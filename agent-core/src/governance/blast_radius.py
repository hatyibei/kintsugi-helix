"""Blast radius analyzer for assessing change impact.

Evaluates the risk and scope of proposed changes.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

from src.evolution.code_fixer import CodeFix
from src.utils.config import Settings
from src.utils.vertex_client import VertexAIClient

logger = structlog.get_logger()


# Risk thresholds
LOW_RISK = 0.3
MEDIUM_RISK = 0.6
HIGH_RISK = 1.0


@dataclass
class BlastRadiusResult:
    """Result of blast radius analysis."""

    score: float  # 0.0 to 1.0
    risk_level: str  # "low", "medium", "high", "critical"
    files_affected: int
    dependencies_affected: list[str]
    test_coverage_estimate: float
    recommendation: str  # "auto_merge", "fast_review", "full_review"
    reasoning: str


class BlastRadiusAnalyzer:
    """Analyzes the blast radius (impact) of proposed changes."""

    def __init__(self, settings: Settings, vertex_client: VertexAIClient) -> None:
        """Initialize the analyzer.

        Args:
            settings: Application settings.
            vertex_client: Vertex AI client instance.
        """
        self.settings = settings
        self.vertex_client = vertex_client
        self.auto_merge_threshold = settings.auto_merge_threshold
        logger.info(
            "BlastRadiusAnalyzer initialized",
            threshold=self.auto_merge_threshold,
        )

    async def analyze(
        self,
        fixes: list[CodeFix],
        project_structure: dict[str, Any] | None = None,
    ) -> BlastRadiusResult:
        """Analyze the blast radius of proposed fixes.

        Args:
            fixes: List of code fixes to analyze.
            project_structure: Optional project structure information.

        Returns:
            BlastRadiusResult: Analysis result.
        """
        logger.info("Analyzing blast radius", num_fixes=len(fixes))

        # Calculate basic metrics
        total_lines_changed = sum(fix.lines_changed for fix in fixes)
        files_affected = len(fixes)

        # Build context for AI analysis
        changes_summary = []
        for fix in fixes:
            changes_summary.append(
                f"- {fix.file_path}: {fix.lines_changed} lines, {fix.description}"
            )

        prompt = f"""Analyze the blast radius (impact scope) of the following code changes.

## Changes
{chr(10).join(changes_summary)}

## Metrics
- Total files affected: {files_affected}
- Total lines changed: {total_lines_changed}

## Project Context
{project_structure or 'No additional context available'}

Evaluate:
1. How many other components might be affected?
2. What's the risk of breaking changes?
3. What dependencies are impacted?
4. Estimate test coverage of affected areas

Provide a risk assessment."""

        schema = {
            "type": "object",
            "properties": {
                "score": {
                    "type": "number",
                    "description": "Blast radius score from 0.0 (minimal) to 1.0 (massive)",
                },
                "dependencies_affected": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of affected dependencies/modules",
                },
                "test_coverage_estimate": {
                    "type": "number",
                    "description": "Estimated test coverage of affected code (0.0 to 1.0)",
                },
                "reasoning": {
                    "type": "string",
                    "description": "Explanation of the analysis",
                },
            },
            "required": ["score", "dependencies_affected", "test_coverage_estimate", "reasoning"],
        }

        result = await self.vertex_client.generate_structured(
            prompt=prompt,
            response_schema=schema,
            temperature=0.2,
        )

        score = min(1.0, max(0.0, result["score"]))
        risk_level = self._calculate_risk_level(score)
        recommendation = self._get_recommendation(score, result["test_coverage_estimate"])

        analysis = BlastRadiusResult(
            score=score,
            risk_level=risk_level,
            files_affected=files_affected,
            dependencies_affected=result["dependencies_affected"],
            test_coverage_estimate=result["test_coverage_estimate"],
            recommendation=recommendation,
            reasoning=result["reasoning"],
        )

        logger.info(
            "Blast radius analysis complete",
            score=analysis.score,
            risk_level=analysis.risk_level,
            recommendation=analysis.recommendation,
        )

        return analysis

    def analyze_simple(self, fixes: list[CodeFix]) -> BlastRadiusResult:
        """Perform simple blast radius analysis without AI.

        Args:
            fixes: List of code fixes to analyze.

        Returns:
            BlastRadiusResult: Analysis result.
        """
        total_lines = sum(fix.lines_changed for fix in fixes)
        files_affected = len(fixes)

        # Simple heuristic scoring
        line_factor = min(1.0, total_lines / 500)  # 500 lines = 1.0
        file_factor = min(1.0, files_affected / 10)  # 10 files = 1.0
        confidence_factor = 1 - (sum(fix.confidence for fix in fixes) / len(fixes))

        score = (line_factor * 0.3 + file_factor * 0.4 + confidence_factor * 0.3)
        score = min(1.0, max(0.0, score))

        risk_level = self._calculate_risk_level(score)
        recommendation = self._get_recommendation(score, 0.5)  # Assume 50% coverage

        return BlastRadiusResult(
            score=score,
            risk_level=risk_level,
            files_affected=files_affected,
            dependencies_affected=[],
            test_coverage_estimate=0.5,
            recommendation=recommendation,
            reasoning=f"Simple analysis: {total_lines} lines across {files_affected} files",
        )

    def _calculate_risk_level(self, score: float) -> str:
        """Calculate risk level from score.

        Args:
            score: Blast radius score (0.0-1.0).

        Returns:
            str: Risk level string.
        """
        if score <= LOW_RISK:
            return "low"
        elif score <= MEDIUM_RISK:
            return "medium"
        elif score <= HIGH_RISK:
            return "high"
        return "critical"

    def _get_recommendation(self, score: float, test_coverage: float) -> str:
        """Get merge recommendation based on analysis.

        Args:
            score: Blast radius score.
            test_coverage: Estimated test coverage.

        Returns:
            str: Recommendation string.
        """
        # Auto-merge if low risk and decent coverage
        if score <= self.auto_merge_threshold and test_coverage >= 0.6:
            return "auto_merge"
        # Fast review if medium risk or lower coverage
        elif score <= MEDIUM_RISK:
            return "fast_review"
        # Full review for high risk
        return "full_review"

    def should_auto_merge(self, result: BlastRadiusResult) -> bool:
        """Determine if changes should be auto-merged.

        Args:
            result: Blast radius analysis result.

        Returns:
            bool: True if safe to auto-merge.
        """
        return (
            result.recommendation == "auto_merge"
            and result.score <= self.auto_merge_threshold
            and result.risk_level in ["low"]
        )
