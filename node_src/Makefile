# Ethoscope Node Server Build System
# Handles both Python backend and frontend installation

.PHONY: install-all install-dev install-production install build dev clean help

# Default target - complete installation
all: install-all

# Complete installation (backend + frontend)
install-all:
	@echo "Installing Python backend package..."
	pip install .
	@echo "Installing npm dependencies..."
	npm install
	@echo "Building frontend assets..."
	npm run build
	@echo "✓ Complete installation finished"

# Development installation (editable Python package)
install-dev:
	@echo "Installing Python backend package in development mode..."
	pip install -e .
	@echo "Installing npm dependencies..."
	npm install
	@echo "Building frontend assets..."
	npm run build
	@echo "✓ Development installation finished"

# Production installation (optimized)
install-production:
	@echo "Installing Python backend package (production)..."
	pip install . --no-deps
	@echo "Installing npm dependencies..."
	npm install --production
	@echo "Building frontend assets..."
	npm run build
	@echo "✓ Production installation finished"

# Install npm dependencies only
install:
	@echo "Installing npm dependencies..."
	npm install

# Build production assets
build: install
	@echo "Building production assets..."
	npm run build

# Development mode with file watching
dev: install
	@echo "Starting development mode with file watching..."
	npm run dev

# Clean build artifacts and dependencies
clean:
	@echo "Cleaning build artifacts and dependencies..."
	rm -rf node_modules/
	rm -rf static/dist/
	rm -rf build/
	rm -rf *.egg-info/

# Show available targets
help:
	@echo "Available targets:"
	@echo "  install-all        - Install both Python backend and frontend (recommended)"
	@echo "  install-dev        - Install in development mode (editable Python package)"
	@echo "  install-production - Install for production deployment"
	@echo "  install            - Install npm dependencies only"
	@echo "  build              - Build frontend assets"
	@echo "  dev                - Start development mode with file watching"
	@echo "  clean              - Clean build artifacts and dependencies"
	@echo "  help               - Show this help message"