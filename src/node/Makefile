# Ethoscope Node Server Build System
# Handles Python backend installation (frontend is now source-only)

.PHONY: install-all install-dev install-production clean help

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

# Clean build artifacts
clean:
	@echo "Cleaning build artifacts..."
	rm -rf build/
	rm -rf *.egg-info/

# Show available targets
help:
	@echo "Available targets:"
	@echo "  install-all        - Install Python backend (recommended)"
	@echo "  install-dev        - Install in development mode (editable Python package)"
	@echo "  install-production - Install for production deployment"
	@echo "  clean              - Clean build artifacts"
	@echo "  help               - Show this help message"
	@echo ""
	@echo "Note: Frontend is now source-only (no build step required)"