"""Root cause analyzer using Gemini.

Analyzes error logs and stack traces to identify the root cause.
Leverages Gemini 1.5 Pro's long context for comprehensive code understanding.
"""

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

from src.sensing.log_collector import LogEntry
from src.utils.config import Settings
from src.utils.vertex_client import VertexAIClient

logger = structlog.get_logger()


@dataclass
class StackFrame:
    """Represents a single frame in a stack trace."""

    class_name: str
    method_name: str
    file_name: str | None
    line_number: int | None
    is_internal: bool  # True if it's a com.kintsugi.demo class

    @property
    def full_class_name(self) -> str:
        """Get the fully qualified class name."""
        return self.class_name

    @property
    def source_path(self) -> str | None:
        """Convert class name to source file path."""
        if not self.is_internal:
            return None
        # Convert com.kintsugi.demo.service.UserService to
        # src/main/java/com/kintsugi/demo/service/UserService.java
        path_parts = self.class_name.replace(".", "/")
        return f"src/main/java/{path_parts}.java"


@dataclass
class CodeLocation:
    """Precise location of code causing the error."""

    file_path: str
    line_number: int | None
    class_name: str
    method_name: str
    code_snippet: str | None = None


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
    # Enhanced fields
    error_location: CodeLocation | None = None
    stack_frames: list[StackFrame] = field(default_factory=list)
    source_context: dict[str, str] = field(default_factory=dict)
    fix_code_sample: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = {
            "summary": self.summary,
            "root_cause": self.root_cause,
            "affected_component": self.affected_component,
            "suggested_fix": self.suggested_fix,
            "confidence": self.confidence,
            "related_files": self.related_files,
            "severity_assessment": self.severity_assessment,
            "fix_code_sample": self.fix_code_sample,
        }
        if self.error_location:
            result["error_location"] = {
                "file_path": self.error_location.file_path,
                "line_number": self.error_location.line_number,
                "class_name": self.error_location.class_name,
                "method_name": self.error_location.method_name,
                "code_snippet": self.error_location.code_snippet,
            }
        if self.stack_frames:
            result["stack_frames"] = [
                {
                    "class_name": f.class_name,
                    "method_name": f.method_name,
                    "file_name": f.file_name,
                    "line_number": f.line_number,
                    "is_internal": f.is_internal,
                    "source_path": f.source_path,
                }
                for f in self.stack_frames
            ]
        return result


class StackTraceParser:
    """Parses Java stack traces to extract relevant information."""

    # Pattern for Java stack trace lines
    # e.g., "at com.kintsugi.demo.service.UserService.authenticate(UserService.java:45)"
    STACK_FRAME_PATTERN = re.compile(
        r"at\s+(?P<class>[\w.$]+)\.(?P<method>[\w$<>]+)\((?P<file>[\w.]+)?:?(?P<line>\d+)?\)"
    )

    # Pattern for exception type and message
    EXCEPTION_PATTERN = re.compile(
        r"(?P<type>[\w.]+(?:Exception|Error|Throwable))\s*:\s*(?P<message>.*)"
    )

    # Internal package prefix
    INTERNAL_PACKAGES = ("com.kintsugi.demo",)

    @classmethod
    def parse(cls, stack_trace: str) -> list[StackFrame]:
        """Parse a stack trace into individual frames.

        Args:
            stack_trace: The raw stack trace string.

        Returns:
            list[StackFrame]: Parsed stack frames.
        """
        frames = []
        if not stack_trace:
            return frames

        for line in stack_trace.split("\n"):
            line = line.strip()
            match = cls.STACK_FRAME_PATTERN.search(line)
            if match:
                class_name = match.group("class")
                is_internal = any(
                    class_name.startswith(pkg) for pkg in cls.INTERNAL_PACKAGES
                )

                frame = StackFrame(
                    class_name=class_name,
                    method_name=match.group("method"),
                    file_name=match.group("file"),
                    line_number=int(match.group("line")) if match.group("line") else None,
                    is_internal=is_internal,
                )
                frames.append(frame)

        return frames

    @classmethod
    def extract_internal_frames(cls, stack_trace: str) -> list[StackFrame]:
        """Extract only internal (com.kintsugi.demo) frames.

        Args:
            stack_trace: The raw stack trace string.

        Returns:
            list[StackFrame]: Internal stack frames.
        """
        all_frames = cls.parse(stack_trace)
        return [f for f in all_frames if f.is_internal]

    @classmethod
    def extract_exception_info(cls, stack_trace: str) -> tuple[str | None, str | None]:
        """Extract exception type and message from stack trace.

        Args:
            stack_trace: The raw stack trace string.

        Returns:
            tuple: (exception_type, exception_message)
        """
        if not stack_trace:
            return None, None

        first_line = stack_trace.split("\n")[0].strip()
        match = cls.EXCEPTION_PATTERN.match(first_line)
        if match:
            return match.group("type"), match.group("message")
        return None, None

    @classmethod
    def get_root_cause_frame(cls, stack_trace: str) -> StackFrame | None:
        """Get the most likely root cause frame (first internal frame).

        Args:
            stack_trace: The raw stack trace string.

        Returns:
            StackFrame | None: The root cause frame or None.
        """
        internal_frames = cls.extract_internal_frames(stack_trace)
        return internal_frames[0] if internal_frames else None

    @classmethod
    def generate_signature(cls, stack_trace: str) -> str:
        """Generate a normalized signature for deduplication.

        Normalizes the stack trace by removing line numbers and
        creating a hash of the class/method chain.

        Args:
            stack_trace: The raw stack trace string.

        Returns:
            str: A normalized signature hash.
        """
        frames = cls.parse(stack_trace)
        if not frames:
            return hashlib.md5(stack_trace.encode()).hexdigest()[:12]

        # Create signature from class.method chain (internal frames only)
        internal_frames = [f for f in frames if f.is_internal][:5]
        if not internal_frames:
            internal_frames = frames[:5]

        signature_parts = [f"{f.class_name}.{f.method_name}" for f in internal_frames]
        signature_str = "|".join(signature_parts)

        # Add exception type if available
        exc_type, _ = cls.extract_exception_info(stack_trace)
        if exc_type:
            signature_str = f"{exc_type}:{signature_str}"

        return hashlib.md5(signature_str.encode()).hexdigest()[:12]


class SourceCodeExtractor:
    """Extracts source code from repository for analysis context."""

    def __init__(self, repo_path: str | Path) -> None:
        """Initialize the source code extractor.

        Args:
            repo_path: Path to the repository root.
        """
        self.repo_path = Path(repo_path)

    def get_source_for_frame(self, frame: StackFrame) -> str | None:
        """Get source code for a stack frame.

        Args:
            frame: The stack frame to get source for.

        Returns:
            str | None: Source code content or None.
        """
        if not frame.source_path:
            return None

        source_file = self.repo_path / frame.source_path
        if source_file.exists():
            try:
                return source_file.read_text()
            except Exception as e:
                logger.warning("Failed to read source file", path=str(source_file), error=str(e))
        return None

    def get_source_with_context(
        self,
        frame: StackFrame,
        context_lines: int = 10,
    ) -> tuple[str | None, str | None]:
        """Get source code with context around the error line.

        Args:
            frame: The stack frame.
            context_lines: Number of lines of context around error.

        Returns:
            tuple: (full_source, highlighted_snippet)
        """
        source = self.get_source_for_frame(frame)
        if not source or not frame.line_number:
            return source, None

        lines = source.split("\n")
        line_num = frame.line_number - 1  # Convert to 0-indexed

        start = max(0, line_num - context_lines)
        end = min(len(lines), line_num + context_lines + 1)

        snippet_lines = []
        for i in range(start, end):
            marker = ">>>" if i == line_num else "   "
            snippet_lines.append(f"{marker} {i + 1:4d} | {lines[i]}")

        return source, "\n".join(snippet_lines)

    def get_sources_for_frames(
        self,
        frames: list[StackFrame],
        max_files: int = 5,
    ) -> dict[str, str]:
        """Get source code for multiple stack frames.

        Args:
            frames: List of stack frames.
            max_files: Maximum number of files to retrieve.

        Returns:
            dict: Mapping of file paths to source content.
        """
        sources = {}
        seen_files = set()

        for frame in frames:
            if len(sources) >= max_files:
                break
            if not frame.source_path or frame.source_path in seen_files:
                continue

            source = self.get_source_for_frame(frame)
            if source:
                sources[frame.source_path] = source
                seen_files.add(frame.source_path)

        return sources

    def extract_imports(self, source: str) -> list[str]:
        """Extract import statements from Java source.

        Args:
            source: Java source code.

        Returns:
            list[str]: List of imported classes.
        """
        import_pattern = re.compile(r"import\s+([\w.]+);")
        return import_pattern.findall(source)

    def get_class_signature(self, source: str) -> str | None:
        """Extract class/interface signature from Java source.

        Args:
            source: Java source code.

        Returns:
            str | None: Class signature.
        """
        # Match class/interface/enum declarations
        pattern = re.compile(
            r"(?:public\s+)?(?:abstract\s+)?(?:final\s+)?"
            r"(?:class|interface|enum)\s+(\w+)"
            r"(?:\s+extends\s+([\w.]+))?"
            r"(?:\s+implements\s+([\w.,\s]+))?"
        )
        match = pattern.search(source)
        if match:
            class_name = match.group(1)
            extends = f" extends {match.group(2)}" if match.group(2) else ""
            implements = f" implements {match.group(3)}" if match.group(3) else ""
            return f"class {class_name}{extends}{implements}"
        return None

    def get_method_signatures(self, source: str) -> list[str]:
        """Extract method signatures from Java source.

        Args:
            source: Java source code.

        Returns:
            list[str]: List of method signatures.
        """
        # Match method declarations
        pattern = re.compile(
            r"(?:public|private|protected)?\s*"
            r"(?:static\s+)?(?:final\s+)?(?:synchronized\s+)?"
            r"(?:<[\w,\s]+>\s+)?"  # Generics
            r"([\w<>[\],\s]+)\s+"  # Return type
            r"(\w+)\s*\("  # Method name
            r"([^)]*)\)"  # Parameters
        )
        signatures = []
        for match in pattern.finditer(source):
            return_type = match.group(1).strip()
            method_name = match.group(2)
            params = match.group(3).strip()
            signatures.append(f"{return_type} {method_name}({params})")
        return signatures


class RootCauseAnalyzer:
    """Analyzes errors to determine root cause using Gemini.

    Leverages Gemini 1.5 Pro's long context window to include
    full source code of affected classes for precise analysis.
    """

    def __init__(
        self,
        settings: Settings,
        vertex_client: VertexAIClient,
        target_repo_path: str | Path | None = None,
    ) -> None:
        """Initialize the analyzer.

        Args:
            settings: Application settings.
            vertex_client: Vertex AI client instance.
            target_repo_path: Path to target repository for source extraction.
        """
        self.settings = settings
        self.vertex_client = vertex_client
        self.target_repo_path = Path(target_repo_path) if target_repo_path else None
        self.source_extractor = (
            SourceCodeExtractor(self.target_repo_path) if self.target_repo_path else None
        )
        logger.info(
            "RootCauseAnalyzer initialized",
            target_repo=str(self.target_repo_path) if self.target_repo_path else None,
        )

    def set_target_repo(self, repo_path: str | Path) -> None:
        """Set the target repository path for source extraction.

        Args:
            repo_path: Path to the target repository.
        """
        self.target_repo_path = Path(repo_path)
        self.source_extractor = SourceCodeExtractor(self.target_repo_path)
        logger.info("Target repo set", path=str(self.target_repo_path))

    async def analyze_incident(
        self,
        incident: dict[str, Any],
        source_files: dict[str, str] | None = None,
    ) -> RootCauseAnalysis:
        """Analyze an incident to determine root cause.

        Automatically extracts source code from stack trace and includes
        full file contents for Gemini's long context analysis.

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

        # Parse stack trace
        stack_trace = incident.get("trace", "")
        stack_frames = StackTraceParser.parse(stack_trace)
        internal_frames = [f for f in stack_frames if f.is_internal]
        root_frame = StackTraceParser.get_root_cause_frame(stack_trace)
        exc_type, exc_message = StackTraceParser.extract_exception_info(stack_trace)

        # Auto-extract source code if we have a target repo
        extracted_sources: dict[str, str] = {}
        error_snippet: str | None = None

        if self.source_extractor and internal_frames:
            extracted_sources = self.source_extractor.get_sources_for_frames(
                internal_frames,
                max_files=8,  # Leverage long context
            )
            logger.info(
                "Auto-extracted source files",
                count=len(extracted_sources),
                files=list(extracted_sources.keys()),
            )

            # Get highlighted snippet for root cause
            if root_frame:
                _, error_snippet = self.source_extractor.get_source_with_context(
                    root_frame,
                    context_lines=15,
                )

        # Merge provided sources with extracted ones
        all_sources = {**extracted_sources, **(source_files or {})}

        # Extract resource info for Cloud Run context
        resource_info = self._extract_resource_info(incident.get("resource", {}))

        # Build comprehensive context
        context = self._build_analysis_context(
            incident=incident,
            exc_type=exc_type,
            exc_message=exc_message,
            internal_frames=internal_frames,
            root_frame=root_frame,
            error_snippet=error_snippet,
            source_files=all_sources,
            resource_info=resource_info,
        )

        # Get analysis from Gemini
        analysis_result = await self._call_gemini_analysis(context)

        # Build code location
        error_location = None
        if root_frame:
            error_location = CodeLocation(
                file_path=root_frame.source_path or f"{root_frame.class_name}.java",
                line_number=root_frame.line_number,
                class_name=root_frame.class_name,
                method_name=root_frame.method_name,
                code_snippet=error_snippet,
            )

        # Create analysis result
        analysis = RootCauseAnalysis(
            summary=analysis_result["summary"],
            root_cause=analysis_result["root_cause"],
            affected_component=analysis_result["affected_component"],
            suggested_fix=analysis_result["suggested_fix"],
            confidence=analysis_result["confidence"],
            related_files=analysis_result["related_files"],
            severity_assessment=analysis_result["severity_assessment"],
            error_location=error_location,
            stack_frames=internal_frames,
            source_context=all_sources,
            fix_code_sample=analysis_result.get("fix_code_sample"),
        )

        logger.info(
            "Analysis complete",
            summary=analysis.summary,
            confidence=analysis.confidence,
            severity=analysis.severity_assessment,
            error_file=error_location.file_path if error_location else None,
            error_line=error_location.line_number if error_location else None,
        )

        return analysis

    def _extract_resource_info(self, resource: dict[str, Any]) -> dict[str, str]:
        """Extract Cloud Run resource information.

        Args:
            resource: Resource labels from log entry.

        Returns:
            dict: Extracted resource information.
        """
        return {
            "service_name": resource.get("service_name", "unknown"),
            "revision_name": resource.get("revision_name", "unknown"),
            "location": resource.get("location", "unknown"),
            "configuration_name": resource.get("configuration_name", "unknown"),
        }

    def _build_analysis_context(
        self,
        incident: dict[str, Any],
        exc_type: str | None,
        exc_message: str | None,
        internal_frames: list[StackFrame],
        root_frame: StackFrame | None,
        error_snippet: str | None,
        source_files: dict[str, str],
        resource_info: dict[str, str],
    ) -> str:
        """Build comprehensive analysis context for Gemini.

        Args:
            incident: Incident data.
            exc_type: Exception type.
            exc_message: Exception message.
            internal_frames: Internal stack frames.
            root_frame: Root cause frame.
            error_snippet: Code snippet around error.
            source_files: Source file contents.
            resource_info: Cloud Run resource info.

        Returns:
            str: Formatted context string.
        """
        parts = []

        # Incident metadata
        parts.append("=" * 80)
        parts.append("INCIDENT ANALYSIS REQUEST")
        parts.append("=" * 80)
        parts.append(f"\nOccurrences: {incident.get('count', 1)}")
        parts.append(f"First seen: {incident.get('first_seen', 'N/A')}")
        parts.append(f"Last seen: {incident.get('last_seen', 'N/A')}")

        # Cloud Run context
        if any(v != "unknown" for v in resource_info.values()):
            parts.append("\n--- Cloud Run Context ---")
            parts.append(f"Service: {resource_info['service_name']}")
            parts.append(f"Revision: {resource_info['revision_name']}")
            parts.append(f"Location: {resource_info['location']}")

        # Exception information
        parts.append("\n--- Exception Details ---")
        if exc_type:
            parts.append(f"Type: {exc_type}")
        if exc_message:
            parts.append(f"Message: {exc_message}")
        parts.append(f"\nFull message:\n{incident.get('message', 'N/A')}")

        # Stack trace analysis
        if internal_frames:
            parts.append("\n--- Internal Stack Frames (com.kintsugi.demo.*) ---")
            for i, frame in enumerate(internal_frames[:10]):
                location = f":{frame.line_number}" if frame.line_number else ""
                parts.append(f"  [{i}] {frame.class_name}.{frame.method_name}({frame.file_name}{location})")

        # Root cause location
        if root_frame:
            parts.append("\n--- LIKELY ROOT CAUSE LOCATION ---")
            parts.append(f"File: {root_frame.source_path or root_frame.class_name}")
            parts.append(f"Class: {root_frame.class_name}")
            parts.append(f"Method: {root_frame.method_name}")
            if root_frame.line_number:
                parts.append(f"Line: {root_frame.line_number}")

            if error_snippet:
                parts.append("\nCode around error:")
                parts.append("```java")
                parts.append(error_snippet)
                parts.append("```")

        # Full stack trace
        if incident.get("trace"):
            parts.append("\n--- Full Stack Trace ---")
            parts.append("```")
            parts.append(incident["trace"])
            parts.append("```")

        # Source files (leverage Gemini 1.5 Pro's long context)
        if source_files:
            parts.append("\n" + "=" * 80)
            parts.append("SOURCE CODE CONTEXT")
            parts.append("=" * 80)
            parts.append(f"\n{len(source_files)} source file(s) included for analysis:\n")

            for path, content in source_files.items():
                parts.append(f"\n{'─' * 60}")
                parts.append(f"FILE: {path}")
                parts.append(f"{'─' * 60}")
                parts.append("```java")
                # Include full file for Gemini's long context
                parts.append(content)
                parts.append("```")

        return "\n".join(parts)

    async def _call_gemini_analysis(self, context: str) -> dict[str, Any]:
        """Call Gemini for root cause analysis.

        Args:
            context: Analysis context.

        Returns:
            dict: Analysis results.
        """
        schema = {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Brief one-line summary of the issue",
                },
                "root_cause": {
                    "type": "string",
                    "description": "Detailed explanation of the root cause, referencing specific code",
                },
                "affected_component": {
                    "type": "string",
                    "description": "The component/class/method where the fix should be applied",
                },
                "suggested_fix": {
                    "type": "string",
                    "description": "Detailed suggested code fix with explanation",
                },
                "confidence": {
                    "type": "number",
                    "description": "Confidence level from 0.0 to 1.0",
                },
                "related_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of file paths that need changes (in src/main/java/... format)",
                },
                "severity_assessment": {
                    "type": "string",
                    "enum": ["critical", "high", "medium", "low"],
                    "description": "Severity assessment",
                },
                "fix_code_sample": {
                    "type": "string",
                    "description": "Sample code showing the fix (Java code only, no markdown)",
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

        prompt = f"""You are an expert Java/Spring Boot software engineer performing root cause analysis.
Your task is to analyze the error incident and determine the EXACT root cause with code-level precision.

{context}

ANALYSIS INSTRUCTIONS:
1. Identify the exact line and method causing the error
2. Explain WHY the error occurs (not just what the error is)
3. Reference specific code from the provided source files
4. Suggest a concrete fix with actual code changes
5. List ALL files that need to be modified

Focus on:
- Null pointer dereferences
- Missing null checks
- Incorrect state handling
- Concurrency issues
- Type mismatches
- Resource leaks

Provide your analysis in structured JSON format."""

        return await self.vertex_client.generate_structured(
            prompt=prompt,
            response_schema=schema,
            model_name="gemini-1.5-pro",  # Use Pro for complex analysis
            temperature=0.1,
        )

    async def analyze_log_entry(self, entry: LogEntry) -> RootCauseAnalysis:
        """Analyze a single log entry.

        Args:
            entry: Log entry to analyze.

        Returns:
            RootCauseAnalysis: Analysis results.
        """
        incident = {
            "signature": StackTraceParser.generate_signature(entry.trace or entry.message),
            "count": 1,
            "first_seen": entry.timestamp,
            "last_seen": entry.timestamp,
            "message": entry.message,
            "trace": entry.trace,
            "resource": entry.resource,
        }
        return await self.analyze_incident(incident)

    async def analyze_with_dependencies(
        self,
        incident: dict[str, Any],
    ) -> RootCauseAnalysis:
        """Analyze incident and include dependent classes.

        Analyzes import statements and includes related classes
        for more comprehensive context.

        Args:
            incident: Incident data.

        Returns:
            RootCauseAnalysis: Analysis results with dependency context.
        """
        if not self.source_extractor:
            return await self.analyze_incident(incident)

        # First, get the basic frames
        stack_trace = incident.get("trace", "")
        internal_frames = StackTraceParser.extract_internal_frames(stack_trace)

        if not internal_frames:
            return await self.analyze_incident(incident)

        # Get sources for internal frames
        sources = self.source_extractor.get_sources_for_frames(internal_frames, max_files=5)

        # Extract and resolve internal dependencies
        dependency_sources = {}
        for source in sources.values():
            imports = self.source_extractor.extract_imports(source)
            for imp in imports:
                if imp.startswith("com.kintsugi.demo"):
                    dep_path = f"src/main/java/{imp.replace('.', '/')}.java"
                    if dep_path not in sources and dep_path not in dependency_sources:
                        dep_file = self.target_repo_path / dep_path
                        if dep_file.exists():
                            try:
                                dependency_sources[dep_path] = dep_file.read_text()
                            except Exception:
                                pass

        # Combine all sources
        all_sources = {**sources, **dependency_sources}
        logger.info(
            "Analyzing with dependencies",
            direct_files=len(sources),
            dependency_files=len(dependency_sources),
        )

        return await self.analyze_incident(incident, source_files=all_sources)

    async def autonomous_explore_and_analyze(
        self,
        incident: dict[str, Any],
        max_exploration_depth: int = 2,
        max_files: int = 15,
    ) -> RootCauseAnalysis:
        """Autonomously explore the codebase and analyze the incident.

        This method implements true autonomous exploration:
        1. Parse stack trace to identify initial suspicious files
        2. Ask Gemini to identify additional files to explore
        3. Recursively explore and fetch relevant files
        4. Build comprehensive context for final analysis

        No human file list needed - the agent discovers everything itself.

        Args:
            incident: Incident data from LogCollector.
            max_exploration_depth: Maximum recursive exploration depth.
            max_files: Maximum number of files to include in analysis.

        Returns:
            RootCauseAnalysis: Comprehensive analysis results.
        """
        if not self.source_extractor or not self.target_repo_path:
            logger.warning("No target repo, falling back to basic analysis")
            return await self.analyze_incident(incident)

        logger.info(
            "Starting autonomous exploration",
            signature=incident.get("signature"),
            max_depth=max_exploration_depth,
        )

        # Phase 1: Initial file discovery from stack trace
        stack_trace = incident.get("trace", "")
        internal_frames = StackTraceParser.extract_internal_frames(stack_trace)

        discovered_files: dict[str, str] = {}
        explored_paths: set[str] = set()

        # Get initial sources from stack trace
        if internal_frames:
            initial_sources = self.source_extractor.get_sources_for_frames(
                internal_frames, max_files=5
            )
            discovered_files.update(initial_sources)
            explored_paths.update(initial_sources.keys())
            logger.info(
                "Phase 1: Stack trace files discovered",
                count=len(initial_sources),
            )

        # Phase 2: AI-guided exploration
        for depth in range(max_exploration_depth):
            if len(discovered_files) >= max_files:
                break

            # Ask Gemini what other files might be relevant
            suggestions = await self._ask_gemini_for_file_suggestions(
                incident=incident,
                current_files=discovered_files,
                explored_paths=explored_paths,
            )

            if not suggestions:
                logger.info(f"No more suggestions at depth {depth}")
                break

            # Explore suggested files
            new_files_found = 0
            for suggestion in suggestions:
                if len(discovered_files) >= max_files:
                    break

                file_path = self._resolve_file_path(suggestion)
                if file_path and file_path not in explored_paths:
                    explored_paths.add(file_path)
                    content = self._read_file(file_path)
                    if content:
                        discovered_files[file_path] = content
                        new_files_found += 1

                        # Also explore imports of newly discovered files
                        imports = self.source_extractor.extract_imports(content)
                        for imp in imports:
                            if imp.startswith("com.kintsugi.demo"):
                                imp_path = f"src/main/java/{imp.replace('.', '/')}.java"
                                if imp_path not in explored_paths:
                                    explored_paths.add(imp_path)
                                    imp_content = self._read_file(imp_path)
                                    if imp_content and len(discovered_files) < max_files:
                                        discovered_files[imp_path] = imp_content

            logger.info(
                f"Phase 2 depth {depth}: AI exploration",
                new_files=new_files_found,
                total_files=len(discovered_files),
            )

            if new_files_found == 0:
                break

        # Phase 3: Comprehensive analysis with all discovered context
        logger.info(
            "Phase 3: Final analysis",
            total_files=len(discovered_files),
            explored_paths=len(explored_paths),
        )

        return await self.analyze_incident(incident, source_files=discovered_files)

    async def _ask_gemini_for_file_suggestions(
        self,
        incident: dict[str, Any],
        current_files: dict[str, str],
        explored_paths: set[str],
    ) -> list[str]:
        """Ask Gemini to suggest additional files to explore.

        Args:
            incident: Incident data.
            current_files: Currently discovered files.
            explored_paths: Already explored paths.

        Returns:
            list[str]: Suggested file paths or class names.
        """
        # Build context summary
        file_list = "\n".join([f"- {path}" for path in current_files.keys()])

        # Extract class signatures for context
        class_info = []
        for path, content in list(current_files.items())[:5]:
            sig = self.source_extractor.get_class_signature(content)
            imports = self.source_extractor.extract_imports(content)[:5]
            class_info.append(f"{path}:\n  Signature: {sig}\n  Imports: {imports}")

        prompt = f"""You are investigating a Java application error. Based on the error and files already examined, suggest additional files that should be explored.

## Error Information
- Message: {incident.get('message', 'N/A')[:500]}
- Exception Type: {StackTraceParser.extract_exception_info(incident.get('trace', ''))[0]}

## Stack Trace (partial)
{incident.get('trace', 'N/A')[:1000]}

## Files Already Examined
{file_list}

## Class Information
{chr(10).join(class_info[:5])}

## Task
Suggest up to 5 additional files/classes that should be explored to understand:
1. Data flow that led to the error
2. Configuration or dependency that might be misconfigured
3. Related service/repository classes that interact with the error location
4. Model/entity classes that might have null fields

Return ONLY Java class names or file paths, one per line. Focus on internal classes (com.kintsugi.demo.*).
If no more exploration is needed, return "NONE".

Example output:
com.kintsugi.demo.repository.UserRepository
com.kintsugi.demo.model.User
com.kintsugi.demo.config.SecurityConfig"""

        try:
            response = await self.vertex_client.generate_text(
                prompt=prompt,
                temperature=0.3,
                max_tokens=500,
            )

            if "NONE" in response.upper():
                return []

            # Parse suggestions
            suggestions = []
            for line in response.strip().split("\n"):
                line = line.strip().lstrip("- ").lstrip("* ")
                if line and not line.startswith("#") and "NONE" not in line.upper():
                    # Skip if already explored
                    resolved = self._resolve_file_path(line)
                    if resolved and resolved not in explored_paths:
                        suggestions.append(line)

            return suggestions[:5]

        except Exception as e:
            logger.warning("Failed to get file suggestions from Gemini", error=str(e))
            return []

    def _resolve_file_path(self, suggestion: str) -> str | None:
        """Resolve a class name or path to a file path.

        Args:
            suggestion: Class name or file path.

        Returns:
            str | None: Resolved file path or None.
        """
        # If it's already a path
        if suggestion.endswith(".java"):
            return suggestion

        # Convert class name to path
        # com.kintsugi.demo.service.UserService -> src/main/java/com/kintsugi/demo/service/UserService.java
        if "." in suggestion:
            path = f"src/main/java/{suggestion.replace('.', '/')}.java"
            return path

        return None

    def _read_file(self, file_path: str) -> str | None:
        """Read a file from the target repository.

        Args:
            file_path: Relative path to the file.

        Returns:
            str | None: File content or None.
        """
        if not self.target_repo_path:
            return None

        full_path = self.target_repo_path / file_path
        if full_path.exists():
            try:
                return full_path.read_text()
            except Exception as e:
                logger.warning("Failed to read file", path=file_path, error=str(e))
        return None

    def discover_project_structure(self) -> dict[str, Any]:
        """Discover and return the project structure.

        Useful for understanding the codebase layout.

        Returns:
            dict: Project structure information.
        """
        if not self.target_repo_path:
            return {}

        structure = {
            "controllers": [],
            "services": [],
            "repositories": [],
            "models": [],
            "config": [],
            "other": [],
        }

        java_root = self.target_repo_path / "src" / "main" / "java"
        if not java_root.exists():
            return structure

        for java_file in java_root.rglob("*.java"):
            rel_path = str(java_file.relative_to(self.target_repo_path))
            name = java_file.stem

            # Categorize based on naming conventions and path
            if "controller" in rel_path.lower() or name.endswith("Controller"):
                structure["controllers"].append(rel_path)
            elif "service" in rel_path.lower() or name.endswith("Service"):
                structure["services"].append(rel_path)
            elif "repository" in rel_path.lower() or name.endswith("Repository"):
                structure["repositories"].append(rel_path)
            elif "model" in rel_path.lower() or "entity" in rel_path.lower():
                structure["models"].append(rel_path)
            elif "config" in rel_path.lower() or name.endswith("Config"):
                structure["config"].append(rel_path)
            else:
                structure["other"].append(rel_path)

        return structure

    async def analyze_autonomously(
        self,
        incident: dict[str, Any],
    ) -> RootCauseAnalysis:
        """Fully autonomous analysis - the preferred entry point.

        This is the main method for autonomous operation. It:
        1. Discovers relevant files without human input
        2. Explores the codebase following the error trail
        3. Builds comprehensive context for Gemini
        4. Returns detailed analysis with high confidence

        Args:
            incident: Incident data from LogCollector.

        Returns:
            RootCauseAnalysis: Complete autonomous analysis.
        """
        logger.info(
            "Starting fully autonomous analysis",
            signature=incident.get("signature"),
        )

        # Use the exploration-based analysis
        return await self.autonomous_explore_and_analyze(
            incident=incident,
            max_exploration_depth=2,
            max_files=12,
        )
