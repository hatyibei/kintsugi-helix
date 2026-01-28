"""Code fixer for applying targeted bug fixes.

Uses Gemini to generate code fixes based on root cause analysis.
"""

from dataclasses import dataclass
from pathlib import Path

import structlog

from src.sensing.root_cause_analyzer import RootCauseAnalysis
from src.utils.config import Settings
from src.utils.vertex_client import VertexAIClient

logger = structlog.get_logger()


@dataclass
class CodeFix:
    """Represents a code fix."""

    file_path: str
    original_code: str
    fixed_code: str
    description: str
    lines_changed: int
    confidence: float


class CodeFixer:
    """Generates and applies code fixes."""

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
        if fixed_code.startswith("```java"):
            fixed_code = fixed_code[7:]
        if fixed_code.startswith("```"):
            fixed_code = fixed_code[3:]
        if fixed_code.endswith("```"):
            fixed_code = fixed_code[:-3]
        fixed_code = fixed_code.strip()

        # Calculate lines changed
        original_lines = source_code.strip().split("\n")
        fixed_lines = fixed_code.split("\n")
        lines_changed = sum(
            1 for i, (a, b) in enumerate(zip(original_lines, fixed_lines)) if a != b
        ) + abs(len(original_lines) - len(fixed_lines))

        fix = CodeFix(
            file_path=file_path,
            original_code=source_code,
            fixed_code=fixed_code,
            description=f"Fix for: {analysis.summary}",
            lines_changed=lines_changed,
            confidence=analysis.confidence,
        )

        logger.info(
            "Fix generated",
            file=file_path,
            lines_changed=lines_changed,
            confidence=fix.confidence,
        )

        return fix

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
            logger.info("Fix applied", file=str(file_path))
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
            if "```java" in fixed_code:
                fixed_code = fixed_code.split("```java")[1].split("```")[0]
            elif "```" in fixed_code:
                fixed_code = fixed_code.split("```")[1].split("```")[0]

            original_lines = source_code.strip().split("\n")
            fixed_lines = fixed_code.strip().split("\n")
            lines_changed = sum(
                1 for a, b in zip(original_lines, fixed_lines) if a != b
            ) + abs(len(original_lines) - len(fixed_lines))

            fixes.append(
                CodeFix(
                    file_path=file_path,
                    original_code=source_code,
                    fixed_code=fixed_code.strip(),
                    description=f"Fix option {i + 1}: {['Conservative', 'Moderate', 'Comprehensive'][i]}",
                    lines_changed=lines_changed,
                    confidence=analysis.confidence - (i * 0.1),
                )
            )

        return fixes
