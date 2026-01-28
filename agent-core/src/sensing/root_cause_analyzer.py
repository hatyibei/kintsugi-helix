"""Root cause analyzer using Gemini.

Analyzes error logs and stack traces to identify the root cause.
"""

from dataclasses import dataclass
from typing import Any

import structlog

from src.sensing.log_collector import LogEntry
from src.utils.config import Settings
from src.utils.vertex_client import VertexAIClient

logger = structlog.get_logger()


@dataclass
class RootCauseAnalysis:
    """Result of root cause analysis."""

    summary: str
    root_cause: str
    affected_component: str
    suggested_fix: str
    confidence: float
    related_files: list[str]
    severity_assessment: str


class RootCauseAnalyzer:
    """Analyzes errors to determine root cause using Gemini."""

    def __init__(self, settings: Settings, vertex_client: VertexAIClient) -> None:
        """Initialize the analyzer.

        Args:
            settings: Application settings.
            vertex_client: Vertex AI client instance.
        """
        self.settings = settings
        self.vertex_client = vertex_client
        logger.info("RootCauseAnalyzer initialized")

    async def analyze_incident(
        self,
        incident: dict[str, Any],
        source_files: dict[str, str] | None = None,
    ) -> RootCauseAnalysis:
        """Analyze an incident to determine root cause.

        Args:
            incident: Incident data from LogCollector.
            source_files: Optional mapping of file paths to contents.

        Returns:
            RootCauseAnalysis: Analysis results.
        """
        logger.info(
            "Analyzing incident",
            signature=incident.get("signature"),
            count=incident.get("count"),
        )

        # Build context from incident
        context_parts = [
            f"Error occurred {incident['count']} times",
            f"First seen: {incident['first_seen']}",
            f"Last seen: {incident['last_seen']}",
            f"\nError message:\n{incident['message']}",
        ]

        if incident.get("trace"):
            context_parts.append(f"\nStack trace:\n{incident['trace']}")

        if incident.get("resource"):
            context_parts.append(f"\nResource: {incident['resource']}")

        # Add source file context if available
        if source_files:
            context_parts.append("\n\nRelated source files:")
            for path, content in source_files.items():
                context_parts.append(f"\n--- {path} ---\n{content[:2000]}")

        context = "\n".join(context_parts)

        # Define response schema
        schema = {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Brief one-line summary of the issue",
                },
                "root_cause": {
                    "type": "string",
                    "description": "Detailed explanation of the root cause",
                },
                "affected_component": {
                    "type": "string",
                    "description": "The component/class/method affected",
                },
                "suggested_fix": {
                    "type": "string",
                    "description": "Suggested code fix or approach",
                },
                "confidence": {
                    "type": "number",
                    "description": "Confidence level from 0.0 to 1.0",
                },
                "related_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of likely affected file paths",
                },
                "severity_assessment": {
                    "type": "string",
                    "enum": ["critical", "high", "medium", "low"],
                    "description": "Severity assessment",
                },
            },
            "required": [
                "summary",
                "root_cause",
                "affected_component",
                "suggested_fix",
                "confidence",
                "related_files",
                "severity_assessment",
            ],
        }

        prompt = f"""You are an expert software engineer performing root cause analysis.
Analyze the following error incident and determine the root cause.

{context}

Provide a structured analysis including:
1. A brief summary of the issue
2. The root cause explanation
3. The affected component
4. A suggested fix
5. Your confidence level (0.0-1.0)
6. Related file paths that may need changes
7. Severity assessment"""

        result = await self.vertex_client.generate_structured(
            prompt=prompt,
            response_schema=schema,
            temperature=0.2,
        )

        analysis = RootCauseAnalysis(
            summary=result["summary"],
            root_cause=result["root_cause"],
            affected_component=result["affected_component"],
            suggested_fix=result["suggested_fix"],
            confidence=result["confidence"],
            related_files=result["related_files"],
            severity_assessment=result["severity_assessment"],
        )

        logger.info(
            "Analysis complete",
            summary=analysis.summary,
            confidence=analysis.confidence,
            severity=analysis.severity_assessment,
        )

        return analysis

    async def analyze_log_entry(self, entry: LogEntry) -> RootCauseAnalysis:
        """Analyze a single log entry.

        Args:
            entry: Log entry to analyze.

        Returns:
            RootCauseAnalysis: Analysis results.
        """
        incident = {
            "signature": f"{entry.severity}:{entry.message[:100]}",
            "count": 1,
            "first_seen": entry.timestamp,
            "last_seen": entry.timestamp,
            "message": entry.message,
            "trace": entry.trace,
            "resource": entry.resource,
        }
        return await self.analyze_incident(incident)
