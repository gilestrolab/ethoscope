#!/usr/bin/env python

"""
Test script for the enhanced notification system.
This script demonstrates the new notification functionality.
"""

import datetime
import json
import os
import sys

# Add the src directory to the path so we can import our modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from ethoscope_node.notifications.base import NotificationAnalyzer
from ethoscope_node.notifications.email import EmailNotificationService


def test_failure_analysis():
    """Test device failure analysis functionality."""
    print("Testing device failure analysis...")

    try:
        analyzer = NotificationAnalyzer()

        # Test with a dummy device ID
        test_device_id = "test_device_001"

        analysis = analyzer.analyze_device_failure(test_device_id)

        print(f"Analysis result for {test_device_id}:")
        print(json.dumps(analysis, indent=2, default=str))

        return True

    except Exception as e:
        print(f"Error in failure analysis test: {e}")
        return False


def test_email_service():
    """Test email notification service."""
    print("\nTesting email notification service...")

    try:
        email_service = EmailNotificationService()

        # Test configuration
        config_test = email_service.test_email_configuration()
        print(f"Email configuration test: {config_test}")

        # Test creating an enhanced alert (without actually sending it)
        print("\nTesting enhanced alert creation...")

        # Create a test alert by overriding the _send_email method to avoid actually sending
        class TestEmailService(EmailNotificationService):
            def _send_email(self, msg):
                print(f"Would send email with subject: {msg['Subject']}")
                print(f"To: {msg['To']}")
                print(
                    f"Has attachments: {len(msg.get_payload()) > 2}"
                )  # text, html, + attachments
                return True

        test_service = TestEmailService()

        # Test sending an enhanced alert
        result = test_service.send_device_stopped_alert(
            device_id="test_device_001",
            device_name="Test Ethoscope 001",
            run_id="test_run_123",
            last_seen=datetime.datetime.now(),
        )

        print(f"Enhanced alert test result: {result}")

        return True

    except Exception as e:
        print(f"Error in email service test: {e}")
        return False


def test_log_retrieval():
    """Test log retrieval functionality."""
    print("\nTesting log retrieval...")

    try:
        analyzer = NotificationAnalyzer()

        # Test with a dummy device ID
        test_device_id = "test_device_001"

        logs = analyzer.get_device_logs(test_device_id)

        if logs:
            print(f"Retrieved {len(logs)} characters of log data")
            print(f"First 200 characters: {logs[:200]}")
        else:
            print("No logs retrieved (expected for test device)")

        return True

    except Exception as e:
        print(f"Error in log retrieval test: {e}")
        return False


def main():
    """Run all tests."""
    print("=== Ethoscope Notification System Tests ===\n")

    tests = [
        ("Failure Analysis", test_failure_analysis),
        ("Email Service", test_email_service),
        ("Log Retrieval", test_log_retrieval),
    ]

    results = []

    for test_name, test_func in tests:
        print(f"\n{'='*50}")
        print(f"Running {test_name} test...")
        print("=" * 50)

        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"Test {test_name} failed with exception: {e}")
            results.append((test_name, False))

    print(f"\n{'='*50}")
    print("Test Results Summary:")
    print("=" * 50)

    for test_name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"{test_name}: {status}")

    passed = sum(1 for _, result in results if result)
    total = len(results)

    print(f"\nPassed: {passed}/{total} tests")

    if passed == total:
        print("All tests passed! ✓")
        return 0
    else:
        print("Some tests failed! ✗")
        return 1


if __name__ == "__main__":
    sys.exit(main())
