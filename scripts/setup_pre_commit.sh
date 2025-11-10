#!/bin/bash
# Setup script for pre-commit hooks in Ethoscope project
# This script installs and configures pre-commit for development

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "========================================"
echo "Ethoscope Pre-Commit Setup"
echo "========================================"
echo ""

cd "$PROJECT_ROOT"

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is not installed or not in PATH"
    exit 1
fi

echo "✓ Python 3 found: $(python3 --version)"

# Check if we're in a venv
if [ -z "$VIRTUAL_ENV" ]; then
    echo ""
    echo "⚠ Warning: Not in a virtual environment"
    echo "  It's recommended to activate your venv first:"
    echo "  source .venv/bin/activate"
    echo ""
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Install pre-commit
echo ""
echo "Installing pre-commit..."
pip install pre-commit

# Install the git hook scripts
echo ""
echo "Installing pre-commit hooks..."
pre-commit install
pre-commit install --hook-type commit-msg
pre-commit install --hook-type pre-push

# Update hook versions
echo ""
echo "Updating hook repositories..."
pre-commit autoupdate || echo "⚠ Autoupdate failed, continuing with existing versions"

# Create secrets baseline if it doesn't exist
if [ ! -f .secrets.baseline ]; then
    echo ""
    echo "Creating secrets baseline..."
    if command -v detect-secrets &> /dev/null; then
        detect-secrets scan > .secrets.baseline || echo '{"version": "1.4.0", "filters_used": [], "results": {}}' > .secrets.baseline
    else
        echo '{"version": "1.4.0", "filters_used": [], "results": {}}' > .secrets.baseline
        echo "⚠ detect-secrets not installed, created empty baseline"
    fi
fi

# Optional: Run on all files to check current state
echo ""
echo "========================================"
echo "Testing pre-commit on existing files..."
echo "========================================"
echo ""
read -p "Run pre-commit on all files now? This may make changes. (y/N) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo ""
    echo "Running pre-commit on all files..."
    pre-commit run --all-files || {
        echo ""
        echo "⚠ Some checks failed. This is normal for an existing codebase."
        echo "  Review the changes and fix any issues before committing."
    }
fi

echo ""
echo "========================================"
echo "✓ Pre-commit setup complete!"
echo "========================================"
echo ""
echo "Usage:"
echo "  • Hooks will run automatically on 'git commit'"
echo "  • Run manually: pre-commit run --all-files"
echo "  • Run on staged files: pre-commit run"
echo "  • Run specific hook: pre-commit run <hook-id>"
echo "  • Skip hooks: git commit --no-verify"
echo ""
echo "Manual-only hooks (run with --hook-stage manual):"
echo "  • python-import-check: Check that imports work"
echo "  • critical-tests: Run tests for critical file changes"
echo "  • update-copyright: Update copyright years"
echo ""
echo "Configuration: .pre-commit-config.yaml"
echo "Documentation: .github/CICD.md"
echo ""
