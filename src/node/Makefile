# Ethoscope Node Server Build System
# Handles Python backend installation (frontend is now source-only)

.PHONY: install-all install-dev install-production test test-unit test-integration test-functional test-coverage clean help

# Default target - complete installation
all: install-all

# Complete installation (backend only - frontend is source-only)
install-all:
	@echo "Installing Python backend package..."
	pip install .
	@echo "✓ Installation finished"

# Development installation (editable Python package)
install-dev:
	@echo "Installing Python backend package in development mode..."
	pip install -e .
	@echo "✓ Development installation finished"

# Production installation
install-production:
	@echo "Installing Python backend package (production)..."
	pip install . --no-deps
	@echo "✓ Production installation finished"

# Testing commands
test:
	@echo "Running all tests..."
	pytest tests/

test-unit:
	@echo "Running unit tests..."
	pytest tests/unit/ -v

test-integration:
	@echo "Running integration tests..."
	pytest tests/integration/ -v

test-functional:
	@echo "Running functional tests..."
	pytest tests/functional/ -v

test-coverage:
	@echo "Running tests with coverage report..."
	pytest tests/ --cov=ethoscope_node --cov-report=html --cov-report=term-missing

test-fast:
	@echo "Running fast tests (excluding slow tests)..."
	pytest tests/ -m "not slow"

test-slow:
	@echo "Running slow tests only..."
	pytest tests/ -m "slow"

# Clean build artifacts
clean:
	@echo "Cleaning build artifacts..."
	rm -rf build/
	rm -rf *.egg-info/
	rm -rf htmlcov/
	rm -rf .coverage
	rm -rf .pytest_cache/
	rm -rf tests/__pycache__/
	rm -rf tests/*/__pycache__/

# Show available targets
help:
	@echo "Available targets:"
	@echo "  install-all        - Install Python backend (recommended)"
	@echo "  install-dev        - Install in development mode (editable Python package)"
	@echo "  install-production - Install for production deployment"
	@echo "  test               - Run all tests"
	@echo "  test-unit          - Run unit tests only"
	@echo "  test-integration   - Run integration tests only"
	@echo "  test-functional    - Run functional tests only"
	@echo "  test-coverage      - Run tests with coverage report"
	@echo "  test-fast          - Run fast tests (excluding slow tests)"
	@echo "  test-slow          - Run slow tests only"
	@echo "  clean              - Clean build artifacts and test cache"
	@echo "  help               - Show this help message"
	@echo ""
	@echo "Note: Frontend is now source-only (no build step required)"
