#!/usr/bin/env python3
"""
Comprehensive test runner for the Ethoscope project.

This script provides a unified interface for running tests across both
device and node packages with various options and configurations.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from typing import Dict
from typing import List
from typing import Optional


class TestRunner:
    """Main test runner class."""

    def __init__(self, project_root: Optional[Path] = None):
        """Initialize test runner."""
        self.project_root = project_root or Path(__file__).parent
        self.device_package = self.project_root / "src" / "ethoscope"
        self.node_package = self.project_root / "src" / "node"
        self.test_results = {}

    def run_command(self, cmd: List[str], cwd: Optional[Path] = None) -> Dict[str, Any]:
        """Run a command and return results."""
        start_time = time.time()

        try:
            result = subprocess.run(
                cmd,
                cwd=cwd or self.project_root,
                capture_output=True,
                text=True,
                timeout=1800,  # 30 minutes timeout
            )

            end_time = time.time()

            return {
                "command": " ".join(cmd),
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "duration": end_time - start_time,
                "success": result.returncode == 0,
            }

        except subprocess.TimeoutExpired:
            return {
                "command": " ".join(cmd),
                "returncode": -1,
                "stdout": "",
                "stderr": "Test timed out after 30 minutes",
                "duration": 1800,
                "success": False,
            }
        except Exception as e:
            return {
                "command": " ".join(cmd),
                "returncode": -1,
                "stdout": "",
                "stderr": str(e),
                "duration": 0,
                "success": False,
            }

    def run_device_tests(
        self, test_type: str = "all", verbose: bool = False
    ) -> Dict[str, Any]:
        """Run device package tests."""
        print(f"Running device package tests ({test_type})...")

        cmd = ["python", "-m", "pytest"]

        if test_type == "unit":
            cmd.extend(["ethoscope/tests/unittests/"])
        elif test_type == "integration":
            cmd.extend(["ethoscope/tests/integration_api_tests/"])
        elif test_type == "all":
            cmd.extend(["ethoscope/tests/"])
        else:
            cmd.extend([f"ethoscope/tests/{test_type}/"])

        if verbose:
            cmd.append("-v")

        cmd.extend(["--tb=short", "--strict-markers", "--strict-config"])

        return self.run_command(cmd, cwd=self.device_package)

    def run_node_tests(
        self, test_type: str = "all", verbose: bool = False
    ) -> Dict[str, Any]:
        """Run node package tests."""
        print(f"Running node package tests ({test_type})...")

        cmd = ["python", "-m", "pytest"]

        if test_type == "unit":
            cmd.extend(["tests/unit/"])
        elif test_type == "integration":
            cmd.extend(["tests/integration/"])
        elif test_type == "functional":
            cmd.extend(["tests/functional/"])
        elif test_type == "all":
            cmd.extend(["tests/"])
        else:
            cmd.extend([f"tests/{test_type}/"])

        if verbose:
            cmd.append("-v")

        cmd.extend(["--tb=short", "--strict-markers", "--strict-config"])

        return self.run_command(cmd, cwd=self.node_package)

    def run_coverage_tests(self, package: str = "both") -> Dict[str, Any]:
        """Run tests with coverage analysis."""
        print(f"Running coverage tests for {package}...")

        results = {}

        if package in ["both", "device"]:
            print("Running device package coverage...")
            cmd = [
                "python",
                "-m",
                "pytest",
                "ethoscope/tests/",
                "--cov=ethoscope",
                "--cov-report=html:htmlcov_device",
                "--cov-report=xml:coverage_device.xml",
                "--cov-report=term-missing",
            ]
            results["device"] = self.run_command(cmd, cwd=self.device_package)

        if package in ["both", "node"]:
            print("Running node package coverage...")
            cmd = [
                "python",
                "-m",
                "pytest",
                "tests/",
                "--cov=ethoscope_node",
                "--cov-report=html:htmlcov_node",
                "--cov-report=xml:coverage_node.xml",
                "--cov-report=term-missing",
            ]
            results["node"] = self.run_command(cmd, cwd=self.node_package)

        return results

    def run_quality_checks(self) -> Dict[str, Any]:
        """Run code quality checks."""
        print("Running code quality checks...")

        results = {}

        # Run flake8 on device package
        print("Running flake8 on device package...")
        results["flake8_device"] = self.run_command(
            [
                "python",
                "-m",
                "flake8",
                "ethoscope/",
                "--max-line-length=88",
                "--extend-ignore=E203,W503",
            ],
            cwd=self.device_package,
        )

        # Run flake8 on node package
        print("Running flake8 on node package...")
        results["flake8_node"] = self.run_command(
            [
                "python",
                "-m",
                "flake8",
                "ethoscope_node/",
                "--max-line-length=88",
                "--extend-ignore=E203,W503",
            ],
            cwd=self.node_package,
        )

        # Run mypy on device package
        print("Running mypy on device package...")
        results["mypy_device"] = self.run_command(
            ["python", "-m", "mypy", "ethoscope/", "--ignore-missing-imports"],
            cwd=self.device_package,
        )

        # Run mypy on node package
        print("Running mypy on node package...")
        results["mypy_node"] = self.run_command(
            ["python", "-m", "mypy", "ethoscope_node/", "--ignore-missing-imports"],
            cwd=self.node_package,
        )

        return results

    def run_security_checks(self) -> Dict[str, Any]:
        """Run security checks."""
        print("Running security checks...")

        results = {}

        # Run bandit on device package
        print("Running bandit on device package...")
        results["bandit_device"] = self.run_command(
            ["python", "-m", "bandit", "-r", "ethoscope/", "-f", "json"],
            cwd=self.device_package,
        )

        # Run bandit on node package
        print("Running bandit on node package...")
        results["bandit_node"] = self.run_command(
            ["python", "-m", "bandit", "-r", "ethoscope_node/", "-f", "json"],
            cwd=self.node_package,
        )

        return results

    def generate_report(
        self, results: Dict[str, Any], output_file: Optional[Path] = None
    ) -> str:
        """Generate a test report."""
        report_lines = []
        report_lines.append("=" * 80)
        report_lines.append("ETHOSCOPE PROJECT TEST REPORT")
        report_lines.append("=" * 80)
        report_lines.append("")

        total_tests = 0
        passed_tests = 0
        failed_tests = 0
        total_duration = 0

        for test_name, result in results.items():
            if isinstance(result, dict) and "success" in result:
                report_lines.append(f"Test: {test_name}")
                report_lines.append(f"  Command: {result['command']}")
                report_lines.append(
                    f"  Status: {'PASSED' if result['success'] else 'FAILED'}"
                )
                report_lines.append(f"  Duration: {result['duration']:.2f}s")

                if result["success"]:
                    passed_tests += 1
                else:
                    failed_tests += 1
                    report_lines.append(f"  Error: {result['stderr']}")

                total_tests += 1
                total_duration += result["duration"]
                report_lines.append("")

        report_lines.append("-" * 80)
        report_lines.append("SUMMARY:")
        report_lines.append(f"  Total tests: {total_tests}")
        report_lines.append(f"  Passed: {passed_tests}")
        report_lines.append(f"  Failed: {failed_tests}")
        report_lines.append(
            f"  Success rate: {(passed_tests/total_tests*100):.1f}%"
            if total_tests > 0
            else "  Success rate: 0%"
        )
        report_lines.append(f"  Total duration: {total_duration:.2f}s")
        report_lines.append("=" * 80)

        report_content = "\n".join(report_lines)

        if output_file:
            with open(output_file, "w") as f:
                f.write(report_content)

        return report_content

    def run_all_tests(
        self,
        verbose: bool = False,
        coverage: bool = False,
        quality: bool = False,
        security: bool = False,
    ) -> Dict[str, Any]:
        """Run all tests with specified options."""
        print("Starting comprehensive test run...")

        results = {}

        # Run unit tests
        results["device_unit"] = self.run_device_tests("unit", verbose)
        results["node_unit"] = self.run_node_tests("unit", verbose)

        # Run integration tests
        results["device_integration"] = self.run_device_tests("integration", verbose)
        results["node_integration"] = self.run_node_tests("integration", verbose)

        # Run functional tests
        results["node_functional"] = self.run_node_tests("functional", verbose)

        # Run coverage if requested
        if coverage:
            coverage_results = self.run_coverage_tests("both")
            results.update(coverage_results)

        # Run quality checks if requested
        if quality:
            quality_results = self.run_quality_checks()
            results.update(quality_results)

        # Run security checks if requested
        if security:
            security_results = self.run_security_checks()
            results.update(security_results)

        return results


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Comprehensive test runner for the Ethoscope project",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--package",
        choices=["device", "node", "both"],
        default="both",
        help="Which package to test (default: both)",
    )

    parser.add_argument(
        "--type",
        choices=["unit", "integration", "functional", "all"],
        default="all",
        help="Type of tests to run (default: all)",
    )

    parser.add_argument(
        "--coverage", action="store_true", help="Run tests with coverage analysis"
    )

    parser.add_argument(
        "--quality", action="store_true", help="Run code quality checks (flake8, mypy)"
    )

    parser.add_argument(
        "--security", action="store_true", help="Run security checks (bandit)"
    )

    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    parser.add_argument("--output", "-o", type=Path, help="Output file for test report")

    args = parser.parse_args()

    runner = TestRunner()

    try:
        if args.package == "both" and args.type == "all":
            # Run comprehensive test suite
            results = runner.run_all_tests(
                verbose=args.verbose,
                coverage=args.coverage,
                quality=args.quality,
                security=args.security,
            )
        else:
            # Run specific tests
            results = {}

            if args.package in ["device", "both"]:
                results["device"] = runner.run_device_tests(args.type, args.verbose)

            if args.package in ["node", "both"]:
                results["node"] = runner.run_node_tests(args.type, args.verbose)

        # Generate and display report
        report = runner.generate_report(results, args.output)
        print(report)

        # Exit with appropriate code
        failed_tests = sum(
            1
            for r in results.values()
            if isinstance(r, dict) and not r.get("success", True)
        )
        sys.exit(0 if failed_tests == 0 else 1)

    except KeyboardInterrupt:
        print("\nTest run interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"Error running tests: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
