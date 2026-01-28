"""Tests for the reflection module.

Tests test generation, Maven result parsing, and the fix-verify loop.
"""

import pytest
from dataclasses import dataclass

from src.reflection.test_generator import (
    EdgeCaseAnalyzer,
    GeneratedTest,
)
from src.reflection.testcontainer_runner import (
    MavenTestSummary,
    TestContainerRunner,
    TestResult,
)


# Sample source code for testing
SAMPLE_JAVA_SOURCE = """package com.kintsugi.demo.service;

import com.kintsugi.demo.model.User;
import com.kintsugi.demo.repository.UserRepository;

public class UserService {
    private final UserRepository userRepository;

    public UserService(UserRepository userRepository) {
        this.userRepository = userRepository;
    }

    public boolean authenticate(String email, String password) {
        User user = userRepository.findByEmail(email);
        return user.validatePassword(password);  // NPE if user is null
    }

    public Boolean isUserActive(Long userId) {
        User user = userRepository.findById(userId).orElse(null);
        return user.isActive();  // NPE - auto-unboxing Boolean
    }

    public int getUserAge(Long userId) {
        User user = userRepository.findById(userId).orElse(null);
        Integer age = user.getAge();
        return age;  // NPE - auto-unboxing Integer
    }
}
"""

SAMPLE_MAVEN_OUTPUT_SUCCESS = """[INFO] Scanning for projects...
[INFO] --- maven-surefire-plugin:3.0.0:test (default-test) @ demo ---
[INFO] Using auto detected provider org.apache.maven.surefire.junitplatform.JUnitPlatformProvider
[INFO] Running com.kintsugi.demo.service.UserServiceTest
[INFO] Tests run: 3, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 1.234 s - in com.kintsugi.demo.service.UserServiceTest
[INFO]
[INFO] Results:
[INFO]
[INFO] Tests run: 3, Failures: 0, Errors: 0, Skipped: 0
[INFO]
[INFO] ------------------------------------------------------------------------
[INFO] BUILD SUCCESS
[INFO] ------------------------------------------------------------------------
[INFO] Total time:  5.678 s
[INFO] Finished at: 2024-01-15T10:30:00Z
[INFO] ------------------------------------------------------------------------"""

SAMPLE_MAVEN_OUTPUT_FAILURE = """[INFO] Scanning for projects...
[INFO] --- maven-surefire-plugin:3.0.0:test (default-test) @ demo ---
[INFO] Using auto detected provider org.apache.maven.surefire.junitplatform.JUnitPlatformProvider
[INFO] Running com.kintsugi.demo.service.UserServiceTest
[ERROR] Tests run: 3, Failures: 1, Errors: 0, Skipped: 0, Time elapsed: 1.234 s <<< FAILURE! - in com.kintsugi.demo.service.UserServiceTest
[ERROR] com.kintsugi.demo.service.UserServiceTest.testAuthenticateWithNullUser  Time elapsed: 0.045 s  <<< FAILURE!
java.lang.NullPointerException: Cannot invoke "com.kintsugi.demo.model.User.validatePassword(String)" because "user" is null
	at com.kintsugi.demo.service.UserService.authenticate(UserService.java:14)
	at com.kintsugi.demo.service.UserServiceTest.testAuthenticateWithNullUser(UserServiceTest.java:25)

[INFO]
[INFO] Results:
[INFO]
[ERROR] Failures:
[ERROR]   UserServiceTest.testAuthenticateWithNullUser:25 NullPointerException Cannot invoke "com.kintsugi.demo.model.User.validatePassword(String)" because "user" is null
[INFO]
[ERROR] Tests run: 3, Failures: 1, Errors: 0, Skipped: 0
[INFO]
[INFO] ------------------------------------------------------------------------
[INFO] BUILD FAILURE
[INFO] ------------------------------------------------------------------------
[INFO] Total time:  5.678 s
[INFO] Finished at: 2024-01-15T10:30:00Z
[INFO] ------------------------------------------------------------------------"""

SAMPLE_MAVEN_OUTPUT_COMPILATION_ERROR = """[INFO] Scanning for projects...
[INFO] --- maven-compiler-plugin:3.11.0:compile (default-compile) @ demo ---
[INFO] Changes detected - recompiling the module!
[ERROR] COMPILATION ERROR :
[INFO] -------------------------------------------------------------
[ERROR] /home/user/target-app/src/test/java/com/kintsugi/demo/service/UserServiceTest.java:[15,5] cannot find symbol
  symbol:   class Useer
  location: class com.kintsugi.demo.service.UserServiceTest
[ERROR] /home/user/target-app/src/test/java/com/kintsugi/demo/service/UserServiceTest.java:[20,13] cannot find symbol
  symbol:   method authenticate(String,String)
  location: variable service of type com.kintsugi.demo.service.UserService
[INFO] 2 errors
[INFO] -------------------------------------------------------------
[INFO] ------------------------------------------------------------------------
[INFO] BUILD FAILURE
[INFO] ------------------------------------------------------------------------
[INFO] Total time:  2.345 s
[INFO] Finished at: 2024-01-15T10:30:00Z
[INFO] ------------------------------------------------------------------------
[ERROR] Failed to execute goal org.apache.maven.plugins:maven-compiler-plugin:3.11.0:compile (default-compile) on project demo: Compilation failure"""

SAMPLE_MAVEN_OUTPUT_ASSERTION_ERROR = """[INFO] Running com.kintsugi.demo.service.UserServiceTest
[ERROR] Tests run: 1, Failures: 1, Errors: 0, Skipped: 0, Time elapsed: 0.123 s <<< FAILURE! - in com.kintsugi.demo.service.UserServiceTest
[ERROR] com.kintsugi.demo.service.UserServiceTest.testUserCount  Time elapsed: 0.023 s  <<< FAILURE!
org.opentest4j.AssertionFailedError: expected: <5> but was: <3>
	at org.junit.jupiter.api.AssertionUtils.fail(AssertionUtils.java:55)
	at org.junit.jupiter.api.AssertEquals.failNotEqual(AssertEquals.java:195)
	at com.kintsugi.demo.service.UserServiceTest.testUserCount(UserServiceTest.java:42)

[INFO] Tests run: 1, Failures: 1, Errors: 0, Skipped: 0"""


class TestEdgeCaseAnalyzer:
    """Tests for EdgeCaseAnalyzer class."""

    def test_identify_npe_risks_method_call(self):
        """Test identifying NPE risk from method calls on potentially null objects."""
        source = """
        User user = repository.findById(id).orElse(null);
        user.getName();
        """
        risks = EdgeCaseAnalyzer.identify_npe_risks(source)

        assert len(risks) >= 1
        # Should detect the method call on potentially null user
        assert any("method call" in r.get("reason", "").lower() for r in risks)

    def test_identify_npe_risks_auto_unboxing(self):
        """Test identifying NPE risk from auto-unboxing."""
        risks = EdgeCaseAnalyzer.identify_npe_risks(SAMPLE_JAVA_SOURCE)

        # Should detect Boolean, Integer potential unboxing issues
        assert len(risks) >= 1
        risk_types = [r.get("reason", "") for r in risks]
        assert any("Boolean" in r or "Integer" in r for r in risk_types)

    def test_identify_npe_risks_empty_source(self):
        """Test handling of empty source code."""
        risks = EdgeCaseAnalyzer.identify_npe_risks("")
        assert risks == []

        risks = EdgeCaseAnalyzer.identify_npe_risks(None)
        assert risks == []

    def test_get_edge_case_suggestions(self):
        """Test getting edge case suggestions."""
        suggestions = EdgeCaseAnalyzer.get_edge_case_suggestions("NullPointerException")

        assert len(suggestions) > 0
        assert any("null" in s.lower() for s in suggestions)

    def test_get_edge_case_suggestions_unknown_exception(self):
        """Test suggestions for unknown exception types."""
        suggestions = EdgeCaseAnalyzer.get_edge_case_suggestions("CustomException")

        # Should return generic suggestions
        assert len(suggestions) > 0


class TestGeneratedTest:
    """Tests for GeneratedTest dataclass."""

    def test_generated_test_creation(self):
        """Test creating a GeneratedTest instance."""
        test = GeneratedTest(
            class_name="UserServiceTest",
            test_method_name="testAuthenticateWithNullUser",
            source_code="// test code",
            target_class="com.kintsugi.demo.service.UserService",
            expected_behavior="Should throw NullPointerException",
            imports=["org.junit.jupiter.api.Test"],
            test_type="bug_reproduction",
            edge_cases_covered=["null_user"],
            assertions_count=1,
        )

        assert test.class_name == "UserServiceTest"
        assert test.test_type == "bug_reproduction"
        assert len(test.edge_cases_covered) == 1

    def test_generated_test_defaults(self):
        """Test default values for GeneratedTest."""
        test = GeneratedTest(
            class_name="Test",
            test_method_name="testMethod",
            source_code="code",
            target_class="Class",
            expected_behavior="behavior",
        )

        assert test.imports == []
        assert test.test_type == "bug_reproduction"
        assert test.edge_cases_covered == []
        assert test.assertions_count == 0


class TestMavenOutputParsing:
    """Tests for Maven output parsing in TestContainerRunner."""

    def test_parse_success_output(self):
        """Test parsing successful Maven output."""
        # Create a mock settings object
        @dataclass
        class MockSettings:
            dry_run: bool = True

        runner = TestContainerRunner.__new__(TestContainerRunner)
        runner.settings = MockSettings()

        summary = runner._parse_maven_output(SAMPLE_MAVEN_OUTPUT_SUCCESS)

        assert summary.total_tests == 3
        assert summary.failures == 0
        assert summary.errors == 0
        assert summary.skipped == 0
        assert summary.build_success is True
        assert summary.compilation_error is None

    def test_parse_failure_output(self):
        """Test parsing Maven output with test failures."""
        @dataclass
        class MockSettings:
            dry_run: bool = True

        runner = TestContainerRunner.__new__(TestContainerRunner)
        runner.settings = MockSettings()

        summary = runner._parse_maven_output(SAMPLE_MAVEN_OUTPUT_FAILURE)

        assert summary.total_tests == 3
        assert summary.failures == 1
        assert summary.errors == 0
        assert summary.build_success is False

    def test_parse_compilation_error(self):
        """Test parsing Maven output with compilation errors."""
        @dataclass
        class MockSettings:
            dry_run: bool = True

        runner = TestContainerRunner.__new__(TestContainerRunner)
        runner.settings = MockSettings()

        summary = runner._parse_maven_output(SAMPLE_MAVEN_OUTPUT_COMPILATION_ERROR)

        assert summary.compilation_error is not None
        assert "cannot find symbol" in summary.compilation_error

    def test_parse_assertion_error(self):
        """Test parsing Maven output with assertion errors."""
        @dataclass
        class MockSettings:
            dry_run: bool = True

        runner = TestContainerRunner.__new__(TestContainerRunner)
        runner.settings = MockSettings()

        summary = runner._parse_maven_output(SAMPLE_MAVEN_OUTPUT_ASSERTION_ERROR)

        assert summary.failures == 1
        assert summary.build_success is False

    def test_extract_assertion_message(self):
        """Test extracting assertion message from error text."""
        @dataclass
        class MockSettings:
            dry_run: bool = True

        runner = TestContainerRunner.__new__(TestContainerRunner)
        runner.settings = MockSettings()

        error_text = "org.opentest4j.AssertionFailedError: expected: <5> but was: <3>"
        message = runner._extract_assertion_message(error_text)

        assert message is not None
        assert "expected" in message.lower()


class TestTestResult:
    """Tests for TestResult dataclass."""

    def test_test_result_creation(self):
        """Test creating a TestResult instance."""
        result = TestResult(
            success=False,
            test_name="UserServiceTest#testAuth",
            output="test output",
            error_message="NullPointerException",
            execution_time_ms=150,
            failure_type="exception",
            stack_trace="at com.example.Test.method(Test.java:10)",
        )

        assert result.success is False
        assert result.failure_type == "exception"
        assert result.execution_time_ms == 150

    def test_test_result_defaults(self):
        """Test default values for TestResult."""
        result = TestResult(
            success=True,
            test_name="Test#test",
            output="",
            error_message=None,
            execution_time_ms=100,
        )

        assert result.failure_type is None
        assert result.expected_value is None
        assert result.actual_value is None
        assert result.tests_run == 0


class TestMavenTestSummary:
    """Tests for MavenTestSummary dataclass."""

    def test_maven_test_summary_creation(self):
        """Test creating a MavenTestSummary instance."""
        summary = MavenTestSummary(
            total_tests=10,
            failures=2,
            errors=1,
            skipped=0,
            execution_time_seconds=5.5,
            build_success=False,
        )

        assert summary.total_tests == 10
        assert summary.failures == 2
        assert summary.errors == 1
        assert summary.build_success is False

    def test_maven_test_summary_defaults(self):
        """Test default values for MavenTestSummary."""
        summary = MavenTestSummary()

        assert summary.total_tests == 0
        assert summary.failures == 0
        assert summary.errors == 0
        assert summary.skipped == 0
        assert summary.execution_time_seconds == 0.0
        assert summary.build_success is False
        assert summary.individual_results == []
        assert summary.compilation_error is None
        assert summary.raw_output == ""


class TestTestFeedbackFormatting:
    """Tests for formatting test results as feedback."""

    def test_get_test_output_for_feedback(self):
        """Test formatting test result for AI feedback."""
        @dataclass
        class MockSettings:
            dry_run: bool = True

        runner = TestContainerRunner.__new__(TestContainerRunner)
        runner.settings = MockSettings()

        result = TestResult(
            success=False,
            test_name="UserServiceTest#testAuth",
            output="Long test output...",
            error_message="NullPointerException: user is null",
            execution_time_ms=150,
            failure_type="exception",
            expected_value=None,
            actual_value=None,
            stack_trace="at com.example.UserService.auth(UserService.java:45)",
        )

        feedback = runner.get_test_output_for_feedback(result)

        assert "UserServiceTest#testAuth" in feedback
        assert "FAILED" in feedback
        assert "NullPointerException" in feedback
        assert "exception" in feedback.lower()

    def test_get_test_output_for_feedback_with_expected_actual(self):
        """Test formatting with expected/actual values."""
        @dataclass
        class MockSettings:
            dry_run: bool = True

        runner = TestContainerRunner.__new__(TestContainerRunner)
        runner.settings = MockSettings()

        result = TestResult(
            success=False,
            test_name="Test#test",
            output="",
            error_message="Assertion failed",
            execution_time_ms=50,
            failure_type="assertion",
            expected_value="5",
            actual_value="3",
        )

        feedback = runner.get_test_output_for_feedback(result)

        assert "Expected: 5" in feedback
        assert "Actual: 3" in feedback
