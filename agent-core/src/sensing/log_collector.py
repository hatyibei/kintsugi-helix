"""Log collector for Cloud Logging.

Fetches and parses error logs from Google Cloud Logging.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from google.cloud import logging as cloud_logging
from google.cloud.logging_v2 import DESCENDING

from src.utils.config import Settings

logger = structlog.get_logger()


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

    @classmethod
    def from_cloud_entry(cls, entry: Any) -> "LogEntry":
        """Create LogEntry from Cloud Logging entry.

        Args:
            entry: Cloud Logging entry object.

        Returns:
            LogEntry: Parsed log entry.
        """
        payload = entry.payload
        if isinstance(payload, dict):
            message = payload.get("message", str(payload))
            trace = payload.get("stack_trace") or payload.get("exception")
        else:
            message = str(payload)
            trace = None

        return cls(
            timestamp=entry.timestamp,
            severity=entry.severity,
            message=message,
            trace=trace,
            resource=dict(entry.resource.labels) if entry.resource else {},
            labels=dict(entry.labels) if entry.labels else {},
            insert_id=entry.insert_id,
        )


class LogCollector:
    """Collects and filters logs from Cloud Logging."""

    def __init__(self, settings: Settings) -> None:
        """Initialize the log collector.

        Args:
            settings: Application settings.
        """
        self.settings = settings
        self.client = cloud_logging.Client(project=settings.google_cloud_project)
        logger.info(
            "LogCollector initialized",
            project=settings.google_cloud_project,
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
        for entry in self.client.list_entries(
            filter_=filter_str,
            order_by=DESCENDING,
            max_results=max_results,
        ):
            entries.append(LogEntry.from_cloud_entry(entry))

        logger.info("Logs collected", count=len(entries))
        return entries

    def get_error_groups(
        self,
        entries: list[LogEntry],
    ) -> dict[str, list[LogEntry]]:
        """Group similar errors together.

        Args:
            entries: List of log entries to group.

        Returns:
            dict: Mapping of error signature to list of entries.
        """
        groups: dict[str, list[LogEntry]] = {}

        for entry in entries:
            # Create a signature from the first line of the message
            first_line = entry.message.split("\n")[0][:100]
            signature = f"{entry.severity}:{first_line}"

            if signature not in groups:
                groups[signature] = []
            groups[signature].append(entry)

        logger.info("Errors grouped", group_count=len(groups))
        return groups

    def get_recent_incidents(
        self,
        min_occurrences: int = 3,
        hours: int | None = None,
    ) -> list[dict[str, Any]]:
        """Get recent error incidents (grouped errors exceeding threshold).

        Args:
            min_occurrences: Minimum occurrences to be considered an incident.
            hours: Hours to look back.

        Returns:
            list[dict]: List of incident summaries.
        """
        entries = self.collect_errors(hours=hours)
        groups = self.get_error_groups(entries)

        incidents = []
        for signature, group_entries in groups.items():
            if len(group_entries) >= min_occurrences:
                # Get the most recent entry as representative
                latest = max(group_entries, key=lambda e: e.timestamp)
                incidents.append({
                    "signature": signature,
                    "count": len(group_entries),
                    "first_seen": min(e.timestamp for e in group_entries),
                    "last_seen": latest.timestamp,
                    "message": latest.message,
                    "trace": latest.trace,
                    "resource": latest.resource,
                    "sample_entries": group_entries[:5],
                })

        # Sort by occurrence count
        incidents.sort(key=lambda x: x["count"], reverse=True)

        logger.info("Incidents identified", count=len(incidents))
        return incidents
