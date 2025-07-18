# Ethoscope Device Package Build System
# Handles installation, testing, and documentation

.PHONY: install install-dev install-production test docs clean help

# Default target
all: install

# Standard installation with device dependencies
install:
	@echo "Installing ethoscope package with device dependencies..."
	pip install .[device]
	@echo "✓ Installation completed"

# Development installation (editable)
install-dev:
	@echo "Installing ethoscope package in development mode..."
	pip install -e .[device,dev]
	@echo "✓ Development installation completed"

# Production installation (optimized)
install-production:
	@echo "Installing ethoscope package for production..."
	pip install . --no-deps
	pip install -r requirements.txt
	@echo "✓ Production installation completed"

# Basic installation (minimal dependencies)
install-minimal:
	@echo "Installing ethoscope package with minimal dependencies..."
	pip install .
	@echo "✓ Minimal installation completed"

# Run all tests
test:
	@echo "Running ethoscope test suite..."
	python -m pytest ethoscope/tests/ -v
	@echo "✓ All tests completed"

# Run unit tests only
test-unit:
	@echo "Running unit tests..."
	python -m pytest ethoscope/tests/unittests/ -v

# Run integration tests only
test-integration:
	@echo "Running integration tests..."
	python -m pytest ethoscope/tests/integration_api_tests/ -v

# Generate documentation
docs:
	@echo "Generating documentation..."
	cd docs && make html
	@echo "✓ Documentation generated in docs/_build/html/"

# Clean build artifacts and cache
clean:
	@echo "Cleaning build artifacts..."
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf docs/_build/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	@echo "✓ Cleanup completed"

# Check package health
check:
	@echo "Checking package configuration..."
	python -m pip check
	python -c "import ethoscope; print('✓ Package imports successfully')"
	@echo "✓ Package health check completed"

# Show available targets
help:
	@echo "Available targets:"
	@echo "  install            - Install with device dependencies (recommended)"
	@echo "  install-dev        - Install in development mode with dev dependencies"
	@echo "  install-production - Install for production deployment"
	@echo "  install-minimal    - Install with minimal dependencies only"
	@echo "  test               - Run all tests"
	@echo "  test-unit          - Run unit tests only"
	@echo "  test-integration   - Run integration tests only"
	@echo "  docs               - Generate documentation"
	@echo "  clean              - Clean build artifacts and cache"
	@echo "  check              - Check package health and imports"
	@echo "  help               - Show this help message"