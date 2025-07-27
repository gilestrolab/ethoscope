#!/usr/bin/env python3
"""
Test runner for backup system tests.

Runs comprehensive tests for the backup system including:
- Unit tests for backup helpers and cache system
- Integration tests for backup API
- Performance tests for cache optimization
- Primary key backup functionality tests
"""

import sys
import os
import unittest
import time
import argparse

# Add the source paths for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'ethoscope_node'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

def run_test_suite(test_type='all', verbose=False):
    """
    Run backup system test suite.
    
    Args:
        test_type: Type of tests to run ('unit', 'integration', 'performance', 'all')
        verbose: Enable verbose output
    """
    print("=" * 70)
    print("ETHOSCOPE BACKUP SYSTEM TEST SUITE")
    print("=" * 70)
    
    # Configure test discovery
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Test directories
    test_dir = os.path.dirname(__file__)
    unit_test_dir = os.path.join(test_dir, '..', '..', 'unit')
    integration_test_dir = os.path.join(test_dir, '..')
    
    test_results = {}
    
    if test_type in ['unit', 'all']:
        print("\n" + "=" * 50)
        print("RUNNING UNIT TESTS")
        print("=" * 50)
        
        # Unit tests
        unit_suite = unittest.TestSuite()
        try:
            from unit.test_backup_helpers import (
                TestVideoCacheSystem,
                TestBytesFormatting,
                TestRsyncEnhancement,
                TestDeviceBackupInfo,
                TestCachePerformance
            )
            
            unit_classes = [
                TestVideoCacheSystem,
                TestBytesFormatting,
                TestRsyncEnhancement,
                TestDeviceBackupInfo,
                TestCachePerformance
            ]
            
            for test_class in unit_classes:
                tests = loader.loadTestsFromTestCase(test_class)
                unit_suite.addTests(tests)
            
            # Run unit tests
            runner = unittest.TextTestRunner(verbosity=2 if verbose else 1)
            start_time = time.time()
            unit_result = runner.run(unit_suite)
            unit_time = time.time() - start_time
            
            test_results['unit'] = {
                'passed': unit_result.wasSuccessful(),
                'tests_run': unit_result.testsRun,
                'failures': len(unit_result.failures),
                'errors': len(unit_result.errors),
                'time': unit_time
            }
            
        except ImportError as e:
            print(f"Warning: Could not import unit tests: {e}")
            test_results['unit'] = {'passed': False, 'error': str(e)}
    
    if test_type in ['integration', 'all']:
        print("\n" + "=" * 50)
        print("RUNNING INTEGRATION TESTS")
        print("=" * 50)
        
        # Integration tests
        integration_suite = unittest.TestSuite()
        try:
            from test_backup_api_integration import (
                TestBackupAPIIntegration,
                TestBackupAPIErrorHandling
            )
            
            integration_classes = [
                TestBackupAPIIntegration,
                TestBackupAPIErrorHandling
            ]
            
            for test_class in integration_classes:
                tests = loader.loadTestsFromTestCase(test_class)
                integration_suite.addTests(tests)
            
            # Run integration tests
            runner = unittest.TextTestRunner(verbosity=2 if verbose else 1)
            start_time = time.time()
            integration_result = runner.run(integration_suite)
            integration_time = time.time() - start_time
            
            test_results['integration'] = {
                'passed': integration_result.wasSuccessful(),
                'tests_run': integration_result.testsRun,
                'failures': len(integration_result.failures),
                'errors': len(integration_result.errors),
                'time': integration_time
            }
            
        except ImportError as e:
            print(f"Warning: Could not import integration tests: {e}")
            test_results['integration'] = {'passed': False, 'error': str(e)}
    
    if test_type in ['performance', 'all']:
        print("\n" + "=" * 50)
        print("RUNNING PERFORMANCE TESTS")
        print("=" * 50)
        
        # Performance tests
        performance_suite = unittest.TestSuite()
        try:
            from test_backup_cache_performance import (
                TestCachePerformanceRealistic,
                TestCacheRobustness
            )
            
            performance_classes = [
                TestCachePerformanceRealistic,
                TestCacheRobustness
            ]
            
            for test_class in performance_classes:
                tests = loader.loadTestsFromTestCase(test_class)
                performance_suite.addTests(tests)
            
            # Run performance tests
            runner = unittest.TextTestRunner(verbosity=2 if verbose else 1, buffer=False)
            start_time = time.time()
            performance_result = runner.run(performance_suite)
            performance_time = time.time() - start_time
            
            test_results['performance'] = {
                'passed': performance_result.wasSuccessful(),
                'tests_run': performance_result.testsRun,
                'failures': len(performance_result.failures),
                'errors': len(performance_result.errors),
                'time': performance_time
            }
            
        except ImportError as e:
            print(f"Warning: Could not import performance tests: {e}")
            test_results['performance'] = {'passed': False, 'error': str(e)}
    
    # Print summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    
    total_tests = 0
    total_failures = 0
    total_errors = 0
    total_time = 0
    all_passed = True
    
    for test_category, results in test_results.items():
        if 'error' in results:
            print(f"{test_category.upper()}: IMPORT ERROR - {results['error']}")
            all_passed = False
        else:
            status = "PASSED" if results['passed'] else "FAILED"
            print(f"{test_category.upper()}: {status}")
            print(f"  Tests run: {results['tests_run']}")
            print(f"  Failures: {results['failures']}")
            print(f"  Errors: {results['errors']}")
            print(f"  Time: {results['time']:.2f}s")
            
            total_tests += results['tests_run']
            total_failures += results['failures']
            total_errors += results['errors']
            total_time += results['time']
            
            if not results['passed']:
                all_passed = False
    
    print("\n" + "-" * 50)
    print(f"TOTAL: {total_tests} tests, {total_failures} failures, {total_errors} errors")
    print(f"Total time: {total_time:.2f}s")
    print(f"Overall result: {'PASSED' if all_passed else 'FAILED'}")
    print("=" * 70)
    
    return all_passed


def main():
    """Main test runner function."""
    parser = argparse.ArgumentParser(description='Run backup system tests')
    parser.add_argument('--type', choices=['unit', 'integration', 'performance', 'all'], 
                       default='all', help='Type of tests to run')
    parser.add_argument('--verbose', '-v', action='store_true', 
                       help='Enable verbose output')
    parser.add_argument('--quick', action='store_true',
                       help='Run only fast tests (skip performance tests)')
    
    args = parser.parse_args()
    
    # Adjust test type based on quick flag
    if args.quick and args.type == 'all':
        test_type = 'unit'
        print("Quick mode: Running only unit tests")
    elif args.quick and args.type == 'performance':
        print("Quick mode: Skipping performance tests")
        return True
    else:
        test_type = args.type
    
    success = run_test_suite(test_type=test_type, verbose=args.verbose)
    
    # Exit with appropriate code
    return success


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)