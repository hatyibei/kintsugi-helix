"""Code fixer for applying targeted bug fixes.

Uses Gemini to generate code fixes based on root cause analysis.
Implements self-correction loop with test feedback for iterative improvement.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

from src.sensing.root_cause_analyzer import RootCauseAnalysis
from src.utils.config import Settings
from src.utils.vertex_client import VertexAIClient

logger = structlog.get_logger()


# Maximum retry attempts for fix generation
MAX_FIX_RETRIES = 3


@dataclass
class FixFeedback:
    """Feedback from test execution for fix improvement."""

    error_type: str  # "compilation", "assertion", "exception", "regression"
    error_message: str
    failed_test: str | None = None
    stack_trace: str | None = None
    expected_value: str | None = None
    actual_value: str | None = None
    affected_lines: list[int] = field(default_factory=list)


@dataclass
class CodeFix:
    """Represents a code fix."""

    file_path: str
    original_code: str
    fixed_code: str
    description: str
    lines_changed: int
    confidence: float
    attempt: int = 1
    feedback_history: list[FixFeedback] = field(default_factory=list)


class CodeFixer:
    """Generates and applies code fixes with self-correction capability."""

    def __init__(self, settings: Settings, vertex_client: VertexAIClient) -> None:
        """Initialize the code fixer.

        Args:
            settings: Application settings.
            vertex_client: Vertex AI client instance.
        """
        self.settings = settings
        self.vertex_client = vertex_client
        logger.info("CodeFixer initialized")

    async def generate_fix(
        self,
        analysis: RootCauseAnalysis,
        source_code: str,
        file_path: str,
    ) -> CodeFix:
        """Generate a code fix based on root cause analysis.

        Args:
            analysis: Root cause analysis result.
            source_code: Current source code.
            file_path: Path to the source file.

        Returns:
            CodeFix: The generated fix.
        """
        logger.info(
            "Generating fix",
            file=file_path,
            component=analysis.affected_component,
        )

        prompt = f"""You are an expert Java developer fixing a bug.

## Bug Analysis
- Summary: {analysis.summary}
- Root Cause: {analysis.root_cause}
- Affected Component: {analysis.affected_component}
- Suggested Fix: {analysis.suggested_fix}

## Current Source Code
File: {file_path}
```java
{source_code}
```

## Instructions
1. Fix the bug identified in the analysis
2. Make minimal changes - only fix what's necessary
3. Preserve code style and formatting
4. Do NOT add unnecessary comments or documentation
5. Ensure the fix is complete and correct

Output the COMPLETE fixed file content, not just the changed parts."""

        fixed_code = await self.vertex_client.generate_code(
            specification=prompt,
            language="java",
        )

        # Clean up the response
        fixed_code = self._clean_code_response(fixed_code)

        # Calculate lines changed
        lines_changed = self._calculate_lines_changed(source_code, fixed_code)

        fix = CodeFix(
            file_path=file_path,
            original_code=source_code,
            fixed_code=fixed_code,
            description=f"Fix for: {analysis.summary}",
            lines_changed=lines_changed,
            confidence=analysis.confidence,
            attempt=1,
        )

        logger.info(
            "Fix generated",
            file=file_path,
            lines_changed=lines_changed,
            confidence=fix.confidence,
        )

        return fix

    async def regenerate_fix_with_feedback(
        self,
        original_fix: CodeFix,
        analysis: RootCauseAnalysis,
        feedback: FixFeedback,
        attempt: int,
    ) -> CodeFix:
        """Regenerate a fix based on test feedback.

        This implements the self-correction loop where Gemini receives
        compilation errors or assertion failures and generates improved fixes.

        Args:
            original_fix: The fix that failed.
            analysis: Original root cause analysis.
            feedback: Feedback from test execution.
            attempt: Current attempt number.

        Returns:
            CodeFix: Improved fix incorporating the feedback.
        """
        logger.info(
            "Regenerating fix with feedback",
            file=original_fix.file_path,
            attempt=attempt,
            error_type=feedback.error_type,
        )

        # Build detailed feedback section
        feedback_section = self._format_feedback(feedback)

        # Build history of previous attempts
        history_section = ""
        if original_fix.feedback_history:
            history_items = []
            for i, hist in enumerate(original_fix.feedback_history, 1):
                history_items.append(f"Attempt {i}: {hist.error_type} - {hist.error_message[:200]}")
            history_section = f"""
## Previous Attempts
{chr(10).join(history_items)}
"""

        prompt = f"""You are an expert Java developer. Your previous fix attempt failed.
Analyze the error and generate an improved fix.

## Original Bug Analysis
- Summary: {analysis.summary}
- Root Cause: {analysis.root_cause}
- Affected Component: {analysis.affected_component}
- Suggested Fix: {analysis.suggested_fix}

## Previous Fix Attempt (Attempt {attempt - 1})
```java
{original_fix.fixed_code}
```
{history_section}
## Test Feedback - Why the Fix Failed
{feedback_section}

## Original Source Code (before any fix)
```java
{original_fix.original_code}
```

## Instructions for Improved Fix
1. Carefully analyze WHY the previous fix failed
2. Address the specific error: {feedback.error_type}
3. Generate a COMPLETE fixed file that resolves BOTH the original bug AND the test failure
4. Make sure your fix compiles correctly
5. Ensure null safety and proper exception handling
6. Do NOT leave any TODO comments or unfinished code

Think step by step:
1. What went wrong with the previous fix?
2. What is the correct way to fix this?
3. Generate the complete fixed code.

Output the COMPLETE fixed file content."""

        fixed_code = await self.vertex_client.generate_code(
            specification=prompt,
            language="java",
        )

        # Clean up the response
        fixed_code = self._clean_code_response(fixed_code)

        # Calculate lines changed from original
        lines_changed = self._calculate_lines_changed(original_fix.original_code, fixed_code)

        # Preserve feedback history
        new_history = original_fix.feedback_history.copy()
        new_history.append(feedback)

        new_fix = CodeFix(
            file_path=original_fix.file_path,
            original_code=original_fix.original_code,
            fixed_code=fixed_code,
            description=f"Fix for: {analysis.summary} (attempt {attempt})",
            lines_changed=lines_changed,
            confidence=max(0.1, analysis.confidence - (attempt * 0.1)),
            attempt=attempt,
            feedback_history=new_history,
        )

        logger.info(
            "Improved fix generated",
            file=original_fix.file_path,
            attempt=attempt,
            lines_changed=lines_changed,
        )

        return new_fix

    def _format_feedback(self, feedback: FixFeedback) -> str:
        """Format feedback for the prompt.

        Args:
            feedback: Fix feedback.

        Returns:
            str: Formatted feedback string.
        """
        sections = [
            f"**Error Type**: {feedback.error_type}",
            f"**Error Message**: {feedback.error_message}",
        ]

        if feedback.failed_test:
            sections.append(f"**Failed Test**: {feedback.failed_test}")

        if feedback.expected_value and feedback.actual_value:
            sections.append(f"**Expected**: {feedback.expected_value}")
            sections.append(f"**Actual**: {feedback.actual_value}")

        if feedback.stack_trace:
            # Truncate long stack traces
            trace = feedback.stack_trace
            if len(trace) > 1000:
                trace = trace[:1000] + "\n... (truncated)"
            sections.append(f"**Stack Trace**:\n```\n{trace}\n```")

        if feedback.affected_lines:
            sections.append(f"**Affected Lines**: {feedback.affected_lines}")

        return "\n".join(sections)

    def _clean_code_response(self, code: str) -> str:
        """Clean up code response from LLM.

        Args:
            code: Raw code response.

        Returns:
            str: Cleaned code.
        """
        if code.startswith("```java"):
            code = code[7:]
        if code.startswith("```"):
            code = code[3:]
        if code.endswith("```"):
            code = code[:-3]
        return code.strip()

    def _calculate_lines_changed(self, original: str, fixed: str) -> int:
        """Calculate number of lines changed.

        Args:
            original: Original code.
            fixed: Fixed code.

        Returns:
            int: Number of lines changed.
        """
        original_lines = original.strip().split("\n")
        fixed_lines = fixed.split("\n")
        changed = sum(
            1 for i, (a, b) in enumerate(zip(original_lines, fixed_lines)) if a != b
        )
        changed += abs(len(original_lines) - len(fixed_lines))
        return changed

    def create_feedback_from_test_result(
        self,
        test_output: str,
        error_type: str = "unknown",
    ) -> FixFeedback:
        """Create FixFeedback from raw test output.

        Args:
            test_output: Raw test output string.
            error_type: Type of error (compilation, assertion, exception, regression).

        Returns:
            FixFeedback: Structured feedback object.
        """
        # Detect error type if not specified
        if error_type == "unknown":
            if "COMPILATION ERROR" in test_output or "cannot find symbol" in test_output:
                error_type = "compilation"
            elif "AssertionError" in test_output or "expected:" in test_output.lower():
                error_type = "assertion"
            elif "Exception" in test_output or "Error" in test_output:
                error_type = "exception"
            else:
                error_type = "unknown"

        # Extract error message
        error_message = self._extract_error_message(test_output, error_type)

        # Extract test name if available
        failed_test = None
        test_match = re.search(r"(\w+Test)\.(\w+)", test_output)
        if test_match:
            failed_test = f"{test_match.group(1)}.{test_match.group(2)}"

        # Extract expected/actual for assertion errors
        expected_value = None
        actual_value = None
        exp_act_match = re.search(
            r"expected:\s*<(.+?)>\s*but was:\s*<(.+?)>",
            test_output,
            re.IGNORECASE,
        )
        if exp_act_match:
            expected_value = exp_act_match.group(1)
            actual_value = exp_act_match.group(2)

        # Extract affected lines from compilation errors
        affected_lines = []
        line_matches = re.findall(r"\.java:\[?(\d+)", test_output)
        affected_lines = [int(m) for m in line_matches[:5]]

        # Extract stack trace
        stack_trace = None
        stack_lines = []
        in_stack = False
        for line in test_output.split("\n"):
            if "at " in line and ("Exception" in test_output or "Error" in test_output):
                in_stack = True
            if in_stack:
                if line.strip().startswith("at ") or "Exception" in line or "Error" in line:
                    stack_lines.append(line)
                elif not line.strip():
                    if stack_lines:
                        break
        if stack_lines:
            stack_trace = "\n".join(stack_lines[:20])

        return FixFeedback(
            error_type=error_type,
            error_message=error_message,
            failed_test=failed_test,
            stack_trace=stack_trace,
            expected_value=expected_value,
            actual_value=actual_value,
            affected_lines=affected_lines,
        )

    def _extract_error_message(self, output: str, error_type: str) -> str:
        """Extract concise error message from output.

        Args:
            output: Raw output.
            error_type: Type of error.

        Returns:
            str: Extracted error message.
        """
        lines = output.split("\n")

        if error_type == "compilation":
            for line in lines:
                if "error:" in line.lower() or "cannot find symbol" in line:
                    return line.strip()[:500]

        elif error_type == "assertion":
            for line in lines:
                if "AssertionError" in line or "expected:" in line.lower():
                    return line.strip()[:500]

        elif error_type == "exception":
            for line in lines:
                if "Exception:" in line or "Error:" in line:
                    return line.strip()[:500]

        # Fallback: first non-empty error line
        for line in lines:
            if "ERROR" in line or "FAILURE" in line:
                return line.strip()[:500]

        return output[:500]

    def apply_fix(self, fix: CodeFix, project_path: str | Path) -> bool:
        """Apply a code fix to the file system.

        Args:
            fix: The fix to apply.
            project_path: Base path of the project.

        Returns:
            bool: True if successfully applied.
        """
        if self.settings.dry_run:
            logger.info("Dry run - not applying fix", file=fix.file_path)
            return True

        file_path = Path(project_path) / fix.file_path
        try:
            # Backup original
            backup_path = file_path.with_suffix(file_path.suffix + ".bak")
            if file_path.exists():
                backup_path.write_text(fix.original_code)

            # Apply fix
            file_path.write_text(fix.fixed_code)
            logger.info("Fix applied", file=str(file_path), attempt=fix.attempt)
            return True

        except Exception as e:
            logger.error("Failed to apply fix", file=str(file_path), error=str(e))
            return False

    def rollback_fix(self, fix: CodeFix, project_path: str | Path) -> bool:
        """Rollback a code fix.

        Args:
            fix: The fix to rollback.
            project_path: Base path of the project.

        Returns:
            bool: True if successfully rolled back.
        """
        file_path = Path(project_path) / fix.file_path
        try:
            file_path.write_text(fix.original_code)
            logger.info("Fix rolled back", file=str(file_path))
            return True
        except Exception as e:
            logger.error("Failed to rollback fix", file=str(file_path), error=str(e))
            return False

    async def generate_multiple_fix_options(
        self,
        analysis: RootCauseAnalysis,
        source_code: str,
        file_path: str,
        num_options: int = 3,
    ) -> list[CodeFix]:
        """Generate multiple fix options for review.

        Args:
            analysis: Root cause analysis result.
            source_code: Current source code.
            file_path: Path to the source file.
            num_options: Number of fix options to generate.

        Returns:
            list[CodeFix]: List of fix options.
        """
        logger.info(
            "Generating multiple fix options",
            file=file_path,
            num_options=num_options,
        )

        fixes = []
        for i in range(num_options):
            temperature = 0.2 + (i * 0.2)  # Vary temperature for diversity

            prompt = f"""You are an expert Java developer fixing a bug.
Generate fix option #{i + 1} with a {'conservative' if i == 0 else 'moderate' if i == 1 else 'comprehensive'} approach.

## Bug Analysis
- Summary: {analysis.summary}
- Root Cause: {analysis.root_cause}
- Suggested Fix: {analysis.suggested_fix}

## Current Source Code
```java
{source_code}
```

{'Make minimal targeted changes.' if i == 0 else 'Balance fixes with minor improvements.' if i == 1 else 'Include defensive improvements where appropriate.'}"""

            fixed_code = await self.vertex_client.generate_code(
                specification=prompt,
                language="java",
            )

            # Clean up
            fixed_code = self._clean_code_response(fixed_code)
            lines_changed = self._calculate_lines_changed(source_code, fixed_code)

            fixes.append(
                CodeFix(
                    file_path=file_path,
                    original_code=source_code,
                    fixed_code=fixed_code,
                    description=f"Fix option {i + 1}: {['Conservative', 'Moderate', 'Comprehensive'][i]}",
                    lines_changed=lines_changed,
                    confidence=analysis.confidence - (i * 0.1),
                )
            )

        return fixes
