"""Blast radius analyzer for assessing change impact.

Evaluates the risk and scope of proposed changes using Gemini 1.5 Pro's
long context capability for deep analysis of import graphs and business logic.
"""

import re
from dataclasses import dataclass, field
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
class ImportRelation:
    """Represents an import relationship between classes."""

    class_name: str
    file_path: str | None
    is_internal: bool
    direction: str  # "imports" or "imported_by"


@dataclass
class DependencyGraph:
    """Graph of class dependencies."""

    target_class: str
    imports: list[ImportRelation] = field(default_factory=list)
    imported_by: list[ImportRelation] = field(default_factory=list)
    transitive_depth: int = 0


@dataclass
class BusinessImpact:
    """Business logic impact assessment."""

    affected_features: list[str]
    affected_endpoints: list[str]
    affected_services: list[str]
    user_facing_impact: str
    data_integrity_risk: str
    severity_justification: str


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
    # Enhanced fields
    dependency_graph: DependencyGraph | None = None
    business_impact: BusinessImpact | None = None
    detailed_analysis: dict[str, Any] = field(default_factory=dict)


class ImportGraphAnalyzer:
    """Analyzes import relationships in Java source code."""

    INTERNAL_PACKAGE = "com.kintsugi.demo"

    def __init__(self, project_path: Path) -> None:
        """Initialize the import graph analyzer.

        Args:
            project_path: Path to the project root.
        """
        self.project_path = project_path
        self.source_root = project_path / "src" / "main" / "java"

    def analyze_class(self, file_path: str) -> DependencyGraph:
        """Analyze import relationships for a class.

        Args:
            file_path: Path to the Java file.

        Returns:
            DependencyGraph: Import graph for the class.
        """
        full_path = self.project_path / file_path
        if not full_path.exists():
            return DependencyGraph(target_class=file_path)

        source_code = full_path.read_text()
        class_name = self._extract_class_name(source_code, file_path)

        # Get direct imports
        imports = self._extract_imports(source_code)

        # Find files that import this class
        imported_by = self._find_importers(class_name)

        return DependencyGraph(
            target_class=class_name,
            imports=imports,
            imported_by=imported_by,
            transitive_depth=1,  # Direct dependencies only for now
        )

    def _extract_class_name(self, source_code: str, file_path: str) -> str:
        """Extract the fully qualified class name.

        Args:
            source_code: Java source code.
            file_path: Path to the file.

        Returns:
            str: Fully qualified class name.
        """
        # Extract package
        package_match = re.search(r"package\s+([\w.]+);", source_code)
        package = package_match.group(1) if package_match else ""

        # Extract class name from file
        class_name = Path(file_path).stem

        return f"{package}.{class_name}" if package else class_name

    def _extract_imports(self, source_code: str) -> list[ImportRelation]:
        """Extract import statements from source code.

        Args:
            source_code: Java source code.

        Returns:
            list[ImportRelation]: List of import relations.
        """
        imports = []
        import_pattern = re.compile(r"import\s+(?:static\s+)?([\w.]+);")

        for match in import_pattern.finditer(source_code):
            class_name = match.group(1)
            is_internal = class_name.startswith(self.INTERNAL_PACKAGE)

            file_path = None
            if is_internal:
                file_path = f"src/main/java/{class_name.replace('.', '/')}.java"

            imports.append(
                ImportRelation(
                    class_name=class_name,
                    file_path=file_path,
                    is_internal=is_internal,
                    direction="imports",
                )
            )

        return imports

    def _find_importers(self, class_name: str) -> list[ImportRelation]:
        """Find all classes that import the given class.

        Args:
            class_name: Fully qualified class name.

        Returns:
            list[ImportRelation]: List of importing classes.
        """
        importers = []
        import_statement = f"import {class_name};"

        if not self.source_root.exists():
            return importers

        for java_file in self.source_root.rglob("*.java"):
            try:
                content = java_file.read_text()
                if import_statement in content:
                    # Extract the importing class name
                    importer_class = self._extract_class_name(
                        content,
                        str(java_file.relative_to(self.project_path)),
                    )
                    rel_path = str(java_file.relative_to(self.project_path))

                    importers.append(
                        ImportRelation(
                            class_name=importer_class,
                            file_path=rel_path,
                            is_internal=True,
                            direction="imported_by",
                        )
                    )
            except Exception:
                continue

        return importers

    def get_full_context_for_analysis(
        self,
        file_paths: list[str],
        max_depth: int = 2,
    ) -> dict[str, Any]:
        """Get full context for blast radius analysis.

        Args:
            file_paths: List of files being modified.
            max_depth: Maximum dependency depth to explore.

        Returns:
            dict: Full context including source code and dependencies.
        """
        context = {
            "modified_files": {},
            "dependency_graphs": {},
            "related_sources": {},
        }

        all_related_files = set()

        for file_path in file_paths:
            full_path = self.project_path / file_path
            if full_path.exists():
                context["modified_files"][file_path] = full_path.read_text()

            # Analyze dependencies
            graph = self.analyze_class(file_path)
            context["dependency_graphs"][file_path] = {
                "class": graph.target_class,
                "imports": [
                    {"class": r.class_name, "internal": r.is_internal}
                    for r in graph.imports
                ],
                "imported_by": [
                    {"class": r.class_name, "file": r.file_path}
                    for r in graph.imported_by
                ],
            }

            # Collect related files
            for rel in graph.imports:
                if rel.file_path:
                    all_related_files.add(rel.file_path)
            for rel in graph.imported_by:
                if rel.file_path:
                    all_related_files.add(rel.file_path)

        # Load related source files (limit to avoid token limits)
        for rel_file in list(all_related_files)[:10]:
            full_path = self.project_path / rel_file
            if full_path.exists():
                context["related_sources"][rel_file] = full_path.read_text()

        return context


class BlastRadiusAnalyzer:
    """Analyzes the blast radius (impact) of proposed changes.

    Uses Gemini 1.5 Pro's long context capability for deep analysis
    of import relationships and business logic impact.
    """

    def __init__(
        self,
        settings: Settings,
        vertex_client: VertexAIClient,
        project_path: Path | None = None,
    ) -> None:
        """Initialize the analyzer.

        Args:
            settings: Application settings.
            vertex_client: Vertex AI client instance.
            project_path: Optional path to target project for import analysis.
        """
        self.settings = settings
        self.vertex_client = vertex_client
        self.auto_merge_threshold = settings.auto_merge_threshold
        self.project_path = project_path
        self.import_analyzer = (
            ImportGraphAnalyzer(project_path) if project_path else None
        )
        logger.info(
            "BlastRadiusAnalyzer initialized",
            threshold=self.auto_merge_threshold,
            project=str(project_path) if project_path else None,
        )

    def set_project_path(self, project_path: Path) -> None:
        """Set the project path for import analysis.

        Args:
            project_path: Path to the project root.
        """
        self.project_path = project_path
        self.import_analyzer = ImportGraphAnalyzer(project_path)

    async def analyze(
        self,
        fixes: list[CodeFix],
        project_structure: dict[str, Any] | None = None,
    ) -> BlastRadiusResult:
        """Analyze the blast radius of proposed fixes.

        Uses Gemini 1.5 Pro with full context including:
        - All modified source files
        - Import/dependency graphs
        - Related source files (importers and imported classes)

        Args:
            fixes: List of code fixes to analyze.
            project_structure: Optional project structure information.

        Returns:
            BlastRadiusResult: Analysis result with business context.
        """
        logger.info("Analyzing blast radius", num_fixes=len(fixes))

        # Calculate basic metrics
        total_lines_changed = sum(fix.lines_changed for fix in fixes)
        files_affected = len(fixes)

        # Gather enhanced context with import analysis
        file_paths = [fix.file_path for fix in fixes]
        enhanced_context = {}
        dependency_graphs = {}

        if self.import_analyzer:
            enhanced_context = self.import_analyzer.get_full_context_for_analysis(
                file_paths
            )
            dependency_graphs = enhanced_context.get("dependency_graphs", {})

        # Build comprehensive prompt with full context
        prompt = self._build_comprehensive_prompt(
            fixes,
            enhanced_context,
            project_structure,
        )

        # Define structured output schema
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
                    "description": "List of affected components/modules",
                },
                "test_coverage_estimate": {
                    "type": "number",
                    "description": "Estimated test coverage of affected code (0.0 to 1.0)",
                },
                "reasoning": {
                    "type": "string",
                    "description": "Detailed explanation of the analysis",
                },
                "affected_features": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Business features affected by this change",
                },
                "affected_endpoints": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "API endpoints affected (e.g., 'POST /api/users')",
                },
                "user_facing_impact": {
                    "type": "string",
                    "description": "Description of how end users might be affected",
                },
                "data_integrity_risk": {
                    "type": "string",
                    "enum": ["none", "low", "medium", "high"],
                    "description": "Risk of data corruption or integrity issues",
                },
                "severity_justification": {
                    "type": "string",
                    "description": "Justification for the risk assessment",
                },
                "recommended_reviewers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Suggested reviewer roles (e.g., 'backend-lead', 'security-team')",
                },
                "testing_recommendations": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specific tests that should be run",
                },
            },
            "required": [
                "score",
                "dependencies_affected",
                "test_coverage_estimate",
                "reasoning",
                "affected_features",
                "user_facing_impact",
                "data_integrity_risk",
                "severity_justification",
            ],
        }

        result = await self.vertex_client.generate_structured(
            prompt=prompt,
            response_schema=schema,
            temperature=0.2,
        )

        score = min(1.0, max(0.0, result.get("score", 0.5)))
        risk_level = self._calculate_risk_level(score)
        recommendation = self._get_recommendation(
            score, result.get("test_coverage_estimate", 0.5)
        )

        # Build business impact assessment
        business_impact = BusinessImpact(
            affected_features=result.get("affected_features", []),
            affected_endpoints=result.get("affected_endpoints", []),
            affected_services=result.get("dependencies_affected", []),
            user_facing_impact=result.get("user_facing_impact", "Unknown"),
            data_integrity_risk=result.get("data_integrity_risk", "low"),
            severity_justification=result.get("severity_justification", ""),
        )

        # Build first dependency graph if available
        first_graph = None
        if dependency_graphs:
            first_key = list(dependency_graphs.keys())[0]
            graph_data = dependency_graphs[first_key]
            first_graph = DependencyGraph(
                target_class=graph_data.get("class", ""),
                imports=[
                    ImportRelation(
                        class_name=i["class"],
                        file_path=None,
                        is_internal=i.get("internal", False),
                        direction="imports",
                    )
                    for i in graph_data.get("imports", [])
                ],
                imported_by=[
                    ImportRelation(
                        class_name=i["class"],
                        file_path=i.get("file"),
                        is_internal=True,
                        direction="imported_by",
                    )
                    for i in graph_data.get("imported_by", [])
                ],
            )

        analysis = BlastRadiusResult(
            score=score,
            risk_level=risk_level,
            files_affected=files_affected,
            dependencies_affected=result.get("dependencies_affected", []),
            test_coverage_estimate=result.get("test_coverage_estimate", 0.5),
            recommendation=recommendation,
            reasoning=result.get("reasoning", ""),
            dependency_graph=first_graph,
            business_impact=business_impact,
            detailed_analysis={
                "recommended_reviewers": result.get("recommended_reviewers", []),
                "testing_recommendations": result.get("testing_recommendations", []),
                "total_lines_changed": total_lines_changed,
                "import_depth": len(dependency_graphs),
            },
        )

        logger.info(
            "Blast radius analysis complete",
            score=analysis.score,
            risk_level=analysis.risk_level,
            recommendation=analysis.recommendation,
            affected_features=len(business_impact.affected_features),
        )

        return analysis

    def _build_comprehensive_prompt(
        self,
        fixes: list[CodeFix],
        enhanced_context: dict[str, Any],
        project_structure: dict[str, Any] | None,
    ) -> str:
        """Build comprehensive prompt with full context for analysis.

        Args:
            fixes: List of code fixes.
            enhanced_context: Enhanced context with dependencies.
            project_structure: Optional project structure.

        Returns:
            str: Comprehensive prompt for Gemini.
        """
        # Build changes summary
        changes_summary = []
        for fix in fixes:
            changes_summary.append(
                f"### {fix.file_path}\n"
                f"- Lines changed: {fix.lines_changed}\n"
                f"- Description: {fix.description}\n"
                f"- Confidence: {fix.confidence}\n"
            )

        # Build dependency graph section
        dep_section = ""
        if enhanced_context.get("dependency_graphs"):
            dep_items = []
            for file_path, graph in enhanced_context["dependency_graphs"].items():
                imports = ", ".join(
                    [f"{i['class']}" + (" (internal)" if i.get('internal') else "")
                     for i in graph.get("imports", [])]
                )
                importers = ", ".join(
                    [i["class"] for i in graph.get("imported_by", [])]
                )
                dep_items.append(
                    f"**{graph.get('class', file_path)}**\n"
                    f"  - Imports: {imports or 'none'}\n"
                    f"  - Imported by: {importers or 'none'}"
                )
            dep_section = "\n\n## Dependency Graph\n" + "\n".join(dep_items)

        # Build related sources section (truncated for token limits)
        sources_section = ""
        if enhanced_context.get("related_sources"):
            source_items = []
            for file_path, source in enhanced_context["related_sources"].items():
                # Truncate to first 100 lines
                truncated = "\n".join(source.split("\n")[:100])
                source_items.append(f"### {file_path}\n```java\n{truncated}\n```")
            sources_section = (
                "\n\n## Related Source Files (imported by/imports modified files)\n"
                + "\n".join(source_items[:5])  # Limit to 5 files
            )

        # Build modified code section
        modified_section = ""
        if enhanced_context.get("modified_files"):
            modified_items = []
            for file_path, source in enhanced_context["modified_files"].items():
                modified_items.append(f"### {file_path}\n```java\n{source}\n```")
            modified_section = "\n\n## Modified Files (Current Content)\n" + "\n".join(
                modified_items
            )

        prompt = f"""You are an expert software architect analyzing the blast radius of code changes.
Evaluate not just the number of files affected, but the BUSINESS IMPACT of these changes.

## Code Changes Being Made
{chr(10).join(changes_summary)}
{modified_section}
{dep_section}
{sources_section}

## Project Structure
{project_structure or 'Standard Spring Boot application with controller/service/repository layers'}

## Analysis Requirements

Analyze the changes considering:

1. **Dependency Impact**: How many classes import/use the modified classes?
   Look at the dependency graph and trace the impact through the codebase.

2. **Business Feature Impact**: Which user-facing features might be affected?
   Consider the business domain - is this authentication, payments, user data, etc.?

3. **API Contract Impact**: Do these changes affect any REST endpoints?
   Could external clients or mobile apps be affected?

4. **Data Integrity Risk**: Could these changes cause data corruption,
   inconsistent state, or database issues?

5. **Severity Assessment**: Justify why this is low/medium/high risk
   based on BUSINESS impact, not just technical metrics.

Think step by step:
1. What does this code do in the business context?
2. Who depends on this functionality?
3. What happens if this change has a bug?
4. How would we detect problems?

Provide a comprehensive analysis with specific details."""

        return prompt

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

        score = line_factor * 0.3 + file_factor * 0.4 + confidence_factor * 0.3
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
        # Check business impact if available
        if result.business_impact:
            # Don't auto-merge if data integrity risk is high
            if result.business_impact.data_integrity_risk in ["medium", "high"]:
                return False

        return (
            result.recommendation == "auto_merge"
            and result.score <= self.auto_merge_threshold
            and result.risk_level in ["low"]
        )

    def to_json_report(self, result: BlastRadiusResult) -> dict[str, Any]:
        """Convert result to JSON format for reporting.

        Useful for generating reports for Zenn articles.

        Args:
            result: Blast radius analysis result.

        Returns:
            dict: JSON-serializable report.
        """
        report = {
            "summary": {
                "score": result.score,
                "risk_level": result.risk_level,
                "recommendation": result.recommendation,
                "files_affected": result.files_affected,
                "test_coverage_estimate": result.test_coverage_estimate,
            },
            "reasoning": result.reasoning,
            "dependencies": result.dependencies_affected,
        }

        if result.business_impact:
            report["business_impact"] = {
                "affected_features": result.business_impact.affected_features,
                "affected_endpoints": result.business_impact.affected_endpoints,
                "user_facing_impact": result.business_impact.user_facing_impact,
                "data_integrity_risk": result.business_impact.data_integrity_risk,
                "severity_justification": result.business_impact.severity_justification,
            }

        if result.dependency_graph:
            report["dependency_graph"] = {
                "target_class": result.dependency_graph.target_class,
                "imports_count": len(result.dependency_graph.imports),
                "imported_by_count": len(result.dependency_graph.imported_by),
                "internal_imports": [
                    r.class_name
                    for r in result.dependency_graph.imports
                    if r.is_internal
                ],
                "importers": [
                    r.class_name for r in result.dependency_graph.imported_by
                ],
            }

        if result.detailed_analysis:
            report["detailed"] = result.detailed_analysis

        return report

    def to_mermaid_graph(self, result: BlastRadiusResult) -> str:
        """Generate a Mermaid diagram from blast radius analysis.

        Creates a visual representation of the impact analysis
        for documentation and presentations.

        Args:
            result: Blast radius analysis result.

        Returns:
            str: Mermaid diagram code.
        """
        lines = ["```mermaid", "graph TD"]

        # Define styles based on risk level
        lines.append("    %% Style definitions")
        lines.append("    classDef modified fill:#ff6b6b,stroke:#c92a2a,color:#fff")
        lines.append("    classDef impacted fill:#ffd43b,stroke:#fab005,color:#000")
        lines.append("    classDef safe fill:#69db7c,stroke:#37b24d,color:#000")
        lines.append("    classDef endpoint fill:#748ffc,stroke:#4c6ef5,color:#fff")
        lines.append("    classDef feature fill:#f783ac,stroke:#e64980,color:#fff")
        lines.append("")

        # Add central node (modified class)
        if result.dependency_graph:
            target = result.dependency_graph.target_class
            target_id = self._sanitize_id(target)
            target_short = target.split(".")[-1]
            lines.append(f"    %% Modified class")
            lines.append(f'    {target_id}["{target_short}<br/>📝 MODIFIED"]')
            lines.append(f"    class {target_id} modified")
            lines.append("")

            # Add imports (classes this depends on)
            if result.dependency_graph.imports:
                lines.append("    %% Dependencies (imports)")
                for imp in result.dependency_graph.imports:
                    if imp.is_internal:
                        imp_id = self._sanitize_id(imp.class_name)
                        imp_short = imp.class_name.split(".")[-1]
                        lines.append(f'    {imp_id}["{imp_short}"]')
                        lines.append(f"    {target_id} --> {imp_id}")
                        lines.append(f"    class {imp_id} safe")
                lines.append("")

            # Add importers (classes that depend on this)
            if result.dependency_graph.imported_by:
                lines.append("    %% Impacted classes (imported by)")
                for importer in result.dependency_graph.imported_by:
                    imp_id = self._sanitize_id(importer.class_name)
                    imp_short = importer.class_name.split(".")[-1]
                    lines.append(f'    {imp_id}["{imp_short}<br/>⚠️ IMPACTED"]')
                    lines.append(f"    {imp_id} --> {target_id}")
                    lines.append(f"    class {imp_id} impacted")
                lines.append("")

        # Add business impact
        if result.business_impact:
            lines.append("    %% Business Impact")

            # Add affected endpoints
            for i, endpoint in enumerate(result.business_impact.affected_endpoints[:5]):
                ep_id = f"endpoint_{i}"
                # Escape special characters
                ep_display = endpoint.replace('"', "'")
                lines.append(f'    {ep_id}("{ep_display}")')
                lines.append(f"    class {ep_id} endpoint")

                # Connect to impacted classes
                if result.dependency_graph and result.dependency_graph.imported_by:
                    for importer in result.dependency_graph.imported_by[:2]:
                        imp_id = self._sanitize_id(importer.class_name)
                        lines.append(f"    {imp_id} -.-> {ep_id}")

            lines.append("")

            # Add affected features
            for i, feature in enumerate(result.business_impact.affected_features[:5]):
                feat_id = f"feature_{i}"
                lines.append(f'    {feat_id}{{{{{feature}}}}}')
                lines.append(f"    class {feat_id} feature")

        # Add legend
        lines.append("")
        lines.append("    %% Legend")
        lines.append('    subgraph Legend[" Legend "]')
        lines.append('        L1["📝 Modified"]')
        lines.append('        L2["⚠️ Impacted"]')
        lines.append('        L3["✅ Safe"]')
        lines.append("    end")
        lines.append("    class L1 modified")
        lines.append("    class L2 impacted")
        lines.append("    class L3 safe")

        lines.append("```")

        return "\n".join(lines)

    def to_mermaid_flowchart(self, result: BlastRadiusResult) -> str:
        """Generate a simpler flowchart-style Mermaid diagram.

        Args:
            result: Blast radius analysis result.

        Returns:
            str: Mermaid flowchart code.
        """
        lines = ["```mermaid", "flowchart LR"]

        # Risk level indicator
        risk_emoji = {
            "low": "🟢",
            "medium": "🟡",
            "high": "🟠",
            "critical": "🔴",
        }
        risk = risk_emoji.get(result.risk_level, "⚪")

        lines.append(f"    subgraph Risk[Risk: {risk} {result.risk_level.upper()}]")
        lines.append(f"        score[Score: {result.score:.2f}]")
        lines.append(f"        files[Files: {result.files_affected}]")
        lines.append("    end")
        lines.append("")

        # Modified component
        if result.dependency_graph:
            target_short = result.dependency_graph.target_class.split(".")[-1]
            lines.append(f'    modified[("🔧 {target_short}")]')

            # Impact chain
            lines.append("    modified --> impact")
            lines.append(f'    impact{{"Impacts {len(result.dependency_graph.imported_by)} classes"}}')

        # Business impact summary
        if result.business_impact:
            features = len(result.business_impact.affected_features)
            endpoints = len(result.business_impact.affected_endpoints)
            lines.append(f'    impact --> features["{features} Features"]')
            lines.append(f'    impact --> endpoints["{endpoints} Endpoints"]')

            # Data risk
            data_risk = result.business_impact.data_integrity_risk
            if data_risk in ["medium", "high"]:
                lines.append(f'    impact --> data_risk["⚠️ Data Risk: {data_risk}"]')

        # Recommendation
        rec_emoji = {
            "auto_merge": "✅",
            "fast_review": "👀",
            "full_review": "🔍",
        }
        rec = rec_emoji.get(result.recommendation, "❓")
        lines.append(f'    Risk --> recommendation["{rec} {result.recommendation}"]')

        lines.append("```")

        return "\n".join(lines)

    def _sanitize_id(self, name: str) -> str:
        """Sanitize a name for use as Mermaid node ID.

        Args:
            name: Original name.

        Returns:
            str: Sanitized ID.
        """
        # Replace dots and special chars with underscores
        return name.replace(".", "_").replace("-", "_").replace(" ", "_")
