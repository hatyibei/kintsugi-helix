"""Main entry point for Kintsugi-Helix agent.

Orchestrates the four pillars: Sensing, Reflection, Evolution, Governance.
"""

import argparse
import asyncio
import sys
from pathlib import Path

import structlog
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from src.evolution.code_fixer import CodeFixer
from src.evolution.openrewrite_executor import OpenRewriteExecutor
from src.governance.blast_radius import BlastRadiusAnalyzer
from src.governance.pr_manager import PRManager
from src.reflection.test_generator import TestGenerator
from src.reflection.testcontainer_runner import TestContainerRunner
from src.sensing.log_collector import LogCollector
from src.sensing.root_cause_analyzer import RootCauseAnalyzer
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


class KintsugiAgent:
    """Main agent orchestrating the four pillars."""

    def __init__(self, settings: Settings, target_path: str | Path) -> None:
        """Initialize the Kintsugi agent.

        Args:
            settings: Application settings.
            target_path: Path to the target Java project.
        """
        self.settings = settings
        self.target_path = Path(target_path)

        # Initialize components
        self.vertex_client = VertexAIClient(settings)
        self.vertex_client.initialize()

        # Sensing
        self.log_collector = LogCollector(settings)
        self.rca = RootCauseAnalyzer(settings, self.vertex_client)

        # Reflection
        self.test_generator = TestGenerator(settings, self.vertex_client)
        self.test_runner = TestContainerRunner(settings, self.target_path)

        # Evolution
        self.code_fixer = CodeFixer(settings, self.vertex_client)
        self.openrewrite = OpenRewriteExecutor(settings, self.target_path)

        # Governance
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
                # Phase 2: Reflection (反射)
                task = progress.add_task(
                    f"[magenta]Reflecting on: {incident['signature'][:50]}...",
                    total=None,
                )
                confirmed, analysis = await self._reflection_phase(incident)
                if confirmed:
                    results["bugs_confirmed"] += 1
                progress.update(task, completed=True)

                if not confirmed or not analysis:
                    continue

                # Phase 3: Evolution (進化)
                task = progress.add_task(
                    "[green]Evolving - Generating fixes...",
                    total=None,
                )
                fixes = await self._evolution_phase(analysis)
                results["fixes_applied"] += len(fixes)
                progress.update(task, completed=True)

                if not fixes:
                    continue

                # Phase 4: Governance (統治)
                task = progress.add_task(
                    "[yellow]Governing - Analyzing blast radius...",
                    total=None,
                )
                pr_result = await self._governance_phase(fixes, incident)
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

    async def _sensing_phase(self, incident_id: str | None) -> list:
        """Execute the sensing phase.

        Args:
            incident_id: Optional specific incident ID.

        Returns:
            list: Detected incidents.
        """
        logger.info("Starting sensing phase")

        if incident_id:
            # Fetch specific incident
            entries = self.log_collector.collect_errors()
            incidents = [
                {
                    "signature": incident_id,
                    "count": 1,
                    "message": entry.message,
                    "trace": entry.trace,
                    "first_seen": entry.timestamp,
                    "last_seen": entry.timestamp,
                }
                for entry in entries
                if incident_id in entry.message or incident_id in (entry.trace or "")
            ]
        else:
            incidents = self.log_collector.get_recent_incidents()

        logger.info("Sensing phase complete", incidents=len(incidents))
        return incidents

    async def _reflection_phase(self, incident: dict) -> tuple[bool, any]:
        """Execute the reflection phase.

        Args:
            incident: Incident to reflect on.

        Returns:
            tuple: (bug_confirmed, analysis)
        """
        logger.info("Starting reflection phase", incident=incident["signature"])

        # Analyze root cause
        analysis = await self.rca.analyze_incident(incident)

        # Generate failing test
        test = await self.test_generator.generate_failing_test(analysis)

        # Run test to confirm bug
        bug_confirmed = self.test_runner.verify_bug_reproduction(test)

        logger.info(
            "Reflection phase complete",
            bug_confirmed=bug_confirmed,
            confidence=analysis.confidence,
        )

        return bug_confirmed, analysis

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

    async def _governance_phase(self, fixes: list, incident: dict) -> dict:
        """Execute the governance phase.

        Args:
            fixes: Applied fixes.
            incident: Original incident.

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
            # In real implementation, would commit and push directly
            result["auto_merged"] = True
        else:
            # Create PR for review
            branch_name = f"kintsugi/fix-{incident['signature'][:20].replace(':', '-')}"

            if not self.settings.dry_run:
                self.git.create_branch(branch_name)
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

    return parser.parse_args()


async def main() -> None:
    """Main entry point."""
    args = parse_args()

    # Load settings with CLI overrides
    settings = get_settings()
    if args.dry_run:
        settings.dry_run = True
    settings.mode = args.mode

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
