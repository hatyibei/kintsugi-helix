"""OpenRewrite executor for structural refactoring.

Runs OpenRewrite recipes to fix structural issues.
Includes Gemini-powered recipe selection for autonomous improvement.
"""

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog
import yaml

from src.sensing.root_cause_analyzer import RootCauseAnalysis
from src.utils.config import Settings
from src.utils.vertex_client import VertexAIClient

logger = structlog.get_logger()


@dataclass
class RewriteResult:
    """Result of an OpenRewrite execution."""

    success: bool
    recipe_name: str
    files_changed: list[str]
    output: str
    error_message: str | None


@dataclass
class RecipeRecommendation:
    """A recommended OpenRewrite recipe with justification."""

    recipe_alias: str
    recipe_full_name: str
    relevance_score: float  # 0.0 to 1.0
    justification: str
    estimated_impact: str
    risk_level: str  # "low", "medium", "high"


@dataclass
class CustomRecipeSpec:
    """Specification for a dynamically generated recipe."""

    name: str
    display_name: str
    description: str
    recipe_list: list[str]
    tags: list[str] = field(default_factory=list)


class OpenRewriteExecutor:
    """Executes OpenRewrite recipes for structural improvements.

    Features:
    - Manual recipe execution
    - Gemini-powered recipe auto-selection
    - Dynamic recipe generation
    """

    # Common recipes for Java/Spring modernization
    RECIPES = {
        "spring-boot-3": {
            "full_name": "org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_2",
            "description": "Upgrade to Spring Boot 3.2",
            "tags": ["spring", "upgrade", "framework"],
            "risk": "high",
        },
        "java-21": {
            "full_name": "org.openrewrite.java.migrate.UpgradeToJava21",
            "description": "Upgrade to Java 21 with modern features",
            "tags": ["java", "upgrade", "language"],
            "risk": "medium",
        },
        "common-static-analysis": {
            "full_name": "org.openrewrite.staticanalysis.CommonStaticAnalysis",
            "description": "Apply common static analysis fixes",
            "tags": ["quality", "static-analysis", "best-practices"],
            "risk": "low",
        },
        "security-best-practices": {
            "full_name": "org.openrewrite.java.security.JavaSecurityBestPractices",
            "description": "Apply Java security best practices",
            "tags": ["security", "best-practices", "hardening"],
            "risk": "medium",
        },
        "testing-best-practices": {
            "full_name": "org.openrewrite.java.testing.junit5.JUnit5BestPractices",
            "description": "Apply JUnit 5 testing best practices",
            "tags": ["testing", "junit", "best-practices"],
            "risk": "low",
        },
        "logging-to-slf4j": {
            "full_name": "org.openrewrite.java.logging.slf4j.Slf4jBestPractices",
            "description": "Standardize logging to SLF4J",
            "tags": ["logging", "standardization", "slf4j"],
            "risk": "low",
        },
        "null-safety": {
            "full_name": "org.openrewrite.staticanalysis.NullableOnMethodReturnType",
            "description": "Add null safety annotations",
            "tags": ["null-safety", "annotations", "quality"],
            "risk": "low",
        },
        "simplify-boolean": {
            "full_name": "org.openrewrite.staticanalysis.SimplifyBooleanExpression",
            "description": "Simplify boolean expressions",
            "tags": ["readability", "simplification", "quality"],
            "risk": "low",
        },
        "use-optional": {
            "full_name": "org.openrewrite.java.UseOptionalMethods",
            "description": "Use Optional methods appropriately",
            "tags": ["optional", "null-safety", "modern-java"],
            "risk": "low",
        },
        "use-diamond-operator": {
            "full_name": "org.openrewrite.java.UseDiamondOperator",
            "description": "Use diamond operator for generic types",
            "tags": ["java", "readability", "simplification"],
            "risk": "low",
        },
        "sql-injection-prevention": {
            "full_name": "org.openrewrite.java.security.UseSecureRandom",
            "description": "Prevent SQL injection vulnerabilities",
            "tags": ["security", "sql", "injection"],
            "risk": "medium",
        },
        "modernize-java-streams": {
            "full_name": "org.openrewrite.java.migrate.UseJavaStreamCollectors",
            "description": "Modernize to Java Stream API",
            "tags": ["java", "streams", "modernization"],
            "risk": "low",
        },
    }

    # Bug pattern to recipe mapping
    BUG_PATTERN_RECIPES = {
        "NullPointerException": ["null-safety", "use-optional", "common-static-analysis"],
        "SQLInjection": ["sql-injection-prevention", "security-best-practices"],
        "SQL Injection": ["sql-injection-prevention", "security-best-practices"],
        "N+1": ["common-static-analysis"],  # No direct recipe, but good practices help
        "ConcurrentModification": ["common-static-analysis"],
        "ResourceLeak": ["common-static-analysis"],
        "SecurityVulnerability": ["security-best-practices"],
        "DeprecatedAPI": ["java-21", "spring-boot-3"],
        "TestFailure": ["testing-best-practices"],
    }

    def __init__(
        self,
        settings: Settings,
        project_path: str | Path,
        vertex_client: VertexAIClient | None = None,
    ) -> None:
        """Initialize the OpenRewrite executor.

        Args:
            settings: Application settings.
            project_path: Path to the target Java project.
            vertex_client: Optional Vertex AI client for AI-powered features.
        """
        self.settings = settings
        self.project_path = Path(project_path)
        self.vertex_client = vertex_client
        logger.info("OpenRewriteExecutor initialized", project=str(self.project_path))

    def get_available_recipes(self) -> dict[str, dict[str, Any]]:
        """Get available OpenRewrite recipes with metadata.

        Returns:
            dict: Mapping of recipe aliases to recipe info.
        """
        return self.RECIPES.copy()

    def get_recipe_full_name(self, alias: str) -> str:
        """Get full recipe name from alias.

        Args:
            alias: Recipe alias or full name.

        Returns:
            str: Full recipe name.
        """
        if alias in self.RECIPES:
            return self.RECIPES[alias]["full_name"]
        return alias

    async def recommend_recipes_for_bug(
        self,
        analysis: RootCauseAnalysis,
        source_code: str | None = None,
    ) -> list[RecipeRecommendation]:
        """Use Gemini to recommend recipes for preventing bug recurrence.

        Args:
            analysis: Root cause analysis of the bug.
            source_code: Optional source code for context.

        Returns:
            list[RecipeRecommendation]: Recommended recipes with justifications.
        """
        if not self.vertex_client:
            # Fallback to pattern matching
            return self._match_recipes_by_pattern(analysis)

        logger.info(
            "Getting AI recipe recommendations",
            bug_type=analysis.summary,
        )

        # Build recipe catalog for the prompt
        recipe_catalog = []
        for alias, info in self.RECIPES.items():
            recipe_catalog.append(
                f"- **{alias}**: {info['description']} "
                f"(tags: {', '.join(info['tags'])}, risk: {info['risk']})"
            )

        prompt = f"""You are an expert Java developer analyzing a bug to recommend OpenRewrite recipes.

## Bug Analysis
- Summary: {analysis.summary}
- Root Cause: {analysis.root_cause}
- Affected Component: {analysis.affected_component}
- Severity: {analysis.severity_assessment}

## Source Code Context
```java
{source_code[:2000] if source_code else 'Not available'}
```

## Available OpenRewrite Recipes
{chr(10).join(recipe_catalog)}

## Task
Recommend 1-3 OpenRewrite recipes that would:
1. Help prevent this type of bug from occurring in the future
2. Improve the code quality in the affected area
3. Address the underlying code patterns that led to this bug

Consider:
- Don't recommend high-risk recipes unless absolutely necessary
- Prefer recipes that directly address the root cause
- Consider the ripple effects of applying each recipe

Return your recommendations with justifications."""

        schema = {
            "type": "object",
            "properties": {
                "recommendations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "recipe_alias": {
                                "type": "string",
                                "description": "Recipe alias from the catalog",
                            },
                            "relevance_score": {
                                "type": "number",
                                "description": "Relevance to this bug (0.0 to 1.0)",
                            },
                            "justification": {
                                "type": "string",
                                "description": "Why this recipe helps",
                            },
                            "estimated_impact": {
                                "type": "string",
                                "description": "Expected impact on the codebase",
                            },
                        },
                        "required": ["recipe_alias", "relevance_score", "justification"],
                    },
                },
            },
            "required": ["recommendations"],
        }

        result = await self.vertex_client.generate_structured(
            prompt=prompt,
            response_schema=schema,
            temperature=0.3,
        )

        recommendations = []
        for rec in result.get("recommendations", []):
            alias = rec.get("recipe_alias", "")
            if alias in self.RECIPES:
                recommendations.append(
                    RecipeRecommendation(
                        recipe_alias=alias,
                        recipe_full_name=self.RECIPES[alias]["full_name"],
                        relevance_score=rec.get("relevance_score", 0.5),
                        justification=rec.get("justification", ""),
                        estimated_impact=rec.get("estimated_impact", "Unknown"),
                        risk_level=self.RECIPES[alias]["risk"],
                    )
                )

        logger.info(
            "Recipe recommendations generated",
            count=len(recommendations),
            recipes=[r.recipe_alias for r in recommendations],
        )

        return recommendations

    def _match_recipes_by_pattern(
        self,
        analysis: RootCauseAnalysis,
    ) -> list[RecipeRecommendation]:
        """Match recipes based on bug patterns.

        Args:
            analysis: Root cause analysis.

        Returns:
            list[RecipeRecommendation]: Matched recipes.
        """
        recommendations = []
        matched_aliases = set()

        # Check for pattern matches in summary and root cause
        text = f"{analysis.summary} {analysis.root_cause}".lower()

        for pattern, aliases in self.BUG_PATTERN_RECIPES.items():
            if pattern.lower() in text:
                for alias in aliases:
                    if alias not in matched_aliases and alias in self.RECIPES:
                        matched_aliases.add(alias)
                        recommendations.append(
                            RecipeRecommendation(
                                recipe_alias=alias,
                                recipe_full_name=self.RECIPES[alias]["full_name"],
                                relevance_score=0.7,
                                justification=f"Matched bug pattern: {pattern}",
                                estimated_impact="Based on pattern matching",
                                risk_level=self.RECIPES[alias]["risk"],
                            )
                        )

        # Always recommend common static analysis for quality
        if "common-static-analysis" not in matched_aliases:
            recommendations.append(
                RecipeRecommendation(
                    recipe_alias="common-static-analysis",
                    recipe_full_name=self.RECIPES["common-static-analysis"]["full_name"],
                    relevance_score=0.5,
                    justification="General code quality improvement",
                    estimated_impact="Minor improvements across codebase",
                    risk_level="low",
                )
            )

        return recommendations

    async def generate_custom_recipe(
        self,
        analysis: RootCauseAnalysis,
        additional_recipes: list[str] | None = None,
    ) -> CustomRecipeSpec | None:
        """Generate a custom composite recipe for a specific bug type.

        Args:
            analysis: Root cause analysis.
            additional_recipes: Additional recipes to include.

        Returns:
            CustomRecipeSpec | None: Generated recipe spec or None.
        """
        if not self.vertex_client:
            return None

        logger.info("Generating custom recipe", bug_type=analysis.summary)

        # Get AI recommendations first
        recommendations = await self.recommend_recipes_for_bug(analysis)

        if not recommendations:
            return None

        # Build recipe list from recommendations
        recipe_list = [r.recipe_full_name for r in recommendations if r.relevance_score >= 0.5]

        # Add any additional specified recipes
        if additional_recipes:
            for alias in additional_recipes:
                full_name = self.get_recipe_full_name(alias)
                if full_name not in recipe_list:
                    recipe_list.append(full_name)

        if not recipe_list:
            return None

        # Generate a name for the custom recipe
        bug_type = analysis.summary[:30].replace(" ", "-").lower()
        name = f"com.kintsugi.helix.recipes.Fix{bug_type.title().replace('-', '')}"

        spec = CustomRecipeSpec(
            name=name,
            display_name=f"Fix for: {analysis.summary[:50]}",
            description=(
                f"Auto-generated recipe to address: {analysis.root_cause[:100]}. "
                f"Combines {len(recipe_list)} recipes for comprehensive improvement."
            ),
            recipe_list=recipe_list,
            tags=["auto-generated", "kintsugi-helix", analysis.severity_assessment],
        )

        logger.info(
            "Custom recipe generated",
            name=name,
            recipes=len(recipe_list),
        )

        return spec

    def run_recipe(self, recipe_name: str, dry_run: bool = True) -> RewriteResult:
        """Run a specific OpenRewrite recipe.

        Args:
            recipe_name: Name or alias of the recipe to run.
            dry_run: If True, only show what would change.

        Returns:
            RewriteResult: Result of the recipe execution.
        """
        # Resolve alias to full recipe name
        full_recipe = self.get_recipe_full_name(recipe_name)

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

    def run_recommended_recipes(
        self,
        recommendations: list[RecipeRecommendation],
        dry_run: bool = True,
        max_risk: str = "medium",
    ) -> list[RewriteResult]:
        """Run recommended recipes with risk filtering.

        Args:
            recommendations: List of recipe recommendations.
            dry_run: If True, only show what would change.
            max_risk: Maximum risk level to run ("low", "medium", "high").

        Returns:
            list[RewriteResult]: Results for each recipe run.
        """
        risk_order = {"low": 0, "medium": 1, "high": 2}
        max_risk_level = risk_order.get(max_risk, 1)

        results = []
        for rec in recommendations:
            rec_risk_level = risk_order.get(rec.risk_level, 2)

            if rec_risk_level > max_risk_level:
                logger.info(
                    "Skipping high-risk recipe",
                    recipe=rec.recipe_alias,
                    risk=rec.risk_level,
                    max_allowed=max_risk,
                )
                continue

            result = self.run_recipe(rec.recipe_alias, dry_run=dry_run)
            results.append(result)

            if not result.success and not dry_run:
                logger.warning(
                    "Stopping due to recipe failure",
                    recipe=rec.recipe_alias,
                )
                break

        return results

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

    def apply_custom_recipe(
        self,
        spec: CustomRecipeSpec,
        dry_run: bool = True,
    ) -> RewriteResult:
        """Apply a custom recipe specification.

        Args:
            spec: Custom recipe specification.
            dry_run: If True, only show what would change.

        Returns:
            RewriteResult: Result of applying the recipe.
        """
        # Write the recipe to rewrite.yml
        recipe_file = self.create_custom_recipe(
            recipe_name=spec.name,
            description=spec.description,
            recipes=spec.recipe_list,
        )

        logger.info(
            "Applying custom recipe",
            name=spec.name,
            recipes=len(spec.recipe_list),
        )

        # Run the custom recipe
        return self.run_recipe(spec.name, dry_run=dry_run)

    def analyze_project(self) -> dict[str, Any]:
        """Analyze project for potential improvements.

        Returns:
            dict: Analysis results including recommended recipes.
        """
        logger.info("Analyzing project for improvements")

        recommendations = []

        # Check for outdated patterns by running dry-run of common recipes
        for alias, info in self.RECIPES.items():
            # Skip high-risk recipes in analysis
            if info["risk"] == "high":
                continue

            result = self.run_recipe(alias, dry_run=True)
            if result.files_changed:
                recommendations.append({
                    "recipe": alias,
                    "full_name": info["full_name"],
                    "description": info["description"],
                    "risk": info["risk"],
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
                    try:
                        existing_config = list(yaml.safe_load_all(content))
                    except yaml.YAMLError:
                        existing_config = []

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
