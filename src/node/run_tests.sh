#!/usr/bin/env bash

# Run all tests for the ethoscope node package
# This script runs unit tests, integration tests, functional tests, and generates coverage reports

set -e  # Exit on any error

echo "Running Ethoscope Node Package Tests"
echo "===================================="

# Change to the node package directory
cd "$(dirname "$0")"

# Check if pytest is available
if ! command -v pytest &> /dev/null; then
    echo "Error: pytest is not installed. Please install test dependencies:"
    echo "  pip install -r ../../test-requirements.txt"
    exit 1
fi

# Check if tests directory exists
if [ ! -d "tests" ]; then
    echo "Error: tests directory not found. Please ensure the test structure is set up."
    exit 1
fi

# Run unit tests
if [ -d "tests/unit" ]; then
    echo "Running unit tests..."
    python -m pytest tests/unit/ -v --tb=short
fi

# Run integration tests
if [ -d "tests/integration" ]; then
    echo "Running integration tests..."
    python -m pytest tests/integration/ -v --tb=short
fi

# Run functional tests
if [ -d "tests/functional" ]; then
    echo "Running functional tests..."
    python -m pytest tests/functional/ -v --tb=short
fi

# Run all tests with coverage
echo "Running all tests with coverage..."
python -m pytest tests/ \
    --cov=ethoscope_node \
    --cov-report=html:htmlcov \
    --cov-report=xml:coverage.xml \
    --cov-report=term-missing \
    --tb=short

echo "Test run completed!"
echo "Coverage report generated in htmlcov/ directory"