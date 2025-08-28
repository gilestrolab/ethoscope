#!/usr/bin/env python3
"""
Authentication System Test Runner

This script runs all authentication-related tests and provides a comprehensive
report on the authentication system's functionality.
"""

import sys
import subprocess
import os
from pathlib import Path


def run_test_suite(test_path, description):
    """Run a specific test suite and return the results."""
    print(f"\n{'='*60}")
    print(f"Running {description}")
    print(f"{'='*60}")
    
    try:
        result = subprocess.run([
            sys.executable, '-m', 'pytest', 
            test_path, 
            '-v', 
            '--tb=short'
        ], capture_output=True, text=True, cwd=Path(__file__).parent.parent)
        
        print(result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr)
        
        return result.returncode == 0
    except Exception as e:
        print(f"Error running tests: {e}")
        return False


def main():
    """Run all authentication tests."""
    print("Ethoscope Authentication System Test Suite")
    print("=" * 50)
    
    # Change to the node directory
    os.chdir(Path(__file__).parent.parent)
    
    # Activate virtual environment
    print("Activating virtual environment...")
    venv_activate = "../../.venv/bin/activate"
    if os.path.exists(venv_activate):
        subprocess.run(f"source {venv_activate}", shell=True)
    
    test_suites = [
        ("tests/unit/test_auth_system_simple.py", "Unit Tests - Authentication Core Logic"),
        ("tests/functional/test_frontend_auth.py", "Functional Tests - Frontend Authentication"),
    ]
    
    results = []
    
    for test_path, description in test_suites:
        if os.path.exists(test_path):
            success = run_test_suite(test_path, description)
            results.append((description, success))
        else:
            print(f"Warning: Test file {test_path} not found")
            results.append((description, False))
    
    # Print summary
    print(f"\n{'='*60}")
    print("TEST SUMMARY")
    print(f"{'='*60}")
    
    all_passed = True
    for description, success in results:
        status = "PASSED" if success else "FAILED"
        print(f"{description}: {status}")
        if not success:
            all_passed = False
    
    print(f"\nOverall Result: {'ALL TESTS PASSED' if all_passed else 'SOME TESTS FAILED'}")
    
    if all_passed:
        print("\n✅ Authentication system tests completed successfully!")
        print("\nThe authentication system includes:")
        print("- ✅ PIN hashing with bcrypt/PBKDF2 fallback")
        print("- ✅ Rate limiting and progressive lockout") 
        print("- ✅ Secure session management")
        print("- ✅ Authentication middleware and decorators")
        print("- ✅ Frontend login/logout functionality")
        print("- ✅ Admin access control")
        print("- ✅ Security best practices")
    else:
        print("\n❌ Some tests failed. Please review the output above.")
        
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())