"""MCP Server implementation for Kintsugi-Helix.

Exposes agent capabilities via the Model Context Protocol.
"""

from typing import Any

import structlog
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src.sensing.log_collector import LogCollector
from src.sensing.root_cause_analyzer import RootCauseAnalyzer
from src.utils.config import Settings, get_settings
from src.utils.vertex_client import VertexAIClient

logger = structlog.get_logger()


# Request/Response models
class AnalyzeIncidentRequest(BaseModel):
    """Request to analyze an incident."""

    incident_id: str | None = None
    hours: int = 24
    min_occurrences: int = 3


class AnalyzeIncidentResponse(BaseModel):
    """Response from incident analysis."""

    success: bool
    incidents: list[dict[str, Any]]
    analyses: list[dict[str, Any]]


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    version: str


class MCPServer:
    """MCP Server exposing Kintsugi-Helix capabilities."""

    def __init__(self, settings: Settings | None = None) -> None:
        """Initialize the MCP server.

        Args:
            settings: Optional settings. Uses default if not provided.
        """
        self.settings = settings or get_settings()
        self.app = FastAPI(
            title="Kintsugi-Helix MCP Server",
            description="Model Context Protocol server for autonomous maintenance",
            version="0.1.0",
        )
        self._setup_routes()
        self._initialized = False

        logger.info("MCPServer created")

    def _setup_routes(self) -> None:
        """Set up FastAPI routes."""

        @self.app.get("/health", response_model=HealthResponse)
        async def health_check() -> HealthResponse:
            """Health check endpoint."""
            return HealthResponse(status="healthy", version="0.1.0")

        @self.app.post("/tools/analyze-incidents", response_model=AnalyzeIncidentResponse)
        async def analyze_incidents(
            request: AnalyzeIncidentRequest,
        ) -> AnalyzeIncidentResponse:
            """Analyze recent incidents from Cloud Logging."""
            try:
                self._ensure_initialized()

                # Get incidents
                incidents = self.log_collector.get_recent_incidents(
                    hours=request.hours,
                    min_occurrences=request.min_occurrences,
                )

                # Analyze each incident
                analyses = []
                for incident in incidents[:5]:  # Limit to 5 incidents
                    analysis = await self.analyzer.analyze_incident(incident)
                    analyses.append({
                        "summary": analysis.summary,
                        "root_cause": analysis.root_cause,
                        "affected_component": analysis.affected_component,
                        "suggested_fix": analysis.suggested_fix,
                        "confidence": analysis.confidence,
                        "severity": analysis.severity_assessment,
                    })

                return AnalyzeIncidentResponse(
                    success=True,
                    incidents=[
                        {
                            "signature": i["signature"],
                            "count": i["count"],
                            "message": i["message"][:500],
                        }
                        for i in incidents
                    ],
                    analyses=analyses,
                )

            except Exception as e:
                logger.error("Failed to analyze incidents", error=str(e))
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.get("/tools/list")
        async def list_tools() -> dict[str, Any]:
            """List available MCP tools."""
            return {
                "tools": [
                    {
                        "name": "analyze-incidents",
                        "description": "Analyze recent error incidents from Cloud Logging",
                        "parameters": {
                            "hours": "Hours to look back (default: 24)",
                            "min_occurrences": "Minimum occurrences for incident (default: 3)",
                        },
                    },
                    {
                        "name": "get-recommendations",
                        "description": "Get OpenRewrite recipe recommendations for the project",
                        "parameters": {},
                    },
                ]
            }

    def _ensure_initialized(self) -> None:
        """Ensure components are initialized."""
        if not self._initialized:
            self.vertex_client = VertexAIClient(self.settings)
            self.vertex_client.initialize()
            self.log_collector = LogCollector(self.settings)
            self.analyzer = RootCauseAnalyzer(self.settings, self.vertex_client)
            self._initialized = True
            logger.info("MCP components initialized")

    def get_app(self) -> FastAPI:
        """Get the FastAPI application.

        Returns:
            FastAPI: The FastAPI app instance.
        """
        return self.app


def create_app() -> FastAPI:
    """Create and configure the MCP server app.

    Returns:
        FastAPI: Configured FastAPI application.
    """
    server = MCPServer()
    return server.get_app()
