"""Test generator for creating failing tests that reproduce bugs.

Uses Gemini to generate JUnit 5 tests based on error analysis.
反射 (Hansha) - Reflection: Confirming bugs through failing tests.
"""

import re
from dataclasses import dataclass, field
from typing import Any

import structlog

from src.sensing.root_cause_analyzer import RootCauseAnalysis
from src.utils.config import Settings
from src.utils.vertex_client import VertexAIClient

logger = structlog.get_logger()


@dataclass
class GeneratedTest:
    """Represents a generated test case."""

    class_name: str
    test_method_name: str
    source_code: str
    target_class: str
    expected_behavior: str
    imports: list[str] = field(default_factory=list)
    # Enhanced fields
    test_type: str = "bug_reproduction"  # bug_reproduction, regression, edge_case
    edge_cases_covered: list[str] = field(default_factory=list)
    assertions_count: int = 0

    def get_package(self) -> str:
        """Extract package from target class."""
        parts = self.target_class.rsplit(".", 1)
        return parts[0] if len(parts) > 1 else ""

    def get_source_path(self) -> str:
        """Get the path where test file should be written."""
        package_path = self.get_package().replace(".", "/")
        return f"src/test/java/{package_path}/{self.class_name}.java"


@dataclass
class TestGenerationResult:
    """Result of test generation attempt."""

    success: bool
    test: GeneratedTest | None
    error_message: str | None = None
    generation_attempts: int = 1


class EdgeCaseAnalyzer:
    """Analyzes code to identify edge cases for testing."""

    # Common NPE patterns in Java
    NPE_PATTERNS = [
        (r"(\w+)\.(\w+)\(\)", "method call on potentially null object"),
        (r"return\s+(\w+);", "return value could be null"),
        (r"(\w+)\s*==\s*null", "explicit null check indicates null possibility"),
        (r"Optional\.ofNullable", "Optional wrapping indicates null possibility"),
        (r"@Nullable", "explicitly marked as nullable"),
    ]

    # Auto-unboxing NPE patterns
    UNBOXING_PATTERNS = [
        (r"Boolean\s+\w+", "Boolean wrapper that could be null"),
        (r"Integer\s+\w+", "Integer wrapper that could be null"),
        (r"Long\s+\w+", "Long wrapper that could be null"),
        (r"Double\s+\w+", "Double wrapper that could be null"),
    ]

    @classmethod
    def identify_npe_risks(cls, source_code: str) -> list[dict[str, Any]]:
        """Identify potential NPE risks in source code.

        Args:
            source_code: Java source code to analyze.

        Returns:
            list: List of identified NPE risks with descriptions.
        """
        risks = []

        for pattern, description in cls.NPE_PATTERNS:
            matches = re.findall(pattern, source_code)
            if matches:
                risks.append({
                    "pattern": pattern,
                    "description": description,
                    "matches": matches[:5],
                })

        for pattern, description in cls.UNBOXING_PATTERNS:
            matches = re.findall(pattern, source_code)
            if matches:
                risks.append({
                    "pattern": pattern,
                    "description": f"Auto-unboxing NPE risk: {description}",
                    "matches": matches[:5],
                })

        return risks

    @classmethod
    def generate_null_injection_scenarios(
        cls,
        class_name: str,
        method_name: str,
        parameters: list[str],
    ) -> list[dict[str, Any]]:
        """Generate null injection test scenarios.

        Args:
            class_name: Target class name.
            method_name: Target method name.
            parameters: List of parameter names.

        Returns:
            list: Test scenarios with null values.
        """
        scenarios = []

        for param in parameters:
            scenarios.append({
                "name": f"test_{method_name}_with_null_{param}",
                "description": f"Test {method_name} with null {param}",
                "null_params": [param],
            })

        if len(parameters) > 1:
            scenarios.append({
                "name": f"test_{method_name}_with_all_nulls",
                "description": f"Test {method_name} with all null parameters",
                "null_params": parameters,
            })

        return scenarios


class TestGenerator:
    """Generates JUnit 5 tests to reproduce bugs.

    Implements the 反射 (Reflection) pillar with emphasis on:
    - Edge case coverage (null values, boundary conditions)
    - Precise bug reproduction
    - Clear test naming and documentation
    """

    def __init__(self, settings: Settings, vertex_client: VertexAIClient) -> None:
        """Initialize the test generator.

        Args:
            settings: Application settings.
            vertex_client: Vertex AI client instance.
        """
        self.settings = settings
        self.vertex_client = vertex_client
        self.edge_analyzer = EdgeCaseAnalyzer()
        logger.info("TestGenerator initialized")

    async def generate_failing_test(
        self,
        analysis: RootCauseAnalysis,
        source_code: str | None = None,
        existing_tests: str | None = None,
    ) -> GeneratedTest:
        """Generate a failing test that reproduces the bug.

        Args:
            analysis: Root cause analysis result.
            source_code: Source code of the affected class.
            existing_tests: Existing test code for reference.

        Returns:
            GeneratedTest: The generated test case.
        """
        logger.info(
            "Generating failing test",
            component=analysis.affected_component,
            severity=analysis.severity_assessment,
        )

        # Get source code from analysis context if not provided
        if not source_code and analysis.source_context:
            for path, content in analysis.source_context.items():
                if analysis.affected_component in path or analysis.affected_component in content:
                    source_code = content
                    break

        # Analyze source for edge cases
        edge_cases = []
        if source_code:
            npe_risks = self.edge_analyzer.identify_npe_risks(source_code)
            edge_cases = [risk["description"] for risk in npe_risks]

        # Build comprehensive context
        context = self._build_test_generation_context(
            analysis=analysis,
            source_code=source_code,
            existing_tests=existing_tests,
            edge_cases=edge_cases,
        )

        # Generate test using Gemini
        result = await self._generate_test_with_gemini(context, "bug_reproduction")

        test = GeneratedTest(
            class_name=result["class_name"],
            test_method_name=result["test_method_name"],
            source_code=result["source_code"],
            target_class=result["target_class"],
            expected_behavior=result["expected_behavior"],
            imports=result.get("imports", []),
            test_type="bug_reproduction",
            edge_cases_covered=result.get("edge_cases_covered", []),
            assertions_count=result.get("assertions_count", 1),
        )

        logger.info(
            "Test generated",
            class_name=test.class_name,
            method=test.test_method_name,
            target=test.target_class,
            edge_cases=len(test.edge_cases_covered),
        )

        return test

    async def generate_npe_reproduction_test(
        self,
        analysis: RootCauseAnalysis,
        source_code: str,
        class_name: str,
        method_name: str,
        line_number: int | None = None,
    ) -> GeneratedTest:
        """Generate a test specifically for NPE reproduction.

        Focuses on null injection and auto-unboxing scenarios.

        Args:
            analysis: Root cause analysis.
            source_code: Source code of the affected class.
            class_name: Name of the class with the bug.
            method_name: Name of the method with the bug.
            line_number: Optional line number of the bug.

        Returns:
            GeneratedTest: NPE reproduction test.
        """
        logger.info(
            "Generating NPE reproduction test",
            class_name=class_name,
            method=method_name,
            line=line_number,
        )

        prompt = f"""You are an expert Java test engineer specializing in null pointer exception testing.
Generate a JUnit 5 test that will trigger the NullPointerException in the following code.

## Bug Analysis
- Summary: {analysis.summary}
- Root Cause: {analysis.root_cause}
- Affected: {class_name}.{method_name}()
{f'- Line Number: {line_number}' if line_number else ''}

## Source Code
```java
{source_code}
```

## Test Requirements
1. The test MUST trigger a NullPointerException
2. Use assertThrows(NullPointerException.class, ...) to verify the NPE
3. Test both direct null injection and scenarios where null comes from object state
4. Include @DisplayName with clear description of what's being tested
5. The test should FAIL (throw NPE) with current buggy code
6. After the bug is fixed, the same scenario should NOT throw NPE

## NPE Testing Strategies
- For Boolean fields: test auto-unboxing when field is null
- For object fields: test method calls when field is null
- For parameters: inject null values directly
- For equals/hashCode: test with null field values

Generate a complete, compilable JUnit 5 test class."""

        schema = self._get_test_schema()
        result = await self.vertex_client.generate_structured(
            prompt=prompt,
            response_schema=schema,
            model_name="gemini-1.5-pro",
            temperature=0.2,
        )

        return GeneratedTest(
            class_name=result["class_name"],
            test_method_name=result["test_method_name"],
            source_code=result["source_code"],
            target_class=result["target_class"],
            expected_behavior=result["expected_behavior"],
            imports=result.get("imports", []),
            test_type="npe_reproduction",
            edge_cases_covered=["null_injection", "auto_unboxing"],
        )

    async def generate_edge_case_tests(
        self,
        analysis: RootCauseAnalysis,
        source_code: str,
    ) -> list[GeneratedTest]:
        """Generate multiple edge case tests for thorough coverage.

        Args:
            analysis: Root cause analysis.
            source_code: Source code to test.

        Returns:
            list: Multiple edge case tests.
        """
        logger.info("Generating edge case tests")

        npe_risks = self.edge_analyzer.identify_npe_risks(source_code)
        tests = []

        edge_case_types = [
            ("null_field_access", "Test behavior when object fields are null"),
            ("null_parameter", "Test behavior with null method parameters"),
            ("empty_collection", "Test behavior with empty collections"),
        ]

        for edge_type, description in edge_case_types:
            prompt = f"""Generate a JUnit 5 test for edge case: {description}

## Bug Context
- Summary: {analysis.summary}
- Component: {analysis.affected_component}

## Source Code
```java
{source_code}
```

## NPE Risks Identified
{chr(10).join(f'- {risk["description"]}' for risk in npe_risks[:5])}

Generate a test that specifically targets: {edge_type}
The test should expose buggy behavior (FAIL with current code)."""

            try:
                result = await self.vertex_client.generate_structured(
                    prompt=prompt,
                    response_schema=self._get_test_schema(),
                    temperature=0.3,
                )

                tests.append(GeneratedTest(
                    class_name=result["class_name"],
                    test_method_name=result["test_method_name"],
                    source_code=result["source_code"],
                    target_class=result["target_class"],
                    expected_behavior=result["expected_behavior"],
                    imports=result.get("imports", []),
                    test_type="edge_case",
                    edge_cases_covered=[edge_type],
                ))
            except Exception as e:
                logger.warning(f"Failed to generate edge case test for {edge_type}", error=str(e))

        logger.info("Edge case tests generated", count=len(tests))
        return tests

    async def generate_regression_test(
        self,
        analysis: RootCauseAnalysis,
        fixed_code: str,
    ) -> GeneratedTest:
        """Generate a test that verifies the fix works.

        Args:
            analysis: Root cause analysis result.
            fixed_code: The corrected source code.

        Returns:
            GeneratedTest: A test that should PASS with the fix.
        """
        logger.info(
            "Generating regression test",
            component=analysis.affected_component,
        )

        prompt = f"""You are an expert Java test engineer.
Generate a JUnit 5 test that VERIFIES the bug fix works correctly.

## Bug That Was Fixed
- Summary: {analysis.summary}
- Root Cause: {analysis.root_cause}
- Fix Applied: {analysis.suggested_fix}

## Fixed Code
```java
{fixed_code}
```

## Test Requirements
1. The test MUST PASS with the fixed code
2. Test the corrected behavior thoroughly
3. Include assertions that would have FAILED with the buggy code
4. Act as a regression test to prevent the bug from returning
5. Use clear, descriptive test method names with @DisplayName
6. For NPE fixes: verify that null handling works correctly (no exception thrown)
7. Include multiple assertions to verify correct behavior

Generate a complete, compilable JUnit 5 test class."""

        result = await self.vertex_client.generate_structured(
            prompt=prompt,
            response_schema=self._get_test_schema(),
            temperature=0.3,
        )

        return GeneratedTest(
            class_name=result["class_name"],
            test_method_name=result["test_method_name"],
            source_code=result["source_code"],
            target_class=result["target_class"],
            expected_behavior=result["expected_behavior"],
            imports=result.get("imports", []),
            test_type="regression",
        )

    async def regenerate_test_with_feedback(
        self,
        original_test: GeneratedTest,
        error_output: str,
        analysis: RootCauseAnalysis,
        attempt: int = 1,
    ) -> GeneratedTest:
        """Regenerate a test based on failure feedback.

        Args:
            original_test: The test that failed.
            error_output: Error output from test execution.
            analysis: Original root cause analysis.
            attempt: Current attempt number.

        Returns:
            GeneratedTest: Regenerated test.
        """
        logger.info(
            "Regenerating test with feedback",
            original_test=original_test.class_name,
            attempt=attempt,
        )

        prompt = f"""You are an expert Java test engineer. A previously generated test failed to execute properly.
Analyze the error and generate a corrected version.

## Original Test
```java
{original_test.source_code}
```

## Execution Error
```
{error_output[:2000]}
```

## Bug Being Tested
- Summary: {analysis.summary}
- Root Cause: {analysis.root_cause}
- Component: {analysis.affected_component}

## Instructions
1. Analyze WHY the test failed (compilation error? wrong assertion? missing import?)
2. Fix the issues while keeping the same testing intent
3. Ensure all imports are correct
4. Ensure the test still reproduces the original bug
5. Make sure the test is compilable and executable

This is attempt {attempt} of 3. Please be more careful with:
- Import statements (use fully qualified names if needed)
- Method visibility and access
- Correct assertion methods
- Proper test setup

Generate a corrected, complete JUnit 5 test class."""

        result = await self.vertex_client.generate_structured(
            prompt=prompt,
            response_schema=self._get_test_schema(),
            temperature=0.2,
        )

        return GeneratedTest(
            class_name=result["class_name"],
            test_method_name=result["test_method_name"],
            source_code=result["source_code"],
            target_class=result["target_class"],
            expected_behavior=result["expected_behavior"],
            imports=result.get("imports", []),
            test_type=original_test.test_type,
            edge_cases_covered=original_test.edge_cases_covered,
        )

    def _build_test_generation_context(
        self,
        analysis: RootCauseAnalysis,
        source_code: str | None,
        existing_tests: str | None,
        edge_cases: list[str],
    ) -> str:
        """Build comprehensive context for test generation.

        Args:
            analysis: Root cause analysis.
            source_code: Source code of affected class.
            existing_tests: Existing test code for style reference.
            edge_cases: Identified edge cases.

        Returns:
            str: Formatted context string.
        """
        parts = [
            "## Bug Analysis",
            f"- Summary: {analysis.summary}",
            f"- Root Cause: {analysis.root_cause}",
            f"- Affected Component: {analysis.affected_component}",
            f"- Suggested Fix: {analysis.suggested_fix}",
            f"- Severity: {analysis.severity_assessment}",
            f"- Confidence: {analysis.confidence}",
        ]

        if analysis.error_location:
            parts.extend([
                "",
                "## Error Location",
                f"- File: {analysis.error_location.file_path}",
                f"- Line: {analysis.error_location.line_number}",
                f"- Class: {analysis.error_location.class_name}",
                f"- Method: {analysis.error_location.method_name}",
            ])
            if analysis.error_location.code_snippet:
                parts.extend([
                    "",
                    "## Code at Error Location",
                    "```java",
                    analysis.error_location.code_snippet,
                    "```",
                ])

        if source_code:
            parts.extend([
                "",
                "## Full Source Code",
                "```java",
                source_code,
                "```",
            ])

        if edge_cases:
            parts.extend([
                "",
                "## Identified Edge Cases to Test",
            ])
            for ec in edge_cases[:10]:
                parts.append(f"- {ec}")

        if existing_tests:
            parts.extend([
                "",
                "## Existing Test Style Reference",
                "```java",
                existing_tests[:1500],
                "```",
            ])

        return "\n".join(parts)

    async def _generate_test_with_gemini(
        self,
        context: str,
        test_type: str,
    ) -> dict[str, Any]:
        """Generate test using Gemini.

        Args:
            context: Test generation context.
            test_type: Type of test to generate.

        Returns:
            dict: Generated test details.
        """
        prompt = f"""You are an expert Java test engineer specializing in bug reproduction testing.
Generate a JUnit 5 test that will FAIL and reproduce the bug described below.

{context}

## Critical Requirements
1. The test MUST be designed to FAIL with the current buggy code
2. Use appropriate JUnit 5 assertions:
   - assertThrows() for expected exceptions
   - assertEquals(), assertTrue(), assertFalse() for value checks
   - assertNotNull() for null checks
3. Include @DisplayName with a clear description
4. Include all necessary imports
5. The test should be self-contained and not depend on external state
6. For NPE bugs: use assertThrows(NullPointerException.class, () -> ...)

## Test Type: {test_type}
{'Focus on null injection and boundary cases.' if test_type == 'bug_reproduction' else ''}

Generate a complete, compilable JUnit 5 test class that proves the bug exists."""

        return await self.vertex_client.generate_structured(
            prompt=prompt,
            response_schema=self._get_test_schema(),
            model_name="gemini-1.5-pro",
            temperature=0.3,
        )

    def _get_test_schema(self) -> dict[str, Any]:
        """Get JSON schema for test generation response.

        Returns:
            dict: JSON schema.
        """
        return {
            "type": "object",
            "properties": {
                "class_name": {
                    "type": "string",
                    "description": "Name of the test class (e.g., UserNpeTest)",
                },
                "test_method_name": {
                    "type": "string",
                    "description": "Name of the main test method",
                },
                "source_code": {
                    "type": "string",
                    "description": "Complete Java test class source code with package, imports, and test methods",
                },
                "target_class": {
                    "type": "string",
                    "description": "Fully qualified name of the class being tested (e.g., com.kintsugi.demo.model.User)",
                },
                "expected_behavior": {
                    "type": "string",
                    "description": "Description of what the test verifies (what bug it exposes)",
                },
                "imports": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of required import statements",
                },
                "edge_cases_covered": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of edge cases this test covers",
                },
                "assertions_count": {
                    "type": "integer",
                    "description": "Number of assertions in the test",
                },
            },
            "required": [
                "class_name",
                "test_method_name",
                "source_code",
                "target_class",
                "expected_behavior",
            ],
        }
