"""Log collector for Cloud Logging.

Fetches and parses error logs from Google Cloud Logging.
Provides precise incident grouping and Cloud Run metadata extraction.
"""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from google.cloud import logging as cloud_logging
from google.cloud.logging_v2 import DESCENDING

from src.utils.config import Settings

logger = structlog.get_logger()


@dataclass
class CloudRunContext:
    """Cloud Run deployment context extracted from logs."""

    service_name: str
    revision_name: str
    location: str
    configuration_name: str
    project_id: str

    @classmethod
    def from_resource(cls, resource: dict[str, Any], project_id: str) -> "CloudRunContext":
        """Create CloudRunContext from resource labels.

        Args:
            resource: Resource labels from log entry.
            project_id: GCP project ID.

        Returns:
            CloudRunContext: Extracted context.
        """
        return cls(
            service_name=resource.get("service_name", "unknown"),
            revision_name=resource.get("revision_name", "unknown"),
            location=resource.get("location", "unknown"),
            configuration_name=resource.get("configuration_name", "unknown"),
            project_id=project_id,
        )

    def to_dict(self) -> dict[str, str]:
        """Convert to dictionary."""
        return {
            "service_name": self.service_name,
            "revision_name": self.revision_name,
            "location": self.location,
            "configuration_name": self.configuration_name,
            "project_id": self.project_id,
        }


@dataclass
class LogEntry:
    """Represents a parsed log entry."""

    timestamp: datetime
    severity: str
    message: str
    trace: str | None
    resource: dict[str, Any]
    labels: dict[str, str]
    insert_id: str
    # Enhanced fields
    cloud_run_context: CloudRunContext | None = None
    trace_id: str | None = None
    span_id: str | None = None
    http_request: dict[str, Any] | None = None

    @classmethod
    def from_cloud_entry(cls, entry: Any, project_id: str) -> "LogEntry":
        """Create LogEntry from Cloud Logging entry.

        Args:
            entry: Cloud Logging entry object.
            project_id: GCP project ID.

        Returns:
            LogEntry: Parsed log entry.
        """
        payload = entry.payload
        if isinstance(payload, dict):
            message = payload.get("message", str(payload))
            trace = payload.get("stack_trace") or payload.get("exception")
            # Also check for nested exception info
            if not trace and "error" in payload:
                error_info = payload["error"]
                if isinstance(error_info, dict):
                    trace = error_info.get("stack_trace") or error_info.get("exception")
        else:
            message = str(payload)
            trace = None

        resource_labels = dict(entry.resource.labels) if entry.resource else {}
        labels = dict(entry.labels) if entry.labels else {}

        # Extract Cloud Run context
        cloud_run_context = None
        if entry.resource and entry.resource.type in ("cloud_run_revision", "cloud_run_job"):
            cloud_run_context = CloudRunContext.from_resource(resource_labels, project_id)

        # Extract trace context
        trace_id = None
        span_id = None
        if hasattr(entry, "trace") and entry.trace:
            # Format: projects/PROJECT_ID/traces/TRACE_ID
            trace_match = re.search(r"traces/([a-f0-9]+)", entry.trace)
            if trace_match:
                trace_id = trace_match.group(1)
        if hasattr(entry, "span_id"):
            span_id = entry.span_id

        # Extract HTTP request info
        http_request = None
        if hasattr(entry, "http_request") and entry.http_request:
            http_request = {
                "method": getattr(entry.http_request, "request_method", None),
                "url": getattr(entry.http_request, "request_url", None),
                "status": getattr(entry.http_request, "status", None),
                "latency": getattr(entry.http_request, "latency", None),
                "user_agent": getattr(entry.http_request, "user_agent", None),
            }

        return cls(
            timestamp=entry.timestamp,
            severity=entry.severity,
            message=message,
            trace=trace,
            resource=resource_labels,
            labels=labels,
            insert_id=entry.insert_id,
            cloud_run_context=cloud_run_context,
            trace_id=trace_id,
            span_id=span_id,
            http_request=http_request,
        )


class StackTraceNormalizer:
    """Normalizes stack traces for consistent signature generation."""

    # Pattern for Java stack trace lines
    JAVA_FRAME_PATTERN = re.compile(
        r"at\s+([\w.$]+)\.([\w$<>]+)\(([^)]+)\)"
    )

    # Pattern to extract exception type and message
    EXCEPTION_PATTERN = re.compile(
        r"^([\w.]+(?:Exception|Error|Throwable))(?:\s*:\s*(.*))?$",
        re.MULTILINE,
    )

    # Patterns for line numbers (to be removed for normalization)
    LINE_NUMBER_PATTERN = re.compile(r":(\d+)\)")

    # Internal package patterns
    INTERNAL_PACKAGES = ("com.kintsugi.demo",)

    @classmethod
    def normalize_stack_trace(cls, trace: str) -> str:
        """Normalize a stack trace for consistent comparison.

        Removes line numbers and keeps only the class/method chain.

        Args:
            trace: Raw stack trace.

        Returns:
            str: Normalized stack trace.
        """
        if not trace:
            return ""

        # Remove line numbers
        normalized = cls.LINE_NUMBER_PATTERN.sub(")", trace)

        # Remove whitespace variations
        lines = [line.strip() for line in normalized.split("\n") if line.strip()]

        return "\n".join(lines)

    @classmethod
    def extract_exception_chain(cls, trace: str) -> list[tuple[str, str | None]]:
        """Extract the chain of exceptions from a stack trace.

        Handles "Caused by:" chains.

        Args:
            trace: Raw stack trace.

        Returns:
            list: List of (exception_type, message) tuples.
        """
        if not trace:
            return []

        exceptions = []
        for match in cls.EXCEPTION_PATTERN.finditer(trace):
            exc_type = match.group(1)
            exc_message = match.group(2).strip() if match.group(2) else None
            exceptions.append((exc_type, exc_message))

        return exceptions

    @classmethod
    def extract_internal_methods(cls, trace: str) -> list[str]:
        """Extract internal (com.kintsugi.demo) method calls.

        Args:
            trace: Raw stack trace.

        Returns:
            list: List of "class.method" strings.
        """
        if not trace:
            return []

        methods = []
        for match in cls.JAVA_FRAME_PATTERN.finditer(trace):
            full_class = match.group(1)
            method = match.group(2)

            # Check if it's an internal class
            if any(full_class.startswith(pkg) for pkg in cls.INTERNAL_PACKAGES):
                methods.append(f"{full_class}.{method}")

        return methods

    @classmethod
    def generate_signature(cls, trace: str, message: str = "") -> str:
        """Generate a stable signature for deduplication.

        The signature is based on:
        1. Exception type
        2. Internal method chain (without line numbers)
        3. Message pattern (with variable parts removed)

        Args:
            trace: Raw stack trace.
            message: Error message.

        Returns:
            str: Stable signature hash.
        """
        parts = []

        # Extract exception type
        exceptions = cls.extract_exception_chain(trace)
        if exceptions:
            parts.append(exceptions[0][0])  # Primary exception type

        # Extract internal method chain
        methods = cls.extract_internal_methods(trace)
        if methods:
            # Use first 5 internal methods for signature
            parts.extend(methods[:5])

        # If no stack trace, use normalized message
        if not parts:
            # Remove variable parts from message (numbers, UUIDs, timestamps)
            normalized_msg = re.sub(r"\b\d+\b", "N", message)
            normalized_msg = re.sub(
                r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
                "UUID",
                normalized_msg,
                flags=re.IGNORECASE,
            )
            normalized_msg = re.sub(
                r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}",
                "TIMESTAMP",
                normalized_msg,
            )
            parts.append(normalized_msg[:200])

        signature_str = "|".join(parts)
        return hashlib.md5(signature_str.encode()).hexdigest()[:16]

    @classmethod
    def are_same_error(cls, trace1: str, trace2: str) -> bool:
        """Check if two stack traces represent the same error.

        Args:
            trace1: First stack trace.
            trace2: Second stack trace.

        Returns:
            bool: True if they represent the same error.
        """
        sig1 = cls.generate_signature(trace1)
        sig2 = cls.generate_signature(trace2)
        return sig1 == sig2


@dataclass
class IncidentSummary:
    """Summary of a grouped incident."""

    signature: str
    count: int
    first_seen: datetime
    last_seen: datetime
    message: str
    trace: str | None
    resource: dict[str, Any]
    sample_entries: list[LogEntry] = field(default_factory=list)
    # Enhanced fields
    exception_type: str | None = None
    exception_message: str | None = None
    affected_methods: list[str] = field(default_factory=list)
    cloud_run_contexts: list[CloudRunContext] = field(default_factory=list)
    http_endpoints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "signature": self.signature,
            "count": self.count,
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "message": self.message,
            "trace": self.trace,
            "resource": self.resource,
            "exception_type": self.exception_type,
            "exception_message": self.exception_message,
            "affected_methods": self.affected_methods,
            "cloud_run_services": list(set(
                ctx.service_name for ctx in self.cloud_run_contexts
                if ctx.service_name != "unknown"
            )),
            "cloud_run_revisions": list(set(
                ctx.revision_name for ctx in self.cloud_run_contexts
                if ctx.revision_name != "unknown"
            )),
            "http_endpoints": list(set(self.http_endpoints)),
        }


class LogCollector:
    """Collects and filters logs from Cloud Logging.

    Provides precise incident grouping using stack trace normalization
    and Cloud Run metadata extraction.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialize the log collector.

        Args:
            settings: Application settings.
        """
        self.settings = settings
        self.project_id = settings.google_cloud_project
        self.client = cloud_logging.Client(project=self.project_id)
        self.normalizer = StackTraceNormalizer()
        logger.info(
            "LogCollector initialized",
            project=self.project_id,
        )

    def collect_errors(
        self,
        hours: int | None = None,
        resource_type: str | None = None,
        service_name: str | None = None,
        max_results: int = 100,
    ) -> list[LogEntry]:
        """Collect error logs within the specified time window.

        Args:
            hours: Hours to look back. Uses settings default if not specified.
            resource_type: Filter by resource type (e.g., 'cloud_run_revision').
            service_name: Filter by service name.
            max_results: Maximum number of results to return.

        Returns:
            list[LogEntry]: List of parsed log entries.
        """
        hours = hours or self.settings.log_lookback_hours
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=hours)

        # Build filter
        filter_parts = [
            self.settings.log_filter,
            f'timestamp>="{start_time.isoformat()}"',
            f'timestamp<="{end_time.isoformat()}"',
        ]

        if resource_type:
            filter_parts.append(f'resource.type="{resource_type}"')

        if service_name:
            filter_parts.append(f'resource.labels.service_name="{service_name}"')

        filter_str = " AND ".join(filter_parts)

        logger.info(
            "Collecting logs",
            filter=filter_str,
            max_results=max_results,
        )

        entries = []
        try:
            for entry in self.client.list_entries(
                filter_=filter_str,
                order_by=DESCENDING,
                max_results=max_results,
            ):
                entries.append(LogEntry.from_cloud_entry(entry, self.project_id))
        except Exception as e:
            logger.error("Failed to collect logs", error=str(e))
            raise

        logger.info("Logs collected", count=len(entries))
        return entries

    def collect_cloud_run_errors(
        self,
        service_name: str | None = None,
        hours: int | None = None,
        max_results: int = 100,
    ) -> list[LogEntry]:
        """Collect errors specifically from Cloud Run services.

        Args:
            service_name: Optional specific service name.
            hours: Hours to look back.
            max_results: Maximum results.

        Returns:
            list[LogEntry]: Cloud Run error entries.
        """
        return self.collect_errors(
            hours=hours,
            resource_type="cloud_run_revision",
            service_name=service_name,
            max_results=max_results,
        )

    def get_error_groups(
        self,
        entries: list[LogEntry],
    ) -> dict[str, list[LogEntry]]:
        """Group similar errors together using normalized signatures.

        Args:
            entries: List of log entries to group.

        Returns:
            dict: Mapping of error signature to list of entries.
        """
        groups: dict[str, list[LogEntry]] = {}

        for entry in entries:
            # Generate signature based on stack trace or message
            signature = self.normalizer.generate_signature(
                entry.trace or "",
                entry.message,
            )

            if signature not in groups:
                groups[signature] = []
            groups[signature].append(entry)

        logger.info("Errors grouped", group_count=len(groups))
        return groups

    def get_recent_incidents(
        self,
        min_occurrences: int = 1,
        hours: int | None = None,
        max_incidents: int = 20,
    ) -> list[dict[str, Any]]:
        """Get recent error incidents (grouped errors exceeding threshold).

        Enhanced to include Cloud Run metadata and precise code locations.

        Args:
            min_occurrences: Minimum occurrences to be considered an incident.
            hours: Hours to look back.
            max_incidents: Maximum number of incidents to return.

        Returns:
            list[dict]: List of incident summaries.
        """
        entries = self.collect_errors(hours=hours)
        groups = self.get_error_groups(entries)

        incidents = []
        for signature, group_entries in groups.items():
            if len(group_entries) >= min_occurrences:
                incident = self._create_incident_summary(signature, group_entries)
                incidents.append(incident.to_dict())

        # Sort by occurrence count (descending)
        incidents.sort(key=lambda x: x["count"], reverse=True)

        # Limit results
        incidents = incidents[:max_incidents]

        logger.info("Incidents identified", count=len(incidents))
        return incidents

    def _create_incident_summary(
        self,
        signature: str,
        entries: list[LogEntry],
    ) -> IncidentSummary:
        """Create a detailed incident summary from grouped entries.

        Args:
            signature: Incident signature.
            entries: Grouped log entries.

        Returns:
            IncidentSummary: Detailed incident summary.
        """
        # Get the most recent entry as representative
        latest = max(entries, key=lambda e: e.timestamp)
        earliest = min(entries, key=lambda e: e.timestamp)

        # Extract exception info
        exception_type = None
        exception_message = None
        if latest.trace:
            exceptions = self.normalizer.extract_exception_chain(latest.trace)
            if exceptions:
                exception_type, exception_message = exceptions[0]

        # Extract affected methods
        affected_methods = []
        if latest.trace:
            affected_methods = self.normalizer.extract_internal_methods(latest.trace)

        # Collect Cloud Run contexts
        cloud_run_contexts = [
            e.cloud_run_context for e in entries
            if e.cloud_run_context is not None
        ]

        # Collect HTTP endpoints
        http_endpoints = []
        for entry in entries:
            if entry.http_request and entry.http_request.get("url"):
                http_endpoints.append(entry.http_request["url"])

        return IncidentSummary(
            signature=signature,
            count=len(entries),
            first_seen=earliest.timestamp,
            last_seen=latest.timestamp,
            message=latest.message,
            trace=latest.trace,
            resource=latest.resource,
            sample_entries=entries[:5],
            exception_type=exception_type,
            exception_message=exception_message,
            affected_methods=affected_methods,
            cloud_run_contexts=cloud_run_contexts,
            http_endpoints=http_endpoints,
        )

    def get_incidents_by_service(
        self,
        hours: int | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Group incidents by Cloud Run service.

        Args:
            hours: Hours to look back.

        Returns:
            dict: Mapping of service name to incident list.
        """
        incidents = self.get_recent_incidents(hours=hours, min_occurrences=1)

        by_service: dict[str, list[dict[str, Any]]] = {}
        for incident in incidents:
            services = incident.get("cloud_run_services", ["unknown"])
            for service in services:
                if service not in by_service:
                    by_service[service] = []
                by_service[service].append(incident)

        return by_service

    def get_incident_timeline(
        self,
        signature: str,
        hours: int = 24,
    ) -> list[dict[str, Any]]:
        """Get timeline of occurrences for a specific incident.

        Args:
            signature: Incident signature.
            hours: Hours to look back.

        Returns:
            list: Timeline entries with timestamps and counts.
        """
        entries = self.collect_errors(hours=hours, max_results=500)
        groups = self.get_error_groups(entries)

        if signature not in groups:
            return []

        incident_entries = groups[signature]

        # Group by hour
        hourly_counts: dict[str, int] = {}
        for entry in incident_entries:
            hour_key = entry.timestamp.strftime("%Y-%m-%d %H:00")
            hourly_counts[hour_key] = hourly_counts.get(hour_key, 0) + 1

        # Convert to timeline
        timeline = [
            {"timestamp": ts, "count": count}
            for ts, count in sorted(hourly_counts.items())
        ]

        return timeline

    def search_logs(
        self,
        query: str,
        hours: int | None = None,
        max_results: int = 50,
    ) -> list[LogEntry]:
        """Search logs with a text query.

        Args:
            query: Text to search for in log messages.
            hours: Hours to look back.
            max_results: Maximum results.

        Returns:
            list[LogEntry]: Matching log entries.
        """
        hours = hours or self.settings.log_lookback_hours
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=hours)

        filter_parts = [
            f'timestamp>="{start_time.isoformat()}"',
            f'timestamp<="{end_time.isoformat()}"',
            f'textPayload:"{query}" OR jsonPayload.message:"{query}"',
        ]

        filter_str = " AND ".join(filter_parts)

        logger.info("Searching logs", query=query, filter=filter_str)

        entries = []
        try:
            for entry in self.client.list_entries(
                filter_=filter_str,
                order_by=DESCENDING,
                max_results=max_results,
            ):
                entries.append(LogEntry.from_cloud_entry(entry, self.project_id))
        except Exception as e:
            logger.error("Failed to search logs", error=str(e))

        return entries
