"""MCP Server implementation for Kintsugi-Helix.

Exposes agent capabilities via the Model Context Protocol.
Provides structured outputs for incident analysis, code context retrieval,
and dependency graph exploration for external agents.
"""

import json
from pathlib import Path
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from src.governance.blast_radius import BlastRadiusAnalyzer, ImportGraphAnalyzer
from src.sensing.log_collector import LogCollector
from src.sensing.root_cause_analyzer import (
    RootCauseAnalyzer,
    SourceCodeExtractor,
    StackTraceParser,
)
from src.utils.config import Settings, get_settings
from src.utils.vertex_client import VertexAIClient

logger = structlog.get_logger()


# ============================================================================
# Request/Response Models
# ============================================================================


class ErrorLocation(BaseModel):
    """Location of an error in source code."""

    file_path: str = Field(description="Path to the source file")
    line_number: int | None = Field(default=None, description="Line number where error occurred")
    class_name: str = Field(description="Fully qualified class name")
    method_name: str = Field(description="Method where error occurred")
    code_snippet: str | None = Field(default=None, description="Code snippet around error")


class StackFrameInfo(BaseModel):
    """Information about a stack frame."""

    class_name: str = Field(description="Fully qualified class name")
    method_name: str = Field(description="Method name")
    file_name: str | None = Field(default=None, description="Source file name")
    line_number: int | None = Field(default=None, description="Line number")
    is_internal: bool = Field(description="Whether this is an internal (com.kintsugi.demo) class")
    source_path: str | None = Field(default=None, description="Full path to source file")


class RootCauseAnalysisResponse(BaseModel):
    """Structured root cause analysis response."""

    summary: str = Field(description="Brief one-line summary of the issue")
    root_cause: str = Field(description="Detailed explanation of the root cause")
    affected_component: str = Field(description="The component/class/method where fix is needed")
    suggested_fix: str = Field(description="Suggested code fix or approach")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence level (0.0-1.0)")
    related_files: list[str] = Field(description="List of files that need changes")
    severity_assessment: str = Field(description="Severity: critical, high, medium, low")
    error_location: ErrorLocation | None = Field(default=None, description="Precise error location")
    stack_frames: list[StackFrameInfo] = Field(
        default_factory=list, description="Internal stack frames"
    )
    fix_code_sample: str | None = Field(default=None, description="Sample code showing the fix")


class IncidentInfo(BaseModel):
    """Information about a detected incident."""

    signature: str = Field(description="Unique incident signature")
    count: int = Field(description="Number of occurrences")
    first_seen: str | None = Field(default=None, description="First occurrence timestamp")
    last_seen: str | None = Field(default=None, description="Last occurrence timestamp")
    message: str = Field(description="Error message (truncated)")
    exception_type: str | None = Field(default=None, description="Exception type")
    affected_methods: list[str] = Field(default_factory=list, description="Affected methods")
    cloud_run_services: list[str] = Field(default_factory=list, description="Affected services")


class AnalyzeIncidentRequest(BaseModel):
    """Request to analyze incidents."""

    incident_id: str | None = Field(default=None, description="Specific incident ID to analyze")
    hours: int = Field(default=24, ge=1, le=168, description="Hours to look back")
    min_occurrences: int = Field(default=1, ge=1, description="Minimum occurrences to include")
    include_source: bool = Field(
        default=True, description="Include source code in analysis context"
    )
    target_repo_path: str | None = Field(
        default=None, description="Path to target repository for source extraction"
    )


class AnalyzeIncidentResponse(BaseModel):
    """Response from incident analysis."""

    success: bool = Field(description="Whether analysis was successful")
    incidents: list[IncidentInfo] = Field(description="Detected incidents")
    analyses: list[RootCauseAnalysisResponse] = Field(description="Analysis results")
    total_incidents: int = Field(description="Total number of incidents found")
    analyzed_count: int = Field(description="Number of incidents analyzed")


class GetCodeContextRequest(BaseModel):
    """Request to get code context for a file."""

    file_path: str = Field(description="Path to the source file (relative to repo root)")
    repo_path: str = Field(description="Path to the repository root")
    include_imports: bool = Field(default=True, description="Include import analysis")
    include_signatures: bool = Field(default=True, description="Include method signatures")
    include_dependencies: bool = Field(default=True, description="Include dependency graph")
    context_line: int | None = Field(default=None, description="Line number to highlight")
    context_range: int = Field(default=10, description="Lines of context around highlighted line")


class ImportInfo(BaseModel):
    """Information about an import statement."""

    class_name: str = Field(description="Fully qualified class name")
    is_internal: bool = Field(description="Whether this is an internal class")
    source_path: str | None = Field(default=None, description="Path to source if internal")


class MethodSignature(BaseModel):
    """Method signature information."""

    signature: str = Field(description="Full method signature")


class DependencyInfo(BaseModel):
    """Information about class dependencies."""

    target_class: str = Field(description="The class being analyzed")
    imports: list[ImportInfo] = Field(default_factory=list, description="Classes this imports")
    imported_by: list[ImportInfo] = Field(
        default_factory=list, description="Classes that import this"
    )


class GetCodeContextResponse(BaseModel):
    """Response with code context."""

    success: bool = Field(description="Whether retrieval was successful")
    file_path: str = Field(description="Requested file path")
    source_code: str | None = Field(default=None, description="Full source code")
    highlighted_snippet: str | None = Field(default=None, description="Highlighted code snippet")
    class_signature: str | None = Field(default=None, description="Class/interface signature")
    imports: list[ImportInfo] = Field(default_factory=list, description="Import information")
    method_signatures: list[MethodSignature] = Field(
        default_factory=list, description="Method signatures"
    )
    dependencies: DependencyInfo | None = Field(
        default=None, description="Dependency graph information"
    )
    error: str | None = Field(default=None, description="Error message if failed")


class GetDependencyGraphRequest(BaseModel):
    """Request to get dependency graph for files."""

    file_paths: list[str] = Field(description="Paths to source files (relative to repo root)")
    repo_path: str = Field(description="Path to the repository root")
    include_source: bool = Field(default=False, description="Include source code of dependencies")
    max_depth: int = Field(default=1, ge=1, le=3, description="Maximum dependency depth")


class DependencyGraphResponse(BaseModel):
    """Response with dependency graph."""

    success: bool = Field(description="Whether analysis was successful")
    graphs: dict[str, DependencyInfo] = Field(
        default_factory=dict, description="Dependency graphs per file"
    )
    related_sources: dict[str, str] = Field(
        default_factory=dict, description="Source code of related files"
    )
    error: str | None = Field(default=None, description="Error message if failed")


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(description="Health status")
    version: str = Field(description="API version")
    components: dict[str, str] = Field(description="Component status")


class ToolInfo(BaseModel):
    """Information about an MCP tool."""

    name: str = Field(description="Tool name")
    description: str = Field(description="Tool description")
    parameters: dict[str, str] = Field(description="Parameter descriptions")


class ListToolsResponse(BaseModel):
    """Response listing available tools."""

    tools: list[ToolInfo] = Field(description="Available tools")


# ============================================================================
# MCP Server Implementation
# ============================================================================


class MCPServer:
    """MCP Server exposing Kintsugi-Helix capabilities.

    Provides tools for:
    - Incident analysis with source code context
    - Code context retrieval with dependency analysis
    - Dependency graph exploration
    - Log searching and filtering
    """

    def __init__(
        self,
        settings: Settings | None = None,
        default_repo_path: str | None = None,
    ) -> None:
        """Initialize the MCP server.

        Args:
            settings: Optional settings. Uses default if not provided.
            default_repo_path: Default path to target repository.
        """
        self.settings = settings or get_settings()
        self.default_repo_path = Path(default_repo_path) if default_repo_path else None
        self.app = FastAPI(
            title="Kintsugi-Helix MCP Server",
            description="Model Context Protocol server for autonomous maintenance",
            version="0.3.0",
        )
        self._setup_routes()
        self._initialized = False

        logger.info("MCPServer created", default_repo=str(self.default_repo_path))

    def _setup_routes(self) -> None:
        """Set up FastAPI routes."""

        @self.app.get("/health", response_model=HealthResponse)
        async def health_check() -> HealthResponse:
            """Health check endpoint."""
            components = {
                "api": "healthy",
                "vertex_ai": "not_initialized" if not self._initialized else "healthy",
                "log_collector": "not_initialized" if not self._initialized else "healthy",
            }
            return HealthResponse(
                status="healthy",
                version="0.3.0",
                components=components,
            )

        @self.app.post("/tools/analyze-incidents", response_model=AnalyzeIncidentResponse)
        async def analyze_incidents(
            request: AnalyzeIncidentRequest,
        ) -> AnalyzeIncidentResponse:
            """Analyze recent incidents from Cloud Logging.

            Returns structured RootCauseAnalysis for each incident with
            precise code location and fix suggestions.
            """
            try:
                self._ensure_initialized()

                # Set up repository path for source extraction
                repo_path = None
                if request.target_repo_path:
                    repo_path = Path(request.target_repo_path)
                elif self.default_repo_path:
                    repo_path = self.default_repo_path

                if repo_path and request.include_source:
                    self.analyzer.set_target_repo(repo_path)

                # Get incidents
                raw_incidents = self.log_collector.get_recent_incidents(
                    hours=request.hours,
                    min_occurrences=request.min_occurrences,
                )

                # Convert to structured format
                incidents = []
                for inc in raw_incidents:
                    incidents.append(
                        IncidentInfo(
                            signature=inc["signature"],
                            count=inc["count"],
                            first_seen=inc.get("first_seen"),
                            last_seen=inc.get("last_seen"),
                            message=inc.get("message", "")[:500],
                            exception_type=inc.get("exception_type"),
                            affected_methods=inc.get("affected_methods", []),
                            cloud_run_services=inc.get("cloud_run_services", []),
                        )
                    )

                # Analyze each incident (limit to 5)
                analyses = []
                for incident_dict in raw_incidents[:5]:
                    analysis = await self.analyzer.analyze_incident(incident_dict)
                    analyses.append(self._convert_analysis_to_response(analysis))

                return AnalyzeIncidentResponse(
                    success=True,
                    incidents=incidents,
                    analyses=analyses,
                    total_incidents=len(raw_incidents),
                    analyzed_count=len(analyses),
                )

            except Exception as e:
                logger.error("Failed to analyze incidents", error=str(e))
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.post("/tools/get-code-context", response_model=GetCodeContextResponse)
        async def get_code_context(
            request: GetCodeContextRequest,
        ) -> GetCodeContextResponse:
            """Get source code context for a file.

            Returns source code along with import analysis, method signatures,
            and dependency information. Enables active exploration by external agents.
            """
            try:
                repo_path = Path(request.repo_path)
                if not repo_path.exists():
                    return GetCodeContextResponse(
                        success=False,
                        file_path=request.file_path,
                        error=f"Repository path not found: {request.repo_path}",
                    )

                extractor = SourceCodeExtractor(repo_path)
                source_file = repo_path / request.file_path

                if not source_file.exists():
                    return GetCodeContextResponse(
                        success=False,
                        file_path=request.file_path,
                        error=f"File not found: {request.file_path}",
                    )

                # Read source code
                source_code = source_file.read_text()

                # Get highlighted snippet if context line specified
                highlighted_snippet = None
                if request.context_line:
                    lines = source_code.split("\n")
                    line_idx = request.context_line - 1
                    start = max(0, line_idx - request.context_range)
                    end = min(len(lines), line_idx + request.context_range + 1)

                    snippet_lines = []
                    for i in range(start, end):
                        marker = ">>>" if i == line_idx else "   "
                        snippet_lines.append(f"{marker} {i + 1:4d} | {lines[i]}")
                    highlighted_snippet = "\n".join(snippet_lines)

                # Extract imports
                imports = []
                if request.include_imports:
                    import_list = extractor.extract_imports(source_code)
                    for imp in import_list:
                        is_internal = imp.startswith("com.kintsugi.demo")
                        source_path = None
                        if is_internal:
                            source_path = f"src/main/java/{imp.replace('.', '/')}.java"
                        imports.append(
                            ImportInfo(
                                class_name=imp,
                                is_internal=is_internal,
                                source_path=source_path,
                            )
                        )

                # Extract class signature
                class_signature = None
                if request.include_signatures:
                    class_signature = extractor.get_class_signature(source_code)

                # Extract method signatures
                method_signatures = []
                if request.include_signatures:
                    sigs = extractor.get_method_signatures(source_code)
                    method_signatures = [MethodSignature(signature=s) for s in sigs]

                # Get dependency graph if requested
                dependencies = None
                if request.include_dependencies:
                    import_analyzer = ImportGraphAnalyzer(repo_path)
                    graph = import_analyzer.analyze_class(request.file_path)

                    dep_imports = [
                        ImportInfo(
                            class_name=r.class_name,
                            is_internal=r.is_internal,
                            source_path=r.file_path,
                        )
                        for r in graph.imports
                    ]
                    dep_imported_by = [
                        ImportInfo(
                            class_name=r.class_name,
                            is_internal=r.is_internal,
                            source_path=r.file_path,
                        )
                        for r in graph.imported_by
                    ]

                    dependencies = DependencyInfo(
                        target_class=graph.target_class,
                        imports=dep_imports,
                        imported_by=dep_imported_by,
                    )

                return GetCodeContextResponse(
                    success=True,
                    file_path=request.file_path,
                    source_code=source_code,
                    highlighted_snippet=highlighted_snippet,
                    class_signature=class_signature,
                    imports=imports,
                    method_signatures=method_signatures,
                    dependencies=dependencies,
                )

            except Exception as e:
                logger.error("Failed to get code context", error=str(e))
                return GetCodeContextResponse(
                    success=False,
                    file_path=request.file_path,
                    error=str(e),
                )

        @self.app.post("/tools/get-dependency-graph", response_model=DependencyGraphResponse)
        async def get_dependency_graph(
            request: GetDependencyGraphRequest,
        ) -> DependencyGraphResponse:
            """Get dependency graph for multiple files.

            Analyzes import relationships to understand how changes
            might ripple through the codebase.
            """
            try:
                repo_path = Path(request.repo_path)
                if not repo_path.exists():
                    return DependencyGraphResponse(
                        success=False,
                        error=f"Repository path not found: {request.repo_path}",
                    )

                import_analyzer = ImportGraphAnalyzer(repo_path)
                context = import_analyzer.get_full_context_for_analysis(
                    request.file_paths,
                    max_depth=request.max_depth,
                )

                # Convert to response format
                graphs = {}
                for file_path, graph_data in context.get("dependency_graphs", {}).items():
                    dep_imports = [
                        ImportInfo(
                            class_name=i["class"],
                            is_internal=i.get("internal", False),
                            source_path=None,
                        )
                        for i in graph_data.get("imports", [])
                    ]
                    dep_imported_by = [
                        ImportInfo(
                            class_name=i["class"],
                            is_internal=True,
                            source_path=i.get("file"),
                        )
                        for i in graph_data.get("imported_by", [])
                    ]

                    graphs[file_path] = DependencyInfo(
                        target_class=graph_data.get("class", file_path),
                        imports=dep_imports,
                        imported_by=dep_imported_by,
                    )

                # Include related sources if requested
                related_sources = {}
                if request.include_source:
                    related_sources = context.get("related_sources", {})

                return DependencyGraphResponse(
                    success=True,
                    graphs=graphs,
                    related_sources=related_sources,
                )

            except Exception as e:
                logger.error("Failed to get dependency graph", error=str(e))
                return DependencyGraphResponse(
                    success=False,
                    error=str(e),
                )

        @self.app.post("/tools/parse-stack-trace")
        async def parse_stack_trace(stack_trace: str) -> dict[str, Any]:
            """Parse a Java stack trace and extract structured information.

            Useful for understanding error locations without full analysis.
            """
            try:
                frames = StackTraceParser.parse(stack_trace)
                internal_frames = StackTraceParser.extract_internal_frames(stack_trace)
                exc_type, exc_msg = StackTraceParser.extract_exception_info(stack_trace)
                signature = StackTraceParser.generate_signature(stack_trace)
                root_frame = StackTraceParser.get_root_cause_frame(stack_trace)

                return {
                    "success": True,
                    "signature": signature,
                    "exception_type": exc_type,
                    "exception_message": exc_msg,
                    "total_frames": len(frames),
                    "internal_frames_count": len(internal_frames),
                    "root_cause_frame": (
                        {
                            "class_name": root_frame.class_name,
                            "method_name": root_frame.method_name,
                            "file_name": root_frame.file_name,
                            "line_number": root_frame.line_number,
                            "source_path": root_frame.source_path,
                        }
                        if root_frame
                        else None
                    ),
                    "internal_frames": [
                        {
                            "class_name": f.class_name,
                            "method_name": f.method_name,
                            "file_name": f.file_name,
                            "line_number": f.line_number,
                            "source_path": f.source_path,
                        }
                        for f in internal_frames
                    ],
                }
            except Exception as e:
                logger.error("Failed to parse stack trace", error=str(e))
                return {"success": False, "error": str(e)}

        @self.app.post("/tools/explore-codebase")
        async def explore_codebase(
            repo_path: str,
            query: str,
            max_files: int = 10,
        ) -> dict[str, Any]:
            """Explore codebase with a natural language query.

            Uses pattern matching to find relevant files and code.
            """
            try:
                path = Path(repo_path)
                if not path.exists():
                    return {"success": False, "error": f"Path not found: {repo_path}"}

                results = {
                    "success": True,
                    "query": query,
                    "matches": [],
                }

                # Search for Java files
                java_files = list(path.rglob("*.java"))[:50]

                # Simple keyword search
                keywords = query.lower().split()
                scored_files = []

                for java_file in java_files:
                    try:
                        content = java_file.read_text().lower()
                        score = sum(1 for kw in keywords if kw in content)
                        if score > 0:
                            scored_files.append((java_file, score, content))
                    except Exception:
                        continue

                # Sort by score and take top matches
                scored_files.sort(key=lambda x: x[1], reverse=True)

                for java_file, score, content in scored_files[:max_files]:
                    rel_path = str(java_file.relative_to(path))
                    # Find relevant lines
                    relevant_lines = []
                    for i, line in enumerate(content.split("\n"), 1):
                        if any(kw in line for kw in keywords):
                            relevant_lines.append({"line": i, "content": line.strip()[:100]})
                            if len(relevant_lines) >= 5:
                                break

                    results["matches"].append({
                        "file": rel_path,
                        "score": score,
                        "relevant_lines": relevant_lines,
                    })

                return results

            except Exception as e:
                logger.error("Failed to explore codebase", error=str(e))
                return {"success": False, "error": str(e)}

        @self.app.get("/tools/list", response_model=ListToolsResponse)
        async def list_tools() -> ListToolsResponse:
            """List available MCP tools."""
            return ListToolsResponse(
                tools=[
                    ToolInfo(
                        name="analyze-incidents",
                        description=(
                            "Analyze recent error incidents from Cloud Logging. "
                            "Returns structured RootCauseAnalysis with precise "
                            "code locations and fix suggestions."
                        ),
                        parameters={
                            "hours": "Hours to look back (1-168, default: 24)",
                            "min_occurrences": "Minimum occurrences for incident (default: 1)",
                            "include_source": "Include source code in analysis (default: true)",
                            "target_repo_path": "Path to target repository for source extraction",
                        },
                    ),
                    ToolInfo(
                        name="get-code-context",
                        description=(
                            "Get source code context for a file including imports, "
                            "method signatures, and dependency information. "
                            "Enables active exploration by external agents."
                        ),
                        parameters={
                            "file_path": "Path to source file (relative to repo root)",
                            "repo_path": "Path to the repository root",
                            "include_imports": "Include import analysis (default: true)",
                            "include_signatures": "Include method signatures (default: true)",
                            "include_dependencies": "Include dependency graph (default: true)",
                            "context_line": "Line number to highlight (optional)",
                            "context_range": "Lines of context around highlighted line (default: 10)",
                        },
                    ),
                    ToolInfo(
                        name="get-dependency-graph",
                        description=(
                            "Get dependency graph for multiple files. "
                            "Analyzes import relationships to understand how changes "
                            "might ripple through the codebase."
                        ),
                        parameters={
                            "file_paths": "List of source file paths",
                            "repo_path": "Path to the repository root",
                            "include_source": "Include source code of dependencies (default: false)",
                            "max_depth": "Maximum dependency depth (1-3, default: 1)",
                        },
                    ),
                    ToolInfo(
                        name="parse-stack-trace",
                        description=(
                            "Parse a Java stack trace and extract structured information. "
                            "Returns exception type, internal frames, and root cause location."
                        ),
                        parameters={
                            "stack_trace": "Raw Java stack trace string",
                        },
                    ),
                    ToolInfo(
                        name="explore-codebase",
                        description=(
                            "Explore codebase with a natural language query. "
                            "Uses keyword matching to find relevant files and code."
                        ),
                        parameters={
                            "repo_path": "Path to the repository root",
                            "query": "Natural language search query",
                            "max_files": "Maximum files to return (default: 10)",
                        },
                    ),
                ]
            )

    def _ensure_initialized(self) -> None:
        """Ensure components are initialized."""
        if not self._initialized:
            self.vertex_client = VertexAIClient(self.settings)
            self.vertex_client.initialize()
            self.log_collector = LogCollector(self.settings)
            self.analyzer = RootCauseAnalyzer(
                self.settings,
                self.vertex_client,
                target_repo_path=self.default_repo_path,
            )
            self._initialized = True
            logger.info("MCP components initialized")

    def _convert_analysis_to_response(self, analysis: Any) -> RootCauseAnalysisResponse:
        """Convert RootCauseAnalysis to response model.

        Args:
            analysis: RootCauseAnalysis dataclass.

        Returns:
            RootCauseAnalysisResponse: Pydantic response model.
        """
        error_location = None
        if analysis.error_location:
            error_location = ErrorLocation(
                file_path=analysis.error_location.file_path,
                line_number=analysis.error_location.line_number,
                class_name=analysis.error_location.class_name,
                method_name=analysis.error_location.method_name,
                code_snippet=analysis.error_location.code_snippet,
            )

        stack_frames = []
        for frame in analysis.stack_frames:
            stack_frames.append(
                StackFrameInfo(
                    class_name=frame.class_name,
                    method_name=frame.method_name,
                    file_name=frame.file_name,
                    line_number=frame.line_number,
                    is_internal=frame.is_internal,
                    source_path=frame.source_path,
                )
            )

        return RootCauseAnalysisResponse(
            summary=analysis.summary,
            root_cause=analysis.root_cause,
            affected_component=analysis.affected_component,
            suggested_fix=analysis.suggested_fix,
            confidence=analysis.confidence,
            related_files=analysis.related_files,
            severity_assessment=analysis.severity_assessment,
            error_location=error_location,
            stack_frames=stack_frames,
            fix_code_sample=analysis.fix_code_sample,
        )

    def get_app(self) -> FastAPI:
        """Get the FastAPI application.

        Returns:
            FastAPI: The FastAPI app instance.
        """
        return self.app


def create_app(default_repo_path: str | None = None) -> FastAPI:
    """Create and configure the MCP server app.

    Args:
        default_repo_path: Default path to target repository.

    Returns:
        FastAPI: Configured FastAPI application.
    """
    server = MCPServer(default_repo_path=default_repo_path)
    return server.get_app()
