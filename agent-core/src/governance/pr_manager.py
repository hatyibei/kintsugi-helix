"""PR manager for GitHub pull request operations.

Creates, updates, and manages pull requests.
"""

from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from src.evolution.code_fixer import CodeFix
from src.governance.blast_radius import BlastRadiusResult
from src.utils.config import Settings

logger = structlog.get_logger()


@dataclass
class PullRequest:
    """Represents a GitHub pull request."""

    number: int
    title: str
    body: str
    url: str
    state: str
    branch: str


class PRManager:
    """Manages GitHub pull requests."""

    def __init__(self, settings: Settings) -> None:
        """Initialize the PR manager.

        Args:
            settings: Application settings.
        """
        self.settings = settings
        self.github_token = settings.github_token
        self.target_repo = settings.target_repo
        self.base_url = "https://api.github.com"

        if not self.github_token:
            logger.warning("GitHub token not configured - PR operations will fail")
        if not self.target_repo:
            logger.warning("Target repo not configured - PR operations will fail")

        logger.info("PRManager initialized", repo=self.target_repo)

    def _get_headers(self) -> dict[str, str]:
        """Get headers for GitHub API requests.

        Returns:
            dict: HTTP headers.
        """
        return {
            "Authorization": f"Bearer {self.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def create_pr(
        self,
        title: str,
        body: str,
        head_branch: str,
        base_branch: str = "main",
    ) -> PullRequest | None:
        """Create a pull request.

        Args:
            title: PR title.
            body: PR body/description.
            head_branch: Branch with changes.
            base_branch: Target branch (default: main).

        Returns:
            PullRequest | None: Created PR or None if failed.
        """
        if not self.github_token or not self.target_repo:
            logger.error("GitHub configuration missing")
            return None

        url = f"{self.base_url}/repos/{self.target_repo}/pulls"

        payload = {
            "title": title,
            "body": body,
            "head": head_branch,
            "base": base_branch,
        }

        logger.info(
            "Creating PR",
            title=title,
            head=head_branch,
            base=base_branch,
        )

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers=self._get_headers(),
                json=payload,
            )

            if response.status_code == 201:
                data = response.json()
                pr = PullRequest(
                    number=data["number"],
                    title=data["title"],
                    body=data["body"],
                    url=data["html_url"],
                    state=data["state"],
                    branch=head_branch,
                )
                logger.info("PR created", number=pr.number, url=pr.url)
                return pr
            else:
                logger.error(
                    "Failed to create PR",
                    status=response.status_code,
                    response=response.text,
                )
                return None

    async def create_fix_pr(
        self,
        fixes: list[CodeFix],
        analysis: BlastRadiusResult,
        head_branch: str,
        incident_id: str | None = None,
    ) -> PullRequest | None:
        """Create a PR for code fixes.

        Args:
            fixes: List of code fixes included.
            analysis: Blast radius analysis result.
            head_branch: Branch with the fixes.
            incident_id: Optional incident ID reference.

        Returns:
            PullRequest | None: Created PR or None if failed.
        """
        title = self._generate_pr_title(fixes, incident_id)
        body = self._generate_pr_body(fixes, analysis, incident_id)

        return await self.create_pr(
            title=title,
            body=body,
            head_branch=head_branch,
        )

    async def merge_pr(
        self,
        pr_number: int,
        merge_method: str = "squash",
    ) -> bool:
        """Merge a pull request.

        Args:
            pr_number: PR number to merge.
            merge_method: Merge method (merge, squash, rebase).

        Returns:
            bool: True if successfully merged.
        """
        if self.settings.dry_run:
            logger.info("Dry run - not merging PR", number=pr_number)
            return True

        url = f"{self.base_url}/repos/{self.target_repo}/pulls/{pr_number}/merge"

        payload = {
            "merge_method": merge_method,
        }

        logger.info("Merging PR", number=pr_number, method=merge_method)

        async with httpx.AsyncClient() as client:
            response = await client.put(
                url,
                headers=self._get_headers(),
                json=payload,
            )

            if response.status_code == 200:
                logger.info("PR merged", number=pr_number)
                return True
            else:
                logger.error(
                    "Failed to merge PR",
                    number=pr_number,
                    status=response.status_code,
                    response=response.text,
                )
                return False

    async def add_labels(self, pr_number: int, labels: list[str]) -> bool:
        """Add labels to a PR.

        Args:
            pr_number: PR number.
            labels: Labels to add.

        Returns:
            bool: True if successful.
        """
        url = f"{self.base_url}/repos/{self.target_repo}/issues/{pr_number}/labels"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers=self._get_headers(),
                json={"labels": labels},
            )

            if response.status_code == 200:
                logger.info("Labels added", pr=pr_number, labels=labels)
                return True
            else:
                logger.error("Failed to add labels", pr=pr_number)
                return False

    async def request_reviewers(
        self,
        pr_number: int,
        reviewers: list[str],
    ) -> bool:
        """Request reviewers for a PR.

        Args:
            pr_number: PR number.
            reviewers: List of GitHub usernames.

        Returns:
            bool: True if successful.
        """
        url = f"{self.base_url}/repos/{self.target_repo}/pulls/{pr_number}/requested_reviewers"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers=self._get_headers(),
                json={"reviewers": reviewers},
            )

            if response.status_code == 201:
                logger.info("Reviewers requested", pr=pr_number, reviewers=reviewers)
                return True
            else:
                logger.error("Failed to request reviewers", pr=pr_number)
                return False

    def _generate_pr_title(
        self,
        fixes: list[CodeFix],
        incident_id: str | None,
    ) -> str:
        """Generate PR title from fixes.

        Args:
            fixes: List of fixes.
            incident_id: Optional incident ID.

        Returns:
            str: Generated title.
        """
        if len(fixes) == 1:
            title = f"fix: {fixes[0].description}"
        else:
            title = f"fix: {len(fixes)} fixes from automated analysis"

        if incident_id:
            title = f"[{incident_id}] {title}"

        return title[:100]  # GitHub title limit

    def _generate_pr_body(
        self,
        fixes: list[CodeFix],
        analysis: BlastRadiusResult,
        incident_id: str | None,
    ) -> str:
        """Generate PR body from fixes and analysis.

        Args:
            fixes: List of fixes.
            analysis: Blast radius analysis.
            incident_id: Optional incident ID.

        Returns:
            str: Generated PR body.
        """
        body_parts = [
            "## Automated Fix by Kintsugi-Helix",
            "",
        ]

        if incident_id:
            body_parts.append(f"**Incident:** `{incident_id}`")
            body_parts.append("")

        body_parts.extend([
            "### Changes",
            "",
        ])

        for fix in fixes:
            body_parts.append(f"- **{fix.file_path}** ({fix.lines_changed} lines)")
            body_parts.append(f"  - {fix.description}")

        body_parts.extend([
            "",
            "### Blast Radius Analysis",
            "",
            f"- **Risk Level:** {analysis.risk_level.upper()}",
            f"- **Score:** {analysis.score:.2f}",
            f"- **Files Affected:** {analysis.files_affected}",
            f"- **Test Coverage:** {analysis.test_coverage_estimate:.0%}",
            "",
            "### Reasoning",
            "",
            analysis.reasoning,
            "",
            "---",
            "*This PR was automatically generated by Kintsugi-Helix*",
        ])

        return "\n".join(body_parts)
