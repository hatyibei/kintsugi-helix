"""Testcontainer runner for executing tests in isolated environments.

Runs generated JUnit tests using Testcontainers with proper Maven integration.
Provides detailed result parsing and execution time extraction.
"""

import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

from src.reflection.test_generator import GeneratedTest
from src.utils.config import Settings

logger = structlog.get_logger()


@dataclass
class TestResult:
    """Result of running a test."""

    success: bool
    test_name: str
    output: str
    error_message: str | None
    execution_time_ms: int
    failure_type: str | None = None  # "assertion", "exception", "compilation", "timeout"
    expected_value: str | None = None
    actual_value: str | None = None
    stack_trace: str | None = None
    test_class: str | None = None
    test_method: str | None = None
    tests_run: int = 0
    tests_failed: int = 0
    tests_errors: int = 0
    tests_skipped: int = 0


@dataclass
class MavenTestSummary:
    """Summary of Maven test execution."""

    total_tests: int = 0
    failures: int = 0
    errors: int = 0
    skipped: int = 0
    execution_time_seconds: float = 0.0
    individual_results: list[TestResult] = field(default_factory=list)
    build_success: bool = False
    compilation_error: str | None = None
    raw_output: str = ""


class TestContainerRunner:
    """Runs tests in containerized environments with Docker/Testcontainers."""

    # Environment variables for Docker/Testcontainers
    DOCKER_ENV_VARS = {
        "DOCKER_HOST": os.environ.get("DOCKER_HOST", "unix:///var/run/docker.sock"),
        "TESTCONTAINERS_RYUK_DISABLED": os.environ.get(
            "TESTCONTAINERS_RYUK_DISABLED", "false"
        ),
        "TESTCONTAINERS_CHECKS_DISABLE": os.environ.get(
            "TESTCONTAINERS_CHECKS_DISABLE", "false"
        ),
    }

    def __init__(
        self,
        settings: Settings,
        project_path: str | Path,
        keep_test_files: bool = False,
    ) -> None:
        """Initialize the test runner.

        Args:
            settings: Application settings.
            project_path: Path to the target Java project.
            keep_test_files: If True, don't delete generated test files after run.
        """
        self.settings = settings
        self.project_path = Path(project_path).resolve()
        self.keep_test_files = keep_test_files
        self._written_test_files: list[Path] = []

        # Verify Maven wrapper exists
        self.mvnw_path = self.project_path / "mvnw"
        if not self.mvnw_path.exists():
            logger.warning("mvnw not found, will try system mvn", path=str(self.project_path))
            self.mvnw_path = Path("mvn")

        logger.info(
            "TestContainerRunner initialized",
            project=str(self.project_path),
            docker_host=self.DOCKER_ENV_VARS.get("DOCKER_HOST"),
        )

    def _get_env(self) -> dict[str, str]:
        """Get environment variables for subprocess calls.

        Returns:
            dict: Environment variables with Docker/Testcontainers settings.
        """
        env = os.environ.copy()
        env.update(self.DOCKER_ENV_VARS)

        # Set JAVA_HOME if not set
        if "JAVA_HOME" not in env:
            java_home = self._detect_java_home()
            if java_home:
                env["JAVA_HOME"] = java_home

        # Maven options for better output
        env["MAVEN_OPTS"] = env.get("MAVEN_OPTS", "") + " -Djansi.force=false"

        return env

    def _detect_java_home(self) -> str | None:
        """Detect JAVA_HOME from system.

        Returns:
            str | None: Path to Java installation or None.
        """
        try:
            result = subprocess.run(
                ["java", "-XshowSettings:properties", "-version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            # Parse java.home from output
            for line in result.stderr.split("\n"):
                if "java.home" in line:
                    return line.split("=")[1].strip()
        except (subprocess.TimeoutExpired, FileNotFoundError, IndexError):
            pass
        return None

    def _write_test_file(self, test: GeneratedTest) -> Path:
        """Write test file to project.

        Args:
            test: Generated test to write.

        Returns:
            Path: Path to written test file.
        """
        test_dir = self.project_path / "src" / "test" / "java"

        # Extract package from target class
        package_parts = test.target_class.rsplit(".", 1)[0].split(".")
        test_package_dir = test_dir.joinpath(*package_parts)
        test_package_dir.mkdir(parents=True, exist_ok=True)

        test_file = test_package_dir / f"{test.class_name}.java"
        test_file.write_text(test.source_code)

        self._written_test_files.append(test_file)

        logger.debug("Test file written", path=str(test_file))
        return test_file

    def _cleanup_test_files(self) -> None:
        """Remove written test files."""
        if self.keep_test_files or self.settings.dry_run:
            return

        for test_file in self._written_test_files:
            try:
                if test_file.exists():
                    test_file.unlink()
                    logger.debug("Test file removed", path=str(test_file))
            except OSError as e:
                logger.warning("Failed to remove test file", path=str(test_file), error=str(e))

        self._written_test_files.clear()

    def _parse_maven_output(self, output: str) -> MavenTestSummary:
        """Parse Maven test output for detailed results.

        Args:
            output: Raw Maven output.

        Returns:
            MavenTestSummary: Parsed test summary.
        """
        summary = MavenTestSummary(raw_output=output)

        # Check for compilation errors
        if "COMPILATION ERROR" in output or "[ERROR] Failed to execute goal" in output:
            compilation_match = re.search(
                r"\[ERROR\].*?\.java:\[(\d+),(\d+)\](.*?)(?=\[ERROR\]|\[INFO\]|$)",
                output,
                re.DOTALL,
            )
            if compilation_match:
                summary.compilation_error = compilation_match.group(0).strip()
            else:
                # Extract general error message
                error_lines = [
                    line for line in output.split("\n")
                    if "[ERROR]" in line and "BUILD FAILURE" not in line
                ]
                summary.compilation_error = "\n".join(error_lines[:10])
            return summary

        # Parse test summary line
        # Example: "Tests run: 5, Failures: 1, Errors: 0, Skipped: 0"
        summary_match = re.search(
            r"Tests run:\s*(\d+),\s*Failures:\s*(\d+),\s*Errors:\s*(\d+),\s*Skipped:\s*(\d+)",
            output,
        )
        if summary_match:
            summary.total_tests = int(summary_match.group(1))
            summary.failures = int(summary_match.group(2))
            summary.errors = int(summary_match.group(3))
            summary.skipped = int(summary_match.group(4))
            summary.build_success = summary.failures == 0 and summary.errors == 0

        # Parse execution time
        # Example: "Time elapsed: 1.234 s"
        time_match = re.search(r"Time elapsed:\s*([\d.]+)\s*s", output)
        if time_match:
            summary.execution_time_seconds = float(time_match.group(1))

        # Also try total time from build
        total_time_match = re.search(r"Total time:\s*([\d.:]+)", output)
        if total_time_match and summary.execution_time_seconds == 0:
            time_str = total_time_match.group(1)
            # Parse formats like "1:23 min" or "45.678 s"
            if ":" in time_str:
                parts = time_str.replace(" min", "").split(":")
                summary.execution_time_seconds = int(parts[0]) * 60 + float(parts[1])
            else:
                summary.execution_time_seconds = float(time_str.replace(" s", ""))

        # Parse individual test failures
        # Pattern: "TestClassName.testMethodName()" followed by failure info
        failure_pattern = re.compile(
            r"(?:FAILURE!|FAILED)\s*\n"
            r"(?:.*?(\w+)\.(\w+)\s*(?:\(.*?\))?\s*"  # Class.method
            r"(?:Time elapsed:.*?\n)?"
            r"(.*?)"  # Error details
            r"(?=\n\n|\Z))",
            re.DOTALL,
        )

        for match in failure_pattern.finditer(output):
            test_class = match.group(1) if match.group(1) else None
            test_method = match.group(2) if match.group(2) else None
            error_text = match.group(3).strip() if match.group(3) else ""

            result = TestResult(
                success=False,
                test_name=f"{test_class}.{test_method}" if test_class else "unknown",
                output=error_text,
                error_message=self._extract_assertion_message(error_text),
                execution_time_ms=0,
                test_class=test_class,
                test_method=test_method,
            )

            # Determine failure type
            if "AssertionError" in error_text or "expected:" in error_text.lower():
                result.failure_type = "assertion"
                # Try to extract expected/actual values
                expected_actual = re.search(
                    r"expected:\s*<(.+?)>\s*but was:\s*<(.+?)>",
                    error_text,
                    re.IGNORECASE,
                )
                if expected_actual:
                    result.expected_value = expected_actual.group(1)
                    result.actual_value = expected_actual.group(2)
            elif "Exception" in error_text or "Error" in error_text:
                result.failure_type = "exception"
                # Extract stack trace
                stack_lines = [
                    line for line in error_text.split("\n")
                    if line.strip().startswith("at ") or "Exception" in line or "Error" in line
                ]
                result.stack_trace = "\n".join(stack_lines[:15])
            else:
                result.failure_type = "unknown"

            summary.individual_results.append(result)

        return summary

    def _extract_assertion_message(self, error_text: str) -> str | None:
        """Extract human-readable assertion message.

        Args:
            error_text: Error text from test output.

        Returns:
            str | None: Extracted message or None.
        """
        # Try different assertion message patterns
        patterns = [
            r"AssertionError:\s*(.+?)(?:\n|$)",
            r"expected:\s*<.+?>\s*but was:\s*<.+?>",
            r"org\.junit\..*?:\s*(.+?)(?:\n|$)",
            r"java\.lang\.AssertionError:\s*(.+?)(?:\n|$)",
        ]

        for pattern in patterns:
            match = re.search(pattern, error_text, re.IGNORECASE)
            if match:
                return match.group(0).strip()[:500]  # Limit length

        # Fallback: first non-empty line
        for line in error_text.split("\n"):
            line = line.strip()
            if line and not line.startswith("at "):
                return line[:500]

        return None

    def _extract_error(self, output: str) -> str | None:
        """Extract error message from Maven output.

        Args:
            output: Maven test output.

        Returns:
            str | None: Extracted error message or None.
        """
        summary = self._parse_maven_output(output)

        if summary.compilation_error:
            return f"Compilation Error:\n{summary.compilation_error}"

        if summary.individual_results:
            errors = []
            for result in summary.individual_results:
                if result.error_message:
                    errors.append(f"{result.test_name}: {result.error_message}")
            if errors:
                return "\n".join(errors)

        # Fallback to old parsing method
        lines = output.split("\n")
        error_lines = []
        capture = False

        for line in lines:
            if "FAILURE" in line or "ERROR" in line or "AssertionError" in line:
                capture = True
            if capture:
                error_lines.append(line)
                if len(error_lines) >= 30:
                    break

        return "\n".join(error_lines) if error_lines else None

    def run_test(
        self,
        test: GeneratedTest,
        timeout: int = 180,
    ) -> TestResult:
        """Run a generated test.

        Args:
            test: The generated test to run.
            timeout: Timeout in seconds (default: 180).

        Returns:
            TestResult: Result of the test execution.
        """
        logger.info(
            "Running test",
            class_name=test.class_name,
            method=test.test_method_name,
        )

        # Write test file to project
        test_file = self._write_test_file(test)

        # Build test class fully qualified name
        package_parts = test.target_class.rsplit(".", 1)[0].split(".")
        test_class_fqn = f"{'.'.join(package_parts)}.{test.class_name}"

        # Run the specific test with verbose output
        cmd = [
            str(self.mvnw_path),
            "test",
            f"-Dtest={test_class_fqn}#{test.test_method_name}",
            "-DfailIfNoTests=false",
            "-Dsurefire.useFile=false",  # Print output to console
            "--batch-mode",  # Non-interactive mode
        ]

        start_time = time.time()

        try:
            result = subprocess.run(
                cmd,
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=self._get_env(),
            )

            elapsed_ms = int((time.time() - start_time) * 1000)
            output = result.stdout + "\n" + result.stderr

            # Parse detailed results
            maven_summary = self._parse_maven_output(output)

            success = result.returncode == 0 and maven_summary.build_success
            error_message = None

            if not success:
                if maven_summary.compilation_error:
                    error_message = f"Compilation Error:\n{maven_summary.compilation_error}"
                elif maven_summary.individual_results:
                    error_message = maven_summary.individual_results[0].error_message
                else:
                    error_message = self._extract_error(output)

            logger.info(
                "Test completed",
                success=success,
                class_name=test.class_name,
                execution_time_ms=elapsed_ms,
                failures=maven_summary.failures,
                errors=maven_summary.errors,
            )

            test_result = TestResult(
                success=success,
                test_name=f"{test.class_name}#{test.test_method_name}",
                output=output,
                error_message=error_message,
                execution_time_ms=elapsed_ms,
                test_class=test.class_name,
                test_method=test.test_method_name,
                tests_run=maven_summary.total_tests,
                tests_failed=maven_summary.failures,
                tests_errors=maven_summary.errors,
                tests_skipped=maven_summary.skipped,
            )

            # Copy failure type if available
            if maven_summary.individual_results:
                first_result = maven_summary.individual_results[0]
                test_result.failure_type = first_result.failure_type
                test_result.expected_value = first_result.expected_value
                test_result.actual_value = first_result.actual_value
                test_result.stack_trace = first_result.stack_trace

            return test_result

        except subprocess.TimeoutExpired:
            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.error("Test timed out", class_name=test.class_name, timeout=timeout)
            return TestResult(
                success=False,
                test_name=f"{test.class_name}#{test.test_method_name}",
                output="",
                error_message=f"Test execution timed out after {timeout} seconds",
                execution_time_ms=elapsed_ms,
                failure_type="timeout",
                test_class=test.class_name,
                test_method=test.test_method_name,
            )
        finally:
            # Clean up test file unless keeping for debugging
            if not self.keep_test_files and not self.settings.dry_run:
                if test_file.exists():
                    try:
                        test_file.unlink()
                        self._written_test_files.remove(test_file)
                    except (OSError, ValueError):
                        pass

    def run_all_tests(self, timeout: int = 600) -> MavenTestSummary:
        """Run all tests in the project.

        Args:
            timeout: Timeout in seconds (default: 600).

        Returns:
            MavenTestSummary: Detailed summary of all test results.
        """
        logger.info("Running all tests", project=str(self.project_path))

        cmd = [
            str(self.mvnw_path),
            "test",
            "-DfailIfNoTests=false",
            "-Dsurefire.useFile=false",
            "--batch-mode",
        ]

        start_time = time.time()

        try:
            result = subprocess.run(
                cmd,
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=self._get_env(),
            )

            elapsed_seconds = time.time() - start_time
            output = result.stdout + "\n" + result.stderr

            # Parse detailed results
            summary = self._parse_maven_output(output)
            summary.execution_time_seconds = elapsed_seconds
            summary.build_success = result.returncode == 0

            logger.info(
                "All tests completed",
                success=summary.build_success,
                total=summary.total_tests,
                failures=summary.failures,
                errors=summary.errors,
                skipped=summary.skipped,
                elapsed_seconds=elapsed_seconds,
            )

            return summary

        except subprocess.TimeoutExpired:
            logger.error("Tests timed out", timeout=timeout)
            return MavenTestSummary(
                build_success=False,
                raw_output=f"Test execution timed out after {timeout} seconds",
            )

    def verify_bug_reproduction(self, test: GeneratedTest) -> tuple[bool, TestResult]:
        """Verify that a test correctly reproduces a bug (fails as expected).

        Args:
            test: The failing test to verify.

        Returns:
            tuple: (bug_confirmed, test_result)
                - bug_confirmed: True if the test fails as expected (bug confirmed)
                - test_result: Detailed test result for feedback
        """
        result = self.run_test(test)

        # For bug reproduction, we expect the test to FAIL
        bug_confirmed = not result.success

        logger.info(
            "Bug reproduction verification",
            bug_confirmed=bug_confirmed,
            test=test.test_method_name,
            failure_type=result.failure_type,
            error=result.error_message[:100] if result.error_message else None,
        )

        return bug_confirmed, result

    def verify_fix(self, test: GeneratedTest) -> tuple[bool, TestResult]:
        """Verify that a fix makes the test pass.

        Args:
            test: The regression test to verify.

        Returns:
            tuple: (fix_works, test_result)
                - fix_works: True if the test passes (fix confirmed)
                - test_result: Detailed test result for feedback
        """
        result = self.run_test(test)

        logger.info(
            "Fix verification",
            fix_works=result.success,
            test=test.test_method_name,
        )

        return result.success, result

    def verify_no_regression(self) -> tuple[bool, MavenTestSummary]:
        """Verify that all existing tests still pass.

        Returns:
            tuple: (no_regression, summary)
                - no_regression: True if all tests pass
                - summary: Detailed test summary
        """
        summary = self.run_all_tests()

        no_regression = summary.build_success and summary.failures == 0 and summary.errors == 0

        logger.info(
            "Regression check",
            no_regression=no_regression,
            total_tests=summary.total_tests,
            failures=summary.failures,
            errors=summary.errors,
        )

        return no_regression, summary

    def run_tests_with_retry(
        self,
        test: GeneratedTest,
        max_retries: int = 3,
    ) -> tuple[bool, list[TestResult]]:
        """Run test with retries for flaky tests.

        Args:
            test: Test to run.
            max_retries: Maximum retry attempts.

        Returns:
            tuple: (final_success, all_results)
        """
        results = []

        for attempt in range(1, max_retries + 1):
            result = self.run_test(test)
            results.append(result)

            if result.success:
                logger.info(
                    "Test passed",
                    attempt=attempt,
                    test=test.test_method_name,
                )
                return True, results

            logger.warning(
                "Test failed, will retry",
                attempt=attempt,
                max_retries=max_retries,
                test=test.test_method_name,
                error=result.error_message[:100] if result.error_message else None,
            )

            if attempt < max_retries:
                # Brief pause before retry
                time.sleep(1)

        return False, results

    def get_test_output_for_feedback(self, result: TestResult) -> str:
        """Format test result for feedback to AI model.

        Args:
            result: Test result to format.

        Returns:
            str: Formatted feedback string for AI model.
        """
        feedback_parts = [
            f"Test: {result.test_name}",
            f"Status: {'PASSED' if result.success else 'FAILED'}",
            f"Execution Time: {result.execution_time_ms}ms",
        ]

        if result.failure_type:
            feedback_parts.append(f"Failure Type: {result.failure_type}")

        if result.error_message:
            feedback_parts.append(f"Error Message:\n{result.error_message}")

        if result.expected_value and result.actual_value:
            feedback_parts.append(f"Expected: {result.expected_value}")
            feedback_parts.append(f"Actual: {result.actual_value}")

        if result.stack_trace:
            feedback_parts.append(f"Stack Trace:\n{result.stack_trace}")

        # Include relevant portion of raw output
        if result.output and len(result.output) > 100:
            # Extract most relevant portion (around errors)
            lines = result.output.split("\n")
            relevant_lines = []
            capture = False
            for line in lines:
                if "FAILURE" in line or "ERROR" in line or "Exception" in line:
                    capture = True
                if capture:
                    relevant_lines.append(line)
                    if len(relevant_lines) >= 50:
                        break
            if relevant_lines:
                feedback_parts.append(f"Relevant Output:\n{''.join(relevant_lines[:50])}")

        return "\n".join(feedback_parts)
