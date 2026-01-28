"""Tests for the enhanced sensing module.

Tests stack trace parsing, signature normalization, and source extraction.
"""

import pytest
from pathlib import Path

from src.sensing.log_collector import StackTraceNormalizer
from src.sensing.root_cause_analyzer import (
    StackFrame,
    StackTraceParser,
    SourceCodeExtractor,
)


# Sample Java stack trace for testing
SAMPLE_STACK_TRACE = """java.lang.NullPointerException: Cannot invoke method on null object
\tat com.kintsugi.demo.service.UserService.authenticate(UserService.java:45)
\tat com.kintsugi.demo.controller.UserController.login(UserController.java:32)
\tat sun.reflect.NativeMethodAccessorImpl.invoke0(Native Method)
\tat sun.reflect.NativeMethodAccessorImpl.invoke(NativeMethodAccessorImpl.java:62)
\tat org.springframework.web.servlet.FrameworkServlet.service(FrameworkServlet.java:897)
\tat javax.servlet.http.HttpServlet.service(HttpServlet.java:750)"""

SAMPLE_STACK_TRACE_WITH_CAUSED_BY = """java.lang.RuntimeException: User authentication failed
\tat com.kintsugi.demo.service.UserService.authenticate(UserService.java:50)
\tat com.kintsugi.demo.controller.UserController.login(UserController.java:32)
Caused by: java.lang.NullPointerException: password is null
\tat com.kintsugi.demo.model.User.validatePassword(User.java:78)
\tat com.kintsugi.demo.service.UserService.authenticate(UserService.java:48)
\t... 2 more"""


class TestStackTraceParser:
    """Tests for StackTraceParser class."""

    def test_parse_basic_stack_trace(self):
        """Test parsing a basic Java stack trace."""
        frames = StackTraceParser.parse(SAMPLE_STACK_TRACE)

        assert len(frames) == 6
        assert frames[0].class_name == "com.kintsugi.demo.service.UserService"
        assert frames[0].method_name == "authenticate"
        assert frames[0].file_name == "UserService.java"
        assert frames[0].line_number == 45
        assert frames[0].is_internal is True

    def test_extract_internal_frames(self):
        """Test extracting only internal frames."""
        internal_frames = StackTraceParser.extract_internal_frames(SAMPLE_STACK_TRACE)

        assert len(internal_frames) == 2
        assert all(f.is_internal for f in internal_frames)
        assert internal_frames[0].class_name == "com.kintsugi.demo.service.UserService"
        assert internal_frames[1].class_name == "com.kintsugi.demo.controller.UserController"

    def test_extract_exception_info(self):
        """Test extracting exception type and message."""
        exc_type, exc_msg = StackTraceParser.extract_exception_info(SAMPLE_STACK_TRACE)

        assert exc_type == "java.lang.NullPointerException"
        assert exc_msg == "Cannot invoke method on null object"

    def test_get_root_cause_frame(self):
        """Test getting the root cause frame."""
        root_frame = StackTraceParser.get_root_cause_frame(SAMPLE_STACK_TRACE)

        assert root_frame is not None
        assert root_frame.class_name == "com.kintsugi.demo.service.UserService"
        assert root_frame.method_name == "authenticate"
        assert root_frame.line_number == 45

    def test_generate_signature_consistent(self):
        """Test that signature generation is consistent."""
        sig1 = StackTraceParser.generate_signature(SAMPLE_STACK_TRACE)
        sig2 = StackTraceParser.generate_signature(SAMPLE_STACK_TRACE)

        assert sig1 == sig2
        assert len(sig1) == 12  # MD5 hash truncated to 12 chars

    def test_generate_signature_different_for_different_traces(self):
        """Test that different traces produce different signatures."""
        sig1 = StackTraceParser.generate_signature(SAMPLE_STACK_TRACE)
        sig2 = StackTraceParser.generate_signature(SAMPLE_STACK_TRACE_WITH_CAUSED_BY)

        assert sig1 != sig2

    def test_generate_signature_ignores_line_numbers(self):
        """Test that signatures are stable despite line number changes."""
        trace1 = """java.lang.NullPointerException
\tat com.kintsugi.demo.service.UserService.authenticate(UserService.java:45)"""
        trace2 = """java.lang.NullPointerException
\tat com.kintsugi.demo.service.UserService.authenticate(UserService.java:50)"""

        sig1 = StackTraceParser.generate_signature(trace1)
        sig2 = StackTraceParser.generate_signature(trace2)

        # Signatures should be the same since class.method chain is identical
        assert sig1 == sig2

    def test_source_path_generation(self):
        """Test that source paths are correctly generated."""
        frame = StackFrame(
            class_name="com.kintsugi.demo.service.UserService",
            method_name="authenticate",
            file_name="UserService.java",
            line_number=45,
            is_internal=True,
        )

        assert frame.source_path == "src/main/java/com/kintsugi/demo/service/UserService.java"

    def test_source_path_none_for_external(self):
        """Test that external classes don't get source paths."""
        frame = StackFrame(
            class_name="org.springframework.web.servlet.FrameworkServlet",
            method_name="service",
            file_name="FrameworkServlet.java",
            line_number=897,
            is_internal=False,
        )

        assert frame.source_path is None

    def test_parse_empty_trace(self):
        """Test handling of empty stack trace."""
        frames = StackTraceParser.parse("")
        assert frames == []

        frames = StackTraceParser.parse(None)
        assert frames == []


class TestStackTraceNormalizer:
    """Tests for StackTraceNormalizer class."""

    def test_normalize_stack_trace(self):
        """Test stack trace normalization."""
        normalized = StackTraceNormalizer.normalize_stack_trace(SAMPLE_STACK_TRACE)

        # Line numbers should be removed
        assert ":45)" not in normalized
        assert ":32)" not in normalized

    def test_extract_exception_chain(self):
        """Test extracting exception chain from caused-by traces."""
        exceptions = StackTraceNormalizer.extract_exception_chain(
            SAMPLE_STACK_TRACE_WITH_CAUSED_BY
        )

        assert len(exceptions) == 2
        assert exceptions[0][0] == "java.lang.RuntimeException"
        assert exceptions[1][0] == "java.lang.NullPointerException"

    def test_extract_internal_methods(self):
        """Test extracting internal method calls."""
        methods = StackTraceNormalizer.extract_internal_methods(SAMPLE_STACK_TRACE)

        assert len(methods) == 2
        assert "com.kintsugi.demo.service.UserService.authenticate" in methods
        assert "com.kintsugi.demo.controller.UserController.login" in methods

    def test_generate_signature_with_message(self):
        """Test signature generation with message fallback."""
        # When no stack trace, should use message
        sig = StackTraceNormalizer.generate_signature("", "Connection timeout for user 123")

        assert sig is not None
        assert len(sig) == 16

    def test_signature_normalizes_variable_parts(self):
        """Test that signatures normalize variable parts in messages."""
        sig1 = StackTraceNormalizer.generate_signature(
            "", "User 12345 not found at 2024-01-15T10:30:00"
        )
        sig2 = StackTraceNormalizer.generate_signature(
            "", "User 67890 not found at 2024-01-16T11:45:00"
        )

        # Should be same since numbers and timestamps are normalized
        assert sig1 == sig2

    def test_are_same_error(self):
        """Test error comparison."""
        trace1 = """java.lang.NullPointerException
\tat com.kintsugi.demo.service.UserService.authenticate(UserService.java:45)"""
        trace2 = """java.lang.NullPointerException
\tat com.kintsugi.demo.service.UserService.authenticate(UserService.java:50)"""

        assert StackTraceNormalizer.are_same_error(trace1, trace2)


class TestSourceCodeExtractor:
    """Tests for SourceCodeExtractor class."""

    @pytest.fixture
    def temp_repo(self, tmp_path):
        """Create a temporary repository structure."""
        # Create Java source directory
        java_dir = tmp_path / "src" / "main" / "java" / "com" / "kintsugi" / "demo" / "service"
        java_dir.mkdir(parents=True)

        # Create a sample Java file
        user_service = java_dir / "UserService.java"
        user_service.write_text("""package com.kintsugi.demo.service;

import com.kintsugi.demo.model.User;
import com.kintsugi.demo.repository.UserRepository;
import org.springframework.stereotype.Service;

@Service
public class UserService {
    private final UserRepository userRepository;

    public UserService(UserRepository userRepository) {
        this.userRepository = userRepository;
    }

    public boolean authenticate(String email, String password) {
        User user = userRepository.findByEmail(email);
        return user.validatePassword(password);  // NPE here
    }

    public User findById(Long id) {
        return userRepository.findById(id).orElse(null);
    }
}
""")

        return tmp_path

    def test_get_source_for_frame(self, temp_repo):
        """Test getting source code for a stack frame."""
        extractor = SourceCodeExtractor(temp_repo)
        frame = StackFrame(
            class_name="com.kintsugi.demo.service.UserService",
            method_name="authenticate",
            file_name="UserService.java",
            line_number=17,
            is_internal=True,
        )

        source = extractor.get_source_for_frame(frame)

        assert source is not None
        assert "public class UserService" in source
        assert "authenticate" in source

    def test_get_source_with_context(self, temp_repo):
        """Test getting source with context around a line."""
        extractor = SourceCodeExtractor(temp_repo)
        frame = StackFrame(
            class_name="com.kintsugi.demo.service.UserService",
            method_name="authenticate",
            file_name="UserService.java",
            line_number=17,
            is_internal=True,
        )

        full_source, snippet = extractor.get_source_with_context(frame, context_lines=3)

        assert full_source is not None
        assert snippet is not None
        assert ">>>" in snippet  # Error line marker
        assert "17" in snippet  # Line number

    def test_extract_imports(self, temp_repo):
        """Test extracting import statements."""
        extractor = SourceCodeExtractor(temp_repo)
        source = (
            temp_repo
            / "src/main/java/com/kintsugi/demo/service/UserService.java"
        ).read_text()

        imports = extractor.extract_imports(source)

        assert "com.kintsugi.demo.model.User" in imports
        assert "com.kintsugi.demo.repository.UserRepository" in imports
        assert "org.springframework.stereotype.Service" in imports

    def test_get_class_signature(self, temp_repo):
        """Test extracting class signature."""
        extractor = SourceCodeExtractor(temp_repo)
        source = (
            temp_repo
            / "src/main/java/com/kintsugi/demo/service/UserService.java"
        ).read_text()

        signature = extractor.get_class_signature(source)

        assert signature is not None
        assert "UserService" in signature

    def test_get_method_signatures(self, temp_repo):
        """Test extracting method signatures."""
        extractor = SourceCodeExtractor(temp_repo)
        source = (
            temp_repo
            / "src/main/java/com/kintsugi/demo/service/UserService.java"
        ).read_text()

        signatures = extractor.get_method_signatures(source)

        assert len(signatures) >= 2
        # Check for authenticate method
        assert any("authenticate" in sig for sig in signatures)
        assert any("findById" in sig for sig in signatures)

    def test_get_sources_for_multiple_frames(self, temp_repo):
        """Test getting sources for multiple frames."""
        extractor = SourceCodeExtractor(temp_repo)
        frames = [
            StackFrame(
                class_name="com.kintsugi.demo.service.UserService",
                method_name="authenticate",
                file_name="UserService.java",
                line_number=17,
                is_internal=True,
            ),
            StackFrame(
                class_name="com.kintsugi.demo.service.NonExistent",
                method_name="method",
                file_name="NonExistent.java",
                line_number=10,
                is_internal=True,
            ),
        ]

        sources = extractor.get_sources_for_frames(frames)

        # Should only get source for existing file
        assert len(sources) == 1
        assert "src/main/java/com/kintsugi/demo/service/UserService.java" in sources
