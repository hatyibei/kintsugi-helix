"""Git utilities for Kintsugi-Helix.

Provides helpers for common Git operations.
"""

from pathlib import Path

import structlog
from git import Repo
from git.exc import GitCommandError, InvalidGitRepositoryError

logger = structlog.get_logger()


class GitHelper:
    """Helper class for Git operations."""

    def __init__(self, repo_path: str | Path) -> None:
        """Initialize GitHelper with a repository path.

        Args:
            repo_path: Path to the Git repository.

        Raises:
            InvalidGitRepositoryError: If the path is not a valid Git repo.
        """
        self.repo_path = Path(repo_path)
        try:
            self.repo = Repo(self.repo_path)
            logger.info("Git repository loaded", path=str(self.repo_path))
        except InvalidGitRepositoryError:
            logger.error("Invalid Git repository", path=str(self.repo_path))
            raise

    @property
    def current_branch(self) -> str:
        """Get the current branch name.

        Returns:
            str: Current branch name.
        """
        return self.repo.active_branch.name

    def create_branch(self, branch_name: str, checkout: bool = True) -> bool:
        """Create a new branch.

        Args:
            branch_name: Name for the new branch.
            checkout: Whether to checkout the new branch.

        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            new_branch = self.repo.create_head(branch_name)
            if checkout:
                new_branch.checkout()
            logger.info("Branch created", branch=branch_name, checkout=checkout)
            return True
        except GitCommandError as e:
            logger.error("Failed to create branch", branch=branch_name, error=str(e))
            return False

    def checkout_branch(self, branch_name: str) -> bool:
        """Checkout an existing branch.

        Args:
            branch_name: Name of the branch to checkout.

        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            self.repo.heads[branch_name].checkout()
            logger.info("Branch checked out", branch=branch_name)
            return True
        except (GitCommandError, IndexError) as e:
            logger.error("Failed to checkout branch", branch=branch_name, error=str(e))
            return False

    def stage_files(self, file_paths: list[str] | str) -> bool:
        """Stage files for commit.

        Args:
            file_paths: Path(s) to stage. Can be a single path or list.

        Returns:
            bool: True if successful, False otherwise.
        """
        if isinstance(file_paths, str):
            file_paths = [file_paths]

        try:
            self.repo.index.add(file_paths)
            logger.info("Files staged", files=file_paths)
            return True
        except GitCommandError as e:
            logger.error("Failed to stage files", files=file_paths, error=str(e))
            return False

    def commit(self, message: str) -> str | None:
        """Create a commit with staged changes.

        Args:
            message: Commit message.

        Returns:
            str | None: Commit SHA if successful, None otherwise.
        """
        try:
            commit = self.repo.index.commit(message)
            logger.info("Commit created", sha=commit.hexsha[:8], message=message[:50])
            return commit.hexsha
        except GitCommandError as e:
            logger.error("Failed to commit", error=str(e))
            return None

    def push(self, remote: str = "origin", branch: str | None = None) -> bool:
        """Push changes to remote.

        Args:
            remote: Remote name (default: origin).
            branch: Branch to push. Uses current branch if not specified.

        Returns:
            bool: True if successful, False otherwise.
        """
        branch = branch or self.current_branch
        try:
            self.repo.remote(remote).push(branch)
            logger.info("Pushed to remote", remote=remote, branch=branch)
            return True
        except GitCommandError as e:
            logger.error("Failed to push", remote=remote, branch=branch, error=str(e))
            return False

    def get_diff(self, staged: bool = False) -> str:
        """Get the current diff.

        Args:
            staged: If True, get staged diff. Otherwise get unstaged diff.

        Returns:
            str: Diff output.
        """
        if staged:
            return self.repo.git.diff("--cached")
        return self.repo.git.diff()

    def get_changed_files(self) -> list[str]:
        """Get list of changed files (staged and unstaged).

        Returns:
            list[str]: List of changed file paths.
        """
        changed = []

        # Staged files
        staged = self.repo.index.diff("HEAD")
        changed.extend([d.a_path for d in staged])

        # Unstaged files
        unstaged = self.repo.index.diff(None)
        changed.extend([d.a_path for d in unstaged])

        # Untracked files
        changed.extend(self.repo.untracked_files)

        return list(set(changed))

    def get_file_content(self, file_path: str, ref: str = "HEAD") -> str | None:
        """Get file content at a specific ref.

        Args:
            file_path: Path to the file.
            ref: Git ref (commit, branch, tag). Default is HEAD.

        Returns:
            str | None: File content or None if not found.
        """
        try:
            blob = self.repo.commit(ref).tree / file_path
            return blob.data_stream.read().decode("utf-8")
        except (KeyError, GitCommandError):
            return None

    def checkout(self, branch_name: str) -> bool:
        """Checkout a branch (alias for checkout_branch).

        Args:
            branch_name: Name of the branch to checkout.

        Returns:
            bool: True if successful, False otherwise.
        """
        return self.checkout_branch(branch_name)

    def reset_hard(self, ref: str = "HEAD") -> bool:
        """Reset the working directory to a specific ref, discarding all changes.

        Args:
            ref: Git ref to reset to. Default is HEAD.

        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            self.repo.git.reset("--hard", ref)
            logger.info("Hard reset performed", ref=ref)
            return True
        except GitCommandError as e:
            logger.error("Failed to perform hard reset", ref=ref, error=str(e))
            return False

    def merge(self, branch_name: str, message: str | None = None) -> bool:
        """Merge a branch into the current branch.

        Args:
            branch_name: Name of the branch to merge.
            message: Optional merge commit message.

        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            if message:
                self.repo.git.merge(branch_name, "-m", message)
            else:
                self.repo.git.merge(branch_name)
            logger.info("Branch merged", branch=branch_name)
            return True
        except GitCommandError as e:
            logger.error("Failed to merge branch", branch=branch_name, error=str(e))
            return False

    def stash(self, message: str | None = None) -> bool:
        """Stash current changes.

        Args:
            message: Optional stash message.

        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            if message:
                self.repo.git.stash("push", "-m", message)
            else:
                self.repo.git.stash("push")
            logger.info("Changes stashed", message=message)
            return True
        except GitCommandError as e:
            logger.error("Failed to stash changes", error=str(e))
            return False

    def stash_pop(self) -> bool:
        """Pop the most recent stash.

        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            self.repo.git.stash("pop")
            logger.info("Stash popped")
            return True
        except GitCommandError as e:
            logger.error("Failed to pop stash", error=str(e))
            return False

    def delete_branch(self, branch_name: str, force: bool = False) -> bool:
        """Delete a branch.

        Args:
            branch_name: Name of the branch to delete.
            force: Force delete even if not merged.

        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            flag = "-D" if force else "-d"
            self.repo.git.branch(flag, branch_name)
            logger.info("Branch deleted", branch=branch_name, force=force)
            return True
        except GitCommandError as e:
            logger.error("Failed to delete branch", branch=branch_name, error=str(e))
            return False

    def has_uncommitted_changes(self) -> bool:
        """Check if there are uncommitted changes.

        Returns:
            bool: True if there are uncommitted changes.
        """
        return self.repo.is_dirty(untracked_files=True)

    def get_commit_log(self, max_count: int = 10) -> list[dict]:
        """Get recent commit log.

        Args:
            max_count: Maximum number of commits to return.

        Returns:
            list[dict]: List of commit info dicts with sha, message, author, date.
        """
        commits = []
        for commit in self.repo.iter_commits(max_count=max_count):
            commits.append({
                "sha": commit.hexsha,
                "short_sha": commit.hexsha[:8],
                "message": commit.message.strip(),
                "author": str(commit.author),
                "date": commit.committed_datetime.isoformat(),
            })
        return commits
