"""Main entry point for Kintsugi-Helix agent.

Orchestrates the four pillars: Sensing, Reflection, Evolution, Governance.
Implements the fix-verify loop with retry logic for robust automated repairs.
"""

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from src.evolution.code_fixer import CodeFixer
from src.evolution.openrewrite_executor import OpenRewriteExecutor
from src.governance.blast_radius import BlastRadiusAnalyzer
from src.governance.pr_manager import PRManager
from src.reflection.test_generator import GeneratedTest, TestGenerator
from src.reflection.testcontainer_runner import (
    MavenTestSummary,
    TestContainerRunner,
    TestResult,
)
from src.sensing.log_collector import LogCollector
from src.sensing.root_cause_analyzer import RootCauseAnalyzer, RootCauseAnalysis
from src.utils.config import Settings, get_settings
from src.utils.git_utils import GitHelper
from src.utils.vertex_client import VertexAIClient

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()
console = Console()


# Constants for fix-verify loop
MAX_TEST_GENERATION_RETRIES = 3
MAX_FIX_RETRIES = 3


@dataclass
class FixVerifyResult:
    """Result of a fix-verify cycle."""

    success: bool
    bug_confirmed: bool
    fix_applied: bool
    regression_passed: bool
    test: GeneratedTest | None
    analysis: RootCauseAnalysis | None
    fixes: list[Any]
    attempts: int
    error_message: str | None = None


class KintsugiAgent:
    """Main agent orchestrating the four pillars."""

    def __init__(self, settings: Settings, target_path: str | Path) -> None:
        """Initialize the Kintsugi agent.

        Args:
            settings: Application settings.
            target_path: Path to the target Java project.
        """
        self.settings = settings
        self.target_path = Path(target_path).resolve()

        # Initialize components
        self.vertex_client = VertexAIClient(settings)
        self.vertex_client.initialize()

        # Sensing (感知) - Enhanced with source code extraction
        self.log_collector = LogCollector(settings)
        self.rca = RootCauseAnalyzer(
            settings,
            self.vertex_client,
            target_repo_path=self.target_path,  # Enable auto source extraction
        )

        # Reflection (反射)
        self.test_generator = TestGenerator(settings, self.vertex_client)
        self.test_runner = TestContainerRunner(settings, self.target_path)

        # Evolution (進化)
        self.code_fixer = CodeFixer(settings, self.vertex_client)
        self.openrewrite = OpenRewriteExecutor(settings, self.target_path)

        # Governance (統治)
        self.blast_analyzer = BlastRadiusAnalyzer(settings, self.vertex_client)
        self.pr_manager = PRManager(settings)

        # Git
        self.git = GitHelper(self.target_path)

        logger.info("KintsugiAgent initialized", target=str(self.target_path))

    async def run(self, incident_id: str | None = None) -> dict:
        """Run the full agent workflow.

        Args:
            incident_id: Optional specific incident ID to process.

        Returns:
            dict: Workflow results.
        """
        console.print(
            Panel.fit(
                "[bold blue]Kintsugi-Helix[/bold blue] - Autonomous Maintenance Engineer",
                subtitle="金継ぎ",
            )
        )

        results = {
            "incidents_found": 0,
            "bugs_confirmed": 0,
            "fixes_applied": 0,
            "prs_created": 0,
            "auto_merged": 0,
        }

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            # Phase 1: Sensing (感知)
            task = progress.add_task("[cyan]Sensing - Detecting errors...", total=None)
            incidents = await self._sensing_phase(incident_id)
            results["incidents_found"] = len(incidents)
            progress.update(task, completed=True)

            if not incidents:
                console.print("[yellow]No incidents found. Exiting.")
                return results

            for incident in incidents[:3]:  # Process top 3 incidents
                # Create a temporary branch for this fix
                fix_branch = self._create_fix_branch(incident)

                # Phase 2: Reflection (反射) with fix-verify loop
                task = progress.add_task(
                    f"[magenta]Reflecting on: {incident['signature'][:50]}...",
                    total=None,
                )
                fix_result = await self._reflection_phase_with_fix_loop(incident)
                progress.update(task, completed=True)

                if fix_result.bug_confirmed:
                    results["bugs_confirmed"] += 1

                if not fix_result.success:
                    logger.warning(
                        "Fix-verify loop failed",
                        incident=incident["signature"],
                        error=fix_result.error_message,
                    )
                    # Restore original branch
                    self._cleanup_fix_branch(fix_branch)
                    continue

                results["fixes_applied"] += len(fix_result.fixes)

                # Phase 3: Governance (統治)
                task = progress.add_task(
                    "[yellow]Governing - Analyzing blast radius...",
                    total=None,
                )
                pr_result = await self._governance_phase(
                    fix_result.fixes, incident, fix_branch
                )
                if pr_result.get("pr_created"):
                    results["prs_created"] += 1
                if pr_result.get("auto_merged"):
                    results["auto_merged"] += 1
                progress.update(task, completed=True)

        # Summary
        console.print("\n")
        console.print(
            Panel(
                f"""[bold]Results Summary[/bold]

Incidents Found: {results['incidents_found']}
Bugs Confirmed: {results['bugs_confirmed']}
Fixes Applied: {results['fixes_applied']}
PRs Created: {results['prs_created']}
Auto-merged: {results['auto_merged']}""",
                title="Kintsugi-Helix Complete",
                border_style="green",
            )
        )

        return results

    def _create_fix_branch(self, incident: dict) -> str:
        """Create a temporary branch for the fix.

        Args:
            incident: Incident being fixed.

        Returns:
            str: Name of the created branch.
        """
        signature = incident.get("signature", "unknown")[:20]
        branch_name = f"kintsugi/fix-{signature.replace(':', '-').replace(' ', '-')}"

        if not self.settings.dry_run:
            try:
                self.git.create_branch(branch_name)
                logger.info("Created fix branch", branch=branch_name)
            except Exception as e:
                logger.warning("Failed to create branch", error=str(e))

        return branch_name

    def _cleanup_fix_branch(self, branch_name: str) -> None:
        """Cleanup a failed fix branch.

        Args:
            branch_name: Name of the branch to cleanup.
        """
        if not self.settings.dry_run:
            try:
                # Switch back to main and delete the branch
                self.git.checkout("main")
                # Note: Don't delete the branch in case we need to debug
                logger.info("Switched back to main branch", abandoned=branch_name)
            except Exception as e:
                logger.warning("Failed to cleanup branch", error=str(e))

    async def _sensing_phase(self, incident_id: str | None) -> list:
        """Execute the sensing phase (感知).

        Uses enhanced LogCollector with signature normalization and
        Cloud Run metadata extraction for precise incident grouping.

        Args:
            incident_id: Optional specific incident ID.

        Returns:
            list: Detected incidents with enhanced metadata.
        """
        logger.info("Starting sensing phase (感知)")

        if incident_id:
            # Fetch specific incident by searching logs
            entries = self.log_collector.collect_errors(max_results=200)
            incidents = []

            for entry in entries:
                # Match by signature or message content
                if incident_id in entry.message or incident_id in (entry.trace or ""):
                    # Extract Cloud Run context if available
                    resource = entry.resource
                    if entry.cloud_run_context:
                        resource = entry.cloud_run_context.to_dict()

                    incidents.append({
                        "signature": incident_id,
                        "count": 1,
                        "message": entry.message,
                        "trace": entry.trace,
                        "first_seen": entry.timestamp,
                        "last_seen": entry.timestamp,
                        "resource": resource,
                        "exception_type": None,
                        "affected_methods": [],
                        "cloud_run_services": (
                            [entry.cloud_run_context.service_name]
                            if entry.cloud_run_context
                            else []
                        ),
                    })
        else:
            # Get grouped incidents with enhanced metadata
            incidents = self.log_collector.get_recent_incidents(
                min_occurrences=1,  # Include all for comprehensive analysis
                max_incidents=20,
            )

        # Log summary with enhanced details
        for incident in incidents[:5]:
            logger.info(
                "Incident detected",
                signature=incident.get("signature"),
                count=incident.get("count"),
                exception_type=incident.get("exception_type"),
                services=incident.get("cloud_run_services", []),
            )

        logger.info("Sensing phase complete", incidents=len(incidents))
        return incidents

    async def _reflection_phase_with_fix_loop(
        self, incident: dict
    ) -> FixVerifyResult:
        """Execute the reflection phase with fix-verify loop.

        This implements the full cycle:
        1. Generate failing test to reproduce bug
        2. Verify test fails (bug confirmed)
        3. Generate code fix
        4. Verify test passes (fix works)
        5. Run all tests (no regression)
        6. Retry with feedback if any step fails (max 3 retries)

        Args:
            incident: Incident to reflect on.

        Returns:
            FixVerifyResult: Complete result of the fix-verify cycle.
        """
        logger.info(
            "Starting reflection phase with fix-verify loop (反射)",
            incident=incident["signature"],
        )

        # Initialize result
        result = FixVerifyResult(
            success=False,
            bug_confirmed=False,
            fix_applied=False,
            regression_passed=False,
            test=None,
            analysis=None,
            fixes=[],
            attempts=0,
        )

        # Step 1: Analyze root cause with auto source extraction
        analysis = await self.rca.analyze_incident(incident)
        result.analysis = analysis

        logger.info(
            "Root cause analysis complete",
            summary=analysis.summary,
            confidence=analysis.confidence,
            severity=analysis.severity_assessment,
            error_file=(
                analysis.error_location.file_path if analysis.error_location else None
            ),
            error_line=(
                analysis.error_location.line_number if analysis.error_location else None
            ),
            related_files=analysis.related_files,
        )

        # Step 2: Generate and verify failing test with retry
        test, bug_confirmed = await self._generate_and_verify_test(analysis, incident)

        if not bug_confirmed:
            result.error_message = "Failed to generate a test that reproduces the bug"
            logger.warning("Bug reproduction failed after retries")
            return result

        result.test = test
        result.bug_confirmed = True

        # Step 3-5: Apply fix and verify with retry loop
        for fix_attempt in range(1, MAX_FIX_RETRIES + 1):
            result.attempts = fix_attempt
            logger.info(
                "Fix attempt",
                attempt=fix_attempt,
                max_retries=MAX_FIX_RETRIES,
            )

            # Generate and apply fixes
            fixes = await self._evolution_phase(analysis)

            if not fixes:
                logger.warning("No fixes generated", attempt=fix_attempt)
                continue

            result.fixes = fixes

            # Verify fix makes the test pass
            fix_works, fix_result = self.test_runner.verify_fix(test)

            if not fix_works:
                logger.warning(
                    "Fix did not make test pass",
                    attempt=fix_attempt,
                    error=fix_result.error_message,
                )

                # Provide feedback to regenerate fix
                feedback = self.test_runner.get_test_output_for_feedback(fix_result)
                analysis = await self._enhance_analysis_with_feedback(
                    analysis, feedback, "fix_failed"
                )

                # Revert the fix
                if not self.settings.dry_run:
                    self.git.reset_hard()

                continue

            result.fix_applied = True

            # Verify no regression
            no_regression, summary = self.test_runner.verify_no_regression()

            if not no_regression:
                logger.warning(
                    "Fix caused regression",
                    attempt=fix_attempt,
                    failures=summary.failures,
                    errors=summary.errors,
                )

                # Provide feedback about regression
                feedback = f"Fix caused regression:\n{summary.raw_output[:2000]}"
                analysis = await self._enhance_analysis_with_feedback(
                    analysis, feedback, "regression"
                )

                # Revert the fix
                if not self.settings.dry_run:
                    self.git.reset_hard()

                continue

            # Success! All verifications passed
            result.regression_passed = True
            result.success = True

            logger.info(
                "Fix-verify loop succeeded",
                attempt=fix_attempt,
                fixes=len(fixes),
            )

            return result

        # All retries exhausted
        result.error_message = f"Failed to generate working fix after {MAX_FIX_RETRIES} attempts"
        logger.error("Fix-verify loop exhausted retries")

        return result

    async def _generate_and_verify_test(
        self,
        analysis: RootCauseAnalysis,
        incident: dict,
    ) -> tuple[GeneratedTest | None, bool]:
        """Generate a failing test and verify it reproduces the bug.

        Args:
            analysis: Root cause analysis.
            incident: Original incident.

        Returns:
            tuple: (generated_test, bug_confirmed)
        """
        test = None
        last_result = None

        for attempt in range(1, MAX_TEST_GENERATION_RETRIES + 1):
            logger.info(
                "Test generation attempt",
                attempt=attempt,
                max_retries=MAX_TEST_GENERATION_RETRIES,
            )

            # Generate or regenerate test
            if test is None:
                # First attempt: generate based on analysis
                if analysis.error_location:
                    # Use NPE-specific generation if appropriate
                    exc_type = incident.get("exception_type", "")
                    if "NullPointerException" in exc_type or "NPE" in analysis.summary:
                        # Read source code for the affected file
                        source_code = await self._read_source_file(
                            analysis.error_location.file_path
                        )
                        if source_code:
                            # Extract class and method from location
                            class_name = (
                                analysis.error_location.file_path.split("/")[-1]
                                .replace(".java", "")
                            )
                            method_name = analysis.error_location.method_name or "unknown"

                            test = await self.test_generator.generate_npe_reproduction_test(
                                analysis,
                                source_code,
                                class_name,
                                method_name,
                                analysis.error_location.line_number,
                            )
                        else:
                            test = await self.test_generator.generate_failing_test(
                                analysis
                            )
                    else:
                        test = await self.test_generator.generate_failing_test(analysis)
                else:
                    test = await self.test_generator.generate_failing_test(analysis)
            else:
                # Retry: regenerate with feedback from previous failure
                feedback = self.test_runner.get_test_output_for_feedback(last_result)
                test = await self.test_generator.regenerate_test_with_feedback(
                    test, feedback, analysis, attempt
                )

            if test is None:
                logger.warning("Test generation returned None", attempt=attempt)
                continue

            # Verify the test reproduces the bug (should FAIL)
            bug_confirmed, last_result = self.test_runner.verify_bug_reproduction(test)

            if bug_confirmed:
                logger.info(
                    "Bug reproduction confirmed",
                    test=test.test_method_name,
                    attempt=attempt,
                )
                return test, True

            logger.warning(
                "Test did not reproduce bug",
                attempt=attempt,
                test_passed=last_result.success,
                error=last_result.error_message,
            )

        return test, False

    async def _read_source_file(self, file_path: str) -> str | None:
        """Read source file content.

        Args:
            file_path: Relative path to the source file.

        Returns:
            str | None: File content or None.
        """
        full_path = self.target_path / file_path
        if full_path.exists():
            return full_path.read_text()
        return None

    async def _enhance_analysis_with_feedback(
        self,
        analysis: RootCauseAnalysis,
        feedback: str,
        feedback_type: str,
    ) -> RootCauseAnalysis:
        """Enhance analysis with feedback from failed attempt.

        Args:
            analysis: Original analysis.
            feedback: Feedback from failed attempt.
            feedback_type: Type of feedback (fix_failed, regression).

        Returns:
            RootCauseAnalysis: Enhanced analysis.
        """
        # Add feedback to suggested fixes
        enhanced_fix = f"[Feedback from {feedback_type}]: {feedback[:500]}..."

        if analysis.suggested_fixes:
            analysis.suggested_fixes.insert(0, enhanced_fix)
        else:
            analysis.suggested_fixes = [enhanced_fix]

        return analysis

    async def _reflection_phase(self, incident: dict) -> tuple[bool, any]:
        """Execute the reflection phase (反射) - legacy method for backward compatibility.

        Args:
            incident: Incident to reflect on.

        Returns:
            tuple: (bug_confirmed, analysis)
        """
        result = await self._reflection_phase_with_fix_loop(incident)
        return result.bug_confirmed, result.analysis

    async def _evolution_phase(self, analysis) -> list:
        """Execute the evolution phase.

        Args:
            analysis: Root cause analysis.

        Returns:
            list: Applied fixes.
        """
        logger.info("Starting evolution phase", component=analysis.affected_component)

        fixes = []

        # Generate fix for each affected file
        for file_path in analysis.related_files:
            full_path = self.target_path / file_path
            if not full_path.exists():
                continue

            source_code = full_path.read_text()
            fix = await self.code_fixer.generate_fix(analysis, source_code, file_path)

            if self.code_fixer.apply_fix(fix, self.target_path):
                fixes.append(fix)

        # Run OpenRewrite for structural improvements
        if fixes and not self.settings.dry_run:
            self.openrewrite.run_recipe("common-static-analysis", dry_run=False)

        logger.info("Evolution phase complete", fixes=len(fixes))
        return fixes

    async def _governance_phase(
        self, fixes: list, incident: dict, branch_name: str
    ) -> dict:
        """Execute the governance phase.

        Args:
            fixes: Applied fixes.
            incident: Original incident.
            branch_name: Branch where fixes are applied.

        Returns:
            dict: Governance results.
        """
        logger.info("Starting governance phase")

        result = {"pr_created": False, "auto_merged": False}

        # Analyze blast radius
        analysis = await self.blast_analyzer.analyze(fixes)

        if self.blast_analyzer.should_auto_merge(analysis):
            # Low risk - auto merge
            logger.info("Auto-merge approved", score=analysis.score)

            if not self.settings.dry_run:
                self.git.stage_files([f.file_path for f in fixes])
                self.git.commit(
                    f"fix: {fixes[0].description if fixes else 'automated fix'}\n\n"
                    f"Auto-merged by Kintsugi-Helix (blast radius: {analysis.score:.2f})"
                )
                self.git.checkout("main")
                self.git.merge(branch_name)
                self.git.push()

            result["auto_merged"] = True
        else:
            # Create PR for review
            if not self.settings.dry_run:
                self.git.stage_files([f.file_path for f in fixes])
                self.git.commit(f"fix: {fixes[0].description if fixes else 'automated fix'}")
                self.git.push()

            pr = await self.pr_manager.create_fix_pr(
                fixes=fixes,
                analysis=analysis,
                head_branch=branch_name,
            )

            if pr:
                result["pr_created"] = True
                # Add appropriate labels
                labels = [f"risk:{analysis.risk_level}", "kintsugi-helix"]
                await self.pr_manager.add_labels(pr.number, labels)

        logger.info("Governance phase complete", result=result)
        return result


def parse_args() -> argparse.Namespace:
    """Parse command line arguments.

    Returns:
        argparse.Namespace: Parsed arguments.
    """
    parser = argparse.ArgumentParser(
        description="Kintsugi-Helix - Autonomous Maintenance Engineer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--mode",
        choices=["dev", "prod", "test"],
        default="dev",
        help="Running mode (default: dev)",
    )

    parser.add_argument(
        "--incident-id",
        type=str,
        help="Specific incident ID to process",
    )

    parser.add_argument(
        "--target-path",
        type=str,
        default="../target-app",
        help="Path to target Java project (default: ../target-app)",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without making actual changes",
    )

    parser.add_argument(
        "--serve",
        action="store_true",
        help="Start MCP server instead of running agent",
    )

    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="MCP server port (default: 8080)",
    )

    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Maximum retry attempts for fix-verify loop (default: 3)",
    )

    return parser.parse_args()


async def main() -> None:
    """Main entry point."""
    args = parse_args()

    # Load settings with CLI overrides
    settings = get_settings()
    if args.dry_run:
        settings.dry_run = True
    settings.mode = args.mode

    # Update retry constants if specified
    global MAX_FIX_RETRIES, MAX_TEST_GENERATION_RETRIES
    if args.max_retries:
        MAX_FIX_RETRIES = args.max_retries
        MAX_TEST_GENERATION_RETRIES = args.max_retries

    if args.serve:
        # Start MCP server
        import uvicorn

        from src.mcp.server import create_app

        app = create_app()
        uvicorn.run(app, host="0.0.0.0", port=args.port)
    else:
        # Run agent
        agent = KintsugiAgent(settings, args.target_path)
        results = await agent.run(args.incident_id)

        # Exit with error if no fixes applied and bugs were found
        if results["bugs_confirmed"] > 0 and results["fixes_applied"] == 0:
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
