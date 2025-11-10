#!/bin/bash
# Test script to verify pre-commit hooks catch common CI failures
# This helps ensure pre-commit hooks prevent GitHub Actions failures

set -e

echo "=============================================="
echo "Testing Pre-Commit Hooks"
echo "=============================================="
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

# Check if pre-commit is installed
if ! command -v pre-commit &> /dev/null; then
    echo "❌ Error: pre-commit is not installed"
    echo "Run: pip install pre-commit && pre-commit install"
    exit 1
fi

echo "✓ pre-commit is installed"
echo ""

# Check if hooks are installed
if [ ! -f .git/hooks/pre-commit ]; then
    echo "⚠ Warning: pre-commit hooks not installed in git"
    echo "Installing hooks..."
    pre-commit install
    echo "✓ Hooks installed"
else
    echo "✓ Pre-commit hooks are installed in git"
fi

echo ""
echo "=============================================="
echo "Running All Pre-Commit Hooks"
echo "=============================================="
echo ""

# Run all hooks on all files
if pre-commit run --all-files; then
    echo ""
    echo "=============================================="
    echo "✅ All pre-commit hooks passed!"
    echo "=============================================="
    echo ""
    echo "Your code is ready to commit and push."
    echo "It should pass GitHub Actions CI/CD checks."
else
    echo ""
    echo "=============================================="
    echo "⚠ Some pre-commit hooks failed"
    echo "=============================================="
    echo ""
    echo "This is actually GOOD - pre-commit caught issues"
    echo "that would have failed in CI/CD!"
    echo ""
    echo "Next steps:"
    echo "1. Review the changes made by auto-fix hooks (black, isort, ruff)"
    echo "2. Fix any remaining issues manually"
    echo "3. Re-run: pre-commit run --all-files"
    echo "4. When all hooks pass, commit and push"
    echo ""
    exit 1
fi

echo ""
echo "=============================================="
echo "Running Manual Hooks (Import Check)"
echo "=============================================="
echo ""

# Test import checking (requires venv)
if [ -f .venv/bin/activate ]; then
    echo "Testing Python import check..."
    if pre-commit run python-import-check --all-files --hook-stage manual; then
        echo "✓ Import check passed"
    else
        echo "⚠ Import check failed - check for missing dependencies"
        exit 1
    fi
else
    echo "⚠ Skipping import check (no venv found at .venv/)"
    echo "  To enable: python -m venv .venv && source .venv/bin/activate"
fi

echo ""
echo "=============================================="
echo "✅ Pre-Commit Testing Complete!"
echo "=============================================="
echo ""
echo "Summary:"
echo "- All formatting hooks passed"
echo "- All linting hooks passed"
echo "- Import checks passed (if venv available)"
echo ""
echo "Your code will likely pass GitHub Actions CI/CD!"
echo ""
