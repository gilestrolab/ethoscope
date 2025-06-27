# Ethoscope Node Frontend Build System
# Requires Node.js and npm to be installed

.PHONY: install build dev clean help

# Default target
all: install build

# Install npm dependencies
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

# Show available targets
help:
	@echo "Available targets:"
	@echo "  install - Install npm dependencies"
	@echo "  build   - Build production assets"
	@echo "  dev     - Start development mode with file watching"
	@echo "  clean   - Clean build artifacts and dependencies"
	@echo "  help    - Show this help message"