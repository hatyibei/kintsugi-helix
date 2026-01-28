"""OpenRewrite executor for structural refactoring.

Runs OpenRewrite recipes to fix structural issues.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog
import yaml

from src.utils.config import Settings

logger = structlog.get_logger()


@dataclass
class RewriteResult:
    """Result of an OpenRewrite execution."""

    success: bool
    recipe_name: str
    files_changed: list[str]
    output: str
    error_message: str | None


class OpenRewriteExecutor:
    """Executes OpenRewrite recipes for structural improvements."""

    # Common recipes for Java/Spring modernization
    RECIPES = {
        "spring-boot-3": "org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_2",
        "java-21": "org.openrewrite.java.migrate.UpgradeToJava21",
        "common-static-analysis": "org.openrewrite.staticanalysis.CommonStaticAnalysis",
        "security-best-practices": "org.openrewrite.java.security.JavaSecurityBestPractices",
        "testing-best-practices": "org.openrewrite.java.testing.junit5.JUnit5BestPractices",
        "logging-to-slf4j": "org.openrewrite.java.logging.slf4j.Slf4jBestPractices",
    }

    def __init__(self, settings: Settings, project_path: str | Path) -> None:
        """Initialize the OpenRewrite executor.

        Args:
            settings: Application settings.
            project_path: Path to the target Java project.
        """
        self.settings = settings
        self.project_path = Path(project_path)
        logger.info("OpenRewriteExecutor initialized", project=str(self.project_path))

    def get_available_recipes(self) -> dict[str, str]:
        """Get available OpenRewrite recipes.

        Returns:
            dict: Mapping of recipe aliases to full recipe names.
        """
        return self.RECIPES.copy()

    def run_recipe(self, recipe_name: str, dry_run: bool = True) -> RewriteResult:
        """Run a specific OpenRewrite recipe.

        Args:
            recipe_name: Name or alias of the recipe to run.
            dry_run: If True, only show what would change.

        Returns:
            RewriteResult: Result of the recipe execution.
        """
        # Resolve alias to full recipe name
        full_recipe = self.RECIPES.get(recipe_name, recipe_name)

        logger.info(
            "Running OpenRewrite recipe",
            recipe=full_recipe,
            dry_run=dry_run,
        )

        cmd = ["./mvnw"]
        if dry_run:
            cmd.extend(["rewrite:dryRun", f"-Drewrite.activeRecipes={full_recipe}"])
        else:
            cmd.extend(["rewrite:run", f"-Drewrite.activeRecipes={full_recipe}"])

        try:
            result = subprocess.run(
                cmd,
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=300,
            )

            success = result.returncode == 0
            output = result.stdout + result.stderr
            files_changed = self._extract_changed_files(output)

            logger.info(
                "Recipe completed",
                recipe=full_recipe,
                success=success,
                files_changed=len(files_changed),
            )

            return RewriteResult(
                success=success,
                recipe_name=full_recipe,
                files_changed=files_changed,
                output=output,
                error_message=None if success else self._extract_error(output),
            )

        except subprocess.TimeoutExpired:
            logger.error("Recipe timed out", recipe=full_recipe)
            return RewriteResult(
                success=False,
                recipe_name=full_recipe,
                files_changed=[],
                output="",
                error_message="Recipe execution timed out after 300 seconds",
            )

    def run_multiple_recipes(
        self,
        recipe_names: list[str],
        dry_run: bool = True,
    ) -> list[RewriteResult]:
        """Run multiple OpenRewrite recipes.

        Args:
            recipe_names: List of recipe names or aliases.
            dry_run: If True, only show what would change.

        Returns:
            list[RewriteResult]: Results for each recipe.
        """
        results = []
        for recipe in recipe_names:
            result = self.run_recipe(recipe, dry_run=dry_run)
            results.append(result)
            if not result.success and not dry_run:
                logger.warning(
                    "Stopping recipe chain due to failure",
                    failed_recipe=recipe,
                )
                break
        return results

    def analyze_project(self) -> dict[str, Any]:
        """Analyze project for potential improvements.

        Returns:
            dict: Analysis results including recommended recipes.
        """
        logger.info("Analyzing project for improvements")

        recommendations = []

        # Check for outdated patterns by running dry-run of common recipes
        for alias, recipe in self.RECIPES.items():
            result = self.run_recipe(alias, dry_run=True)
            if result.files_changed:
                recommendations.append({
                    "recipe": alias,
                    "full_name": recipe,
                    "files_affected": len(result.files_changed),
                    "files": result.files_changed[:10],  # Limit to first 10
                })

        return {
            "project_path": str(self.project_path),
            "recommendations": recommendations,
            "total_recipes_applicable": len(recommendations),
        }

    def create_custom_recipe(
        self,
        recipe_name: str,
        description: str,
        recipes: list[str],
    ) -> Path:
        """Create a custom composite recipe.

        Args:
            recipe_name: Name for the custom recipe.
            description: Description of what the recipe does.
            recipes: List of recipes to include.

        Returns:
            Path: Path to the created recipe file.
        """
        recipe_config = {
            "type": "specs.openrewrite.org/v1beta/recipe",
            "name": recipe_name,
            "displayName": recipe_name.split(".")[-1],
            "description": description,
            "recipeList": [{"recipe": r} for r in recipes],
        }

        recipe_file = self.project_path / "rewrite.yml"
        existing_config = []

        if recipe_file.exists():
            with open(recipe_file) as f:
                content = f.read()
                if content.strip():
                    existing_config = list(yaml.safe_load_all(content))

        existing_config.append(recipe_config)

        with open(recipe_file, "w") as f:
            yaml.dump_all(existing_config, f, default_flow_style=False)

        logger.info("Custom recipe created", name=recipe_name, path=str(recipe_file))
        return recipe_file

    def _extract_changed_files(self, output: str) -> list[str]:
        """Extract list of changed files from OpenRewrite output.

        Args:
            output: OpenRewrite command output.

        Returns:
            list[str]: List of changed file paths.
        """
        files = []
        for line in output.split("\n"):
            if "would be changed" in line.lower() or "has been changed" in line.lower():
                # Extract file path from the line
                parts = line.split()
                for part in parts:
                    if part.endswith(".java"):
                        files.append(part)
        return files

    def _extract_error(self, output: str) -> str | None:
        """Extract error message from output.

        Args:
            output: Command output.

        Returns:
            str | None: Error message or None.
        """
        lines = output.split("\n")
        for i, line in enumerate(lines):
            if "ERROR" in line or "FAILURE" in line:
                return "\n".join(lines[i : i + 10])
        return None
