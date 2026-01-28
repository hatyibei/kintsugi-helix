"""Testcontainer runner for executing tests in isolated environments.

Runs generated JUnit tests using Testcontainers.
"""

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

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


class TestContainerRunner:
    """Runs tests in containerized environments."""

    def __init__(self, settings: Settings, project_path: str | Path) -> None:
        """Initialize the test runner.

        Args:
            settings: Application settings.
            project_path: Path to the target Java project.
        """
        self.settings = settings
        self.project_path = Path(project_path)
        logger.info("TestContainerRunner initialized", project=str(self.project_path))

    def run_test(self, test: GeneratedTest) -> TestResult:
        """Run a generated test.

        Args:
            test: The generated test to run.

        Returns:
            TestResult: Result of the test execution.
        """
        logger.info(
            "Running test",
            class_name=test.class_name,
            method=test.test_method_name,
        )

        # Write test file to project
        test_dir = self.project_path / "src" / "test" / "java"
        package_parts = test.target_class.rsplit(".", 1)[0].split(".")
        test_package_dir = test_dir.joinpath(*package_parts)
        test_package_dir.mkdir(parents=True, exist_ok=True)

        test_file = test_package_dir / f"{test.class_name}.java"
        test_file.write_text(test.source_code)

        logger.debug("Test file written", path=str(test_file))

        # Run the specific test
        test_class_fqn = f"{'.'.join(package_parts)}.{test.class_name}"
        cmd = [
            "./mvnw",
            "test",
            f"-Dtest={test_class_fqn}#{test.test_method_name}",
            "-q",
        ]

        try:
            result = subprocess.run(
                cmd,
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=120,
            )

            success = result.returncode == 0
            output = result.stdout + result.stderr
            error_message = None if success else self._extract_error(output)

            logger.info(
                "Test completed",
                success=success,
                class_name=test.class_name,
            )

            return TestResult(
                success=success,
                test_name=f"{test.class_name}#{test.test_method_name}",
                output=output,
                error_message=error_message,
                execution_time_ms=0,  # TODO: Extract from Maven output
            )

        except subprocess.TimeoutExpired:
            logger.error("Test timed out", class_name=test.class_name)
            return TestResult(
                success=False,
                test_name=f"{test.class_name}#{test.test_method_name}",
                output="",
                error_message="Test execution timed out after 120 seconds",
                execution_time_ms=120000,
            )
        finally:
            # Clean up test file if not in dry run mode
            if not self.settings.dry_run and test_file.exists():
                test_file.unlink()

    def run_all_tests(self) -> list[TestResult]:
        """Run all tests in the project.

        Returns:
            list[TestResult]: Results of all tests.
        """
        logger.info("Running all tests", project=str(self.project_path))

        cmd = ["./mvnw", "test", "-q"]

        try:
            result = subprocess.run(
                cmd,
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=300,
            )

            success = result.returncode == 0
            output = result.stdout + result.stderr

            logger.info("All tests completed", success=success)

            return [
                TestResult(
                    success=success,
                    test_name="all",
                    output=output,
                    error_message=None if success else self._extract_error(output),
                    execution_time_ms=0,
                )
            ]

        except subprocess.TimeoutExpired:
            logger.error("Tests timed out")
            return [
                TestResult(
                    success=False,
                    test_name="all",
                    output="",
                    error_message="Test execution timed out after 300 seconds",
                    execution_time_ms=300000,
                )
            ]

    def verify_bug_reproduction(self, test: GeneratedTest) -> bool:
        """Verify that a test correctly reproduces a bug (fails as expected).

        Args:
            test: The failing test to verify.

        Returns:
            bool: True if the test fails as expected (bug confirmed).
        """
        result = self.run_test(test)
        # For bug reproduction, we expect the test to FAIL
        bug_confirmed = not result.success
        logger.info(
            "Bug reproduction verification",
            bug_confirmed=bug_confirmed,
            test=test.test_method_name,
        )
        return bug_confirmed

    def verify_fix(self, test: GeneratedTest) -> bool:
        """Verify that a fix makes the test pass.

        Args:
            test: The regression test to verify.

        Returns:
            bool: True if the test passes (fix confirmed).
        """
        result = self.run_test(test)
        logger.info(
            "Fix verification",
            fix_works=result.success,
            test=test.test_method_name,
        )
        return result.success

    def _extract_error(self, output: str) -> str | None:
        """Extract error message from Maven output.

        Args:
            output: Maven test output.

        Returns:
            str | None: Extracted error message or None.
        """
        lines = output.split("\n")
        error_lines = []
        capture = False

        for line in lines:
            if "FAILURE" in line or "ERROR" in line or "AssertionError" in line:
                capture = True
            if capture:
                error_lines.append(line)
                if len(error_lines) >= 20:
                    break

        return "\n".join(error_lines) if error_lines else None
