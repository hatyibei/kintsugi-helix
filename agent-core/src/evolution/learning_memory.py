"""Learning Memory for Kintsugi-Helix immune system.

Persists knowledge from successful and failed fix attempts to enable
the agent to learn from past experiences (antifragility).
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

from src.evolution.code_fixer import CodeFix, FixFeedback
from src.sensing.root_cause_analyzer import RootCauseAnalysis

logger = structlog.get_logger()


@dataclass
class LearningEntry:
    """A single learning entry from a fix attempt."""

    timestamp: str
    incident_signature: str
    bug_type: str
    root_cause_summary: str
    affected_component: str

    # What worked
    successful_fix_description: str | None = None
    successful_fix_pattern: str | None = None

    # What didn't work (lessons learned)
    failed_attempts: list[dict] = field(default_factory=list)

    # Meta insights
    key_insight: str | None = None
    prevention_recommendation: str | None = None
    related_patterns: list[str] = field(default_factory=list)

    # Statistics
    attempts_required: int = 1
    total_time_seconds: float = 0.0


@dataclass
class KnowledgeBase:
    """Accumulated knowledge from all fix attempts."""

    version: str = "1.0.0"
    last_updated: str = ""
    total_fixes: int = 0
    total_learnings: int = 0

    # Indexed knowledge
    entries: list[LearningEntry] = field(default_factory=list)

    # Pattern summaries (aggregated insights)
    common_bug_patterns: dict[str, dict] = field(default_factory=dict)
    effective_fix_strategies: dict[str, list[str]] = field(default_factory=dict)
    anti_patterns: list[dict] = field(default_factory=list)

    # Prompt tips learned from failures
    prompt_tips: list[str] = field(default_factory=list)


class LearningMemory:
    """Manages the agent's learning memory and knowledge persistence.

    Implements the "immune system" that learns from past experiences:
    - Records successful fixes and their patterns
    - Records failed attempts and why they failed
    - Extracts generalizable insights
    - Persists knowledge to KNOWLEDGE_BASE.json
    """

    KNOWLEDGE_FILE = "KNOWLEDGE_BASE.json"
    PROMPT_TIPS_FILE = "PROMPT_TIPS.md"

    def __init__(
        self,
        project_path: Path,
        vertex_client: Any | None = None,
    ) -> None:
        """Initialize the learning memory.

        Args:
            project_path: Path to the target project.
            vertex_client: Optional Vertex AI client for insight generation.
        """
        self.project_path = project_path
        self.vertex_client = vertex_client
        self.knowledge_file = project_path / self.KNOWLEDGE_FILE
        self.prompt_tips_file = project_path / self.PROMPT_TIPS_FILE

        # Load existing knowledge
        self.knowledge = self._load_knowledge()

        logger.info(
            "LearningMemory initialized",
            existing_entries=len(self.knowledge.entries),
            path=str(self.knowledge_file),
        )

    def _load_knowledge(self) -> KnowledgeBase:
        """Load existing knowledge from file.

        Returns:
            KnowledgeBase: Loaded or new knowledge base.
        """
        if self.knowledge_file.exists():
            try:
                data = json.loads(self.knowledge_file.read_text())
                entries = [LearningEntry(**e) for e in data.get("entries", [])]
                return KnowledgeBase(
                    version=data.get("version", "1.0.0"),
                    last_updated=data.get("last_updated", ""),
                    total_fixes=data.get("total_fixes", 0),
                    total_learnings=data.get("total_learnings", 0),
                    entries=entries,
                    common_bug_patterns=data.get("common_bug_patterns", {}),
                    effective_fix_strategies=data.get("effective_fix_strategies", {}),
                    anti_patterns=data.get("anti_patterns", []),
                    prompt_tips=data.get("prompt_tips", []),
                )
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning("Failed to load knowledge base, starting fresh", error=str(e))

        return KnowledgeBase()

    def record_successful_fix(
        self,
        analysis: RootCauseAnalysis,
        fix: CodeFix,
        incident_signature: str,
        start_time: datetime,
    ) -> LearningEntry:
        """Record a successful fix for learning.

        Args:
            analysis: The root cause analysis.
            fix: The successful fix.
            incident_signature: Unique incident identifier.
            start_time: When the fix attempt started.

        Returns:
            LearningEntry: The created learning entry.
        """
        elapsed = (datetime.now() - start_time).total_seconds()

        # Extract bug type from analysis
        bug_type = self._classify_bug_type(analysis)

        # Create learning entry
        entry = LearningEntry(
            timestamp=datetime.now().isoformat(),
            incident_signature=incident_signature,
            bug_type=bug_type,
            root_cause_summary=analysis.summary,
            affected_component=analysis.affected_component,
            successful_fix_description=fix.description,
            successful_fix_pattern=self._extract_fix_pattern(fix),
            failed_attempts=[
                {
                    "attempt": i + 1,
                    "error_type": fb.error_type,
                    "error_summary": fb.error_message[:200] if fb.error_message else None,
                }
                for i, fb in enumerate(fix.feedback_history)
            ],
            attempts_required=fix.attempt,
            total_time_seconds=elapsed,
        )

        # Update knowledge base
        self.knowledge.entries.append(entry)
        self.knowledge.total_fixes += 1
        self.knowledge.total_learnings += 1
        self.knowledge.last_updated = datetime.now().isoformat()

        # Update pattern statistics
        self._update_patterns(entry, bug_type)

        logger.info(
            "Successful fix recorded",
            bug_type=bug_type,
            attempts=fix.attempt,
            elapsed_seconds=elapsed,
        )

        return entry

    def record_failed_fix(
        self,
        analysis: RootCauseAnalysis,
        feedback_history: list[FixFeedback],
        incident_signature: str,
        reason: str,
    ) -> None:
        """Record a failed fix attempt for learning.

        Args:
            analysis: The root cause analysis.
            feedback_history: History of failed attempts.
            incident_signature: Unique incident identifier.
            reason: Why the fix ultimately failed.
        """
        bug_type = self._classify_bug_type(analysis)

        # Record as anti-pattern
        anti_pattern = {
            "timestamp": datetime.now().isoformat(),
            "bug_type": bug_type,
            "incident_signature": incident_signature,
            "root_cause": analysis.summary,
            "failure_reason": reason,
            "attempts": [
                {
                    "error_type": fb.error_type,
                    "error_message": fb.error_message[:300] if fb.error_message else None,
                }
                for fb in feedback_history
            ],
        }

        self.knowledge.anti_patterns.append(anti_pattern)
        self.knowledge.total_learnings += 1
        self.knowledge.last_updated = datetime.now().isoformat()

        logger.info(
            "Failed fix recorded as anti-pattern",
            bug_type=bug_type,
            attempts=len(feedback_history),
        )

    def _classify_bug_type(self, analysis: RootCauseAnalysis) -> str:
        """Classify the bug type from analysis.

        Args:
            analysis: Root cause analysis.

        Returns:
            str: Bug type classification.
        """
        summary = f"{analysis.summary} {analysis.root_cause}".lower()

        if "nullpointer" in summary or "null" in summary and "exception" in summary:
            return "NullPointerException"
        elif "sql" in summary and ("injection" in summary or "security" in summary):
            return "SQLInjection"
        elif "n+1" in summary or "lazy" in summary and "fetch" in summary:
            return "N+1Query"
        elif "concurrent" in summary or "thread" in summary:
            return "ConcurrencyIssue"
        elif "memory" in summary or "leak" in summary:
            return "MemoryLeak"
        elif "timeout" in summary or "performance" in summary:
            return "PerformanceIssue"
        elif "auth" in summary or "permission" in summary:
            return "AuthorizationIssue"
        else:
            return "Other"

    def _extract_fix_pattern(self, fix: CodeFix) -> str:
        """Extract a generalizable pattern from the fix.

        Args:
            fix: The successful fix.

        Returns:
            str: Extracted pattern description.
        """
        # Simple heuristic based on lines changed
        if fix.lines_changed <= 3:
            return "single_line_fix"
        elif fix.lines_changed <= 10:
            return "localized_fix"
        else:
            return "structural_fix"

    def _update_patterns(self, entry: LearningEntry, bug_type: str) -> None:
        """Update pattern statistics with new entry.

        Args:
            entry: The learning entry.
            bug_type: Bug type classification.
        """
        # Update common bug patterns
        if bug_type not in self.knowledge.common_bug_patterns:
            self.knowledge.common_bug_patterns[bug_type] = {
                "count": 0,
                "avg_attempts": 0.0,
                "components": [],
            }

        pattern = self.knowledge.common_bug_patterns[bug_type]
        old_count = pattern["count"]
        pattern["count"] += 1
        pattern["avg_attempts"] = (
            (pattern["avg_attempts"] * old_count + entry.attempts_required) / pattern["count"]
        )
        if entry.affected_component not in pattern["components"]:
            pattern["components"].append(entry.affected_component)

        # Update effective fix strategies
        if bug_type not in self.knowledge.effective_fix_strategies:
            self.knowledge.effective_fix_strategies[bug_type] = []

        if entry.successful_fix_description:
            strategies = self.knowledge.effective_fix_strategies[bug_type]
            if len(strategies) < 5:  # Keep top 5 strategies
                strategies.append(entry.successful_fix_description[:200])

    async def generate_insights(self) -> dict[str, Any]:
        """Generate insights from accumulated knowledge using Gemini.

        Returns:
            dict: Generated insights.
        """
        if not self.vertex_client or len(self.knowledge.entries) < 3:
            return {}

        # Build context from recent entries
        recent_entries = self.knowledge.entries[-10:]
        entries_summary = "\n".join([
            f"- {e.bug_type}: {e.root_cause_summary} (attempts: {e.attempts_required})"
            for e in recent_entries
        ])

        prompt = f"""Analyze these recent bug fixes and extract generalizable insights:

## Recent Bug Fixes
{entries_summary}

## Bug Pattern Statistics
{json.dumps(self.knowledge.common_bug_patterns, indent=2)}

## Anti-patterns (Failed Fixes)
{json.dumps(self.knowledge.anti_patterns[-5:], indent=2) if self.knowledge.anti_patterns else "None"}

Generate:
1. Key insights about recurring patterns
2. Prompt tips for better fix generation
3. Prevention recommendations

Be concise and actionable."""

        schema = {
            "type": "object",
            "properties": {
                "key_insights": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "prompt_tips": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "prevention_recommendations": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        }

        result = await self.vertex_client.generate_structured(
            prompt=prompt,
            response_schema=schema,
            temperature=0.3,
        )

        # Update prompt tips
        new_tips = result.get("prompt_tips", [])
        for tip in new_tips:
            if tip not in self.knowledge.prompt_tips:
                self.knowledge.prompt_tips.append(tip)

        return result

    def get_relevant_knowledge(self, analysis: RootCauseAnalysis) -> dict[str, Any]:
        """Get relevant knowledge for a new bug fix.

        Args:
            analysis: The new bug's root cause analysis.

        Returns:
            dict: Relevant past knowledge.
        """
        bug_type = self._classify_bug_type(analysis)

        relevant = {
            "bug_type": bug_type,
            "past_fixes": [],
            "effective_strategies": [],
            "prompt_tips": [],
            "warnings": [],
        }

        # Find similar past fixes
        for entry in self.knowledge.entries:
            if entry.bug_type == bug_type:
                relevant["past_fixes"].append({
                    "component": entry.affected_component,
                    "fix": entry.successful_fix_description,
                    "attempts": entry.attempts_required,
                })

        # Get effective strategies
        if bug_type in self.knowledge.effective_fix_strategies:
            relevant["effective_strategies"] = self.knowledge.effective_fix_strategies[bug_type]

        # Get relevant prompt tips
        relevant["prompt_tips"] = self.knowledge.prompt_tips[-5:]

        # Check for anti-patterns (warnings)
        for ap in self.knowledge.anti_patterns:
            if ap.get("bug_type") == bug_type:
                relevant["warnings"].append(ap.get("failure_reason", ""))

        return relevant

    def save(self) -> None:
        """Save knowledge to file."""
        data = {
            "version": self.knowledge.version,
            "last_updated": self.knowledge.last_updated,
            "total_fixes": self.knowledge.total_fixes,
            "total_learnings": self.knowledge.total_learnings,
            "entries": [asdict(e) for e in self.knowledge.entries],
            "common_bug_patterns": self.knowledge.common_bug_patterns,
            "effective_fix_strategies": self.knowledge.effective_fix_strategies,
            "anti_patterns": self.knowledge.anti_patterns,
            "prompt_tips": self.knowledge.prompt_tips,
        }

        self.knowledge_file.write_text(json.dumps(data, indent=2, ensure_ascii=False))

        logger.info(
            "Knowledge base saved",
            entries=len(self.knowledge.entries),
            path=str(self.knowledge_file),
        )

    def save_prompt_tips(self) -> None:
        """Save prompt tips as markdown for human readability."""
        if not self.knowledge.prompt_tips:
            return

        content = """# Kintsugi-Helix Prompt Tips

This file contains learned tips for better bug fix generation.
Auto-generated from past fix experiences.

## Tips

"""
        for i, tip in enumerate(self.knowledge.prompt_tips, 1):
            content += f"{i}. {tip}\n"

        content += f"""
## Statistics

- Total fixes: {self.knowledge.total_fixes}
- Total learnings: {self.knowledge.total_learnings}
- Last updated: {self.knowledge.last_updated}

## Common Bug Patterns

"""
        for bug_type, stats in self.knowledge.common_bug_patterns.items():
            content += f"### {bug_type}\n"
            content += f"- Count: {stats['count']}\n"
            content += f"- Avg attempts: {stats['avg_attempts']:.1f}\n"
            content += f"- Components: {', '.join(stats['components'][:5])}\n\n"

        self.prompt_tips_file.write_text(content)

        logger.info("Prompt tips saved", path=str(self.prompt_tips_file))

    def get_summary(self) -> dict[str, Any]:
        """Get a summary of the knowledge base.

        Returns:
            dict: Summary statistics.
        """
        return {
            "total_fixes": self.knowledge.total_fixes,
            "total_learnings": self.knowledge.total_learnings,
            "entries_count": len(self.knowledge.entries),
            "bug_types_seen": list(self.knowledge.common_bug_patterns.keys()),
            "anti_patterns_count": len(self.knowledge.anti_patterns),
            "prompt_tips_count": len(self.knowledge.prompt_tips),
            "last_updated": self.knowledge.last_updated,
        }
