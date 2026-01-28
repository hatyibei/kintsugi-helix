"""Test generator for creating failing tests that reproduce bugs.

Uses Gemini to generate JUnit tests based on error analysis.
"""

from dataclasses import dataclass

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
    imports: list[str]


class TestGenerator:
    """Generates JUnit tests to reproduce bugs."""

    def __init__(self, settings: Settings, vertex_client: VertexAIClient) -> None:
        """Initialize the test generator.

        Args:
            settings: Application settings.
            vertex_client: Vertex AI client instance.
        """
        self.settings = settings
        self.vertex_client = vertex_client
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

        context_parts = [
            f"Issue Summary: {analysis.summary}",
            f"Root Cause: {analysis.root_cause}",
            f"Affected Component: {analysis.affected_component}",
            f"Suggested Fix: {analysis.suggested_fix}",
        ]

        if source_code:
            context_parts.append(f"\nSource Code:\n```java\n{source_code}\n```")

        if existing_tests:
            context_parts.append(
                f"\nExisting Test Style Reference:\n```java\n{existing_tests[:1500]}\n```"
            )

        context = "\n".join(context_parts)

        schema = {
            "type": "object",
            "properties": {
                "class_name": {
                    "type": "string",
                    "description": "Name of the test class",
                },
                "test_method_name": {
                    "type": "string",
                    "description": "Name of the test method",
                },
                "source_code": {
                    "type": "string",
                    "description": "Complete Java test class source code",
                },
                "target_class": {
                    "type": "string",
                    "description": "Fully qualified name of the class being tested",
                },
                "expected_behavior": {
                    "type": "string",
                    "description": "Description of what the test verifies",
                },
                "imports": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Required import statements",
                },
            },
            "required": [
                "class_name",
                "test_method_name",
                "source_code",
                "target_class",
                "expected_behavior",
                "imports",
            ],
        }

        prompt = f"""You are an expert Java test engineer.
Generate a JUnit 5 test that will FAIL and reproduce the following bug.

The test should:
1. Be a complete, compilable JUnit 5 test class
2. Use appropriate assertions to verify the buggy behavior
3. Include clear test method names that describe what's being tested
4. Use @DisplayName annotation for clarity
5. Include necessary imports
6. Be designed to FAIL until the bug is fixed

{context}

Generate a failing test that proves the bug exists."""

        result = await self.vertex_client.generate_structured(
            prompt=prompt,
            response_schema=schema,
            temperature=0.3,
        )

        test = GeneratedTest(
            class_name=result["class_name"],
            test_method_name=result["test_method_name"],
            source_code=result["source_code"],
            target_class=result["target_class"],
            expected_behavior=result["expected_behavior"],
            imports=result["imports"],
        )

        logger.info(
            "Test generated",
            class_name=test.class_name,
            method=test.test_method_name,
            target=test.target_class,
        )

        return test

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

Issue Summary: {analysis.summary}
Root Cause: {analysis.root_cause}
Suggested Fix: {analysis.suggested_fix}

Fixed Code:
```java
{fixed_code}
```

Generate a test that:
1. Will PASS when the fix is in place
2. Tests the corrected behavior thoroughly
3. Acts as a regression test to prevent the bug from returning
4. Uses clear, descriptive test method names"""

        schema = {
            "type": "object",
            "properties": {
                "class_name": {"type": "string"},
                "test_method_name": {"type": "string"},
                "source_code": {"type": "string"},
                "target_class": {"type": "string"},
                "expected_behavior": {"type": "string"},
                "imports": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "class_name",
                "test_method_name",
                "source_code",
                "target_class",
                "expected_behavior",
                "imports",
            ],
        }

        result = await self.vertex_client.generate_structured(
            prompt=prompt,
            response_schema=schema,
            temperature=0.3,
        )

        return GeneratedTest(
            class_name=result["class_name"],
            test_method_name=result["test_method_name"],
            source_code=result["source_code"],
            target_class=result["target_class"],
            expected_behavior=result["expected_behavior"],
            imports=result["imports"],
        )
