#!/usr/bin/env bash

# Run all tests for the ethoscope device package
# This script runs unit tests, integration tests, and generates coverage reports

set -e  # Exit on any error

echo "Running Ethoscope Device Package Tests"
echo "======================================"

# Change to the device package directory
cd "$(dirname "$0")/../../../"

# Check if pytest is available
if ! command -v pytest &> /dev/null; then
    echo "Error: pytest is not installed. Please install test dependencies:"
    echo "  pip install -r ../../../../test-requirements.txt"
    exit 1
fi

# Run unit tests
echo "Running unit tests..."
python -m pytest ethoscope/tests/unittests/ -v --tb=short

# Run integration tests
echo "Running integration tests..."
python -m pytest ethoscope/tests/integration_api_tests/ -v --tb=short

# Run all tests with coverage
echo "Running all tests with coverage..."
python -m pytest ethoscope/tests/ \
    --cov=ethoscope \
    --cov-report=html:htmlcov \
    --cov-report=xml:coverage.xml \
    --cov-report=term-missing \
    --tb=short

echo "Test run completed!"
echo "Coverage report generated in htmlcov/ directory"
