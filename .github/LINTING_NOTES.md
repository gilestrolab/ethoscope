# Code Quality & Linting Notes

## Current Status

The CI/CD pipeline enforces code quality standards with some temporary exceptions for legacy code.

### Passing Standards

✅ **Device Package** (`src/ethoscope/`)
- Fully compliant with PEP8 and project standards
- No linting exceptions needed

### Legacy Code with Exceptions

⚠️ **Node API Files** (`src/node/ethoscope_node/api/`)
- These files have some linting issues that are temporarily ignored:
  - `E501`: Line too long (>88 characters)
  - `F401`: Unused imports
  - `F841`: Unused variables
  - `E722`: Bare except clauses
  - `F541`: f-string without placeholders
  - `F821`: Undefined names

**Reason for Exceptions:**
These files are legacy code that predates the current linting standards. Rather than block CI/CD while we refactor all legacy code, we've temporarily relaxed standards for these specific files while maintaining strict standards for new code.

## Gradual Improvement Strategy

### For New Code
✅ **All new code MUST pass full linting** (no exceptions)
- Use `black` for formatting
- Use `flake8` with no extra ignores
- Use `ruff` for additional checks
- Run pre-commit hooks before pushing

### For Existing Code
🔄 **When modifying legacy files:**
1. Fix linting issues in the lines you're changing
2. Consider fixing nearby issues if time permits
3. Don't feel obligated to fix the entire file in one go

### Pre-Commit Hooks
The pre-commit hooks are configured to:
- ✅ Auto-format with `black` and `isort`
- ✅ Catch new linting violations
- ⚠️ Temporarily exclude legacy API files from strict flake8 checks

## How Pre-Commit Catches CI Failures

### System Dependencies
**Issue:** CI needs `libcap-dev` for `python-prctl` (dependency of `picamera2`)

**Pre-commit protection:**
- The `python-import-check` hook (manual stage) will catch import failures
- Run it before pushing: `pre-commit run python-import-check --all-files --hook-stage manual`

**To test locally:**
```bash
# Install system dependency
sudo pacman -S libcap  # or apt-get install libcap-dev

# Then test imports
pre-commit run python-import-check --all-files --hook-stage manual
```

### Code Quality Issues
**Issue:** Linting errors (trailing whitespace, unused imports, etc.)

**Pre-commit protection:**
- `black`: Auto-formats code
- `isort`: Sorts imports
- `flake8`: Catches linting violations
- `ruff`: Modern linter with auto-fix
- `trailing-whitespace`: Removes trailing whitespace

**Auto-fix before commit:**
```bash
# Run all hooks
pre-commit run --all-files

# Or just formatting
pre-commit run black --all-files
pre-commit run isort --all-files
```

## Development Workflow

### Before Committing

1. **Run pre-commit hooks:**
   ```bash
   pre-commit run --all-files
   ```

2. **Check what changed:**
   ```bash
   git diff
   ```

3. **If testing imports (optional but recommended):**
   ```bash
   pre-commit run python-import-check --all-files --hook-stage manual
   ```

### Before Pushing

1. **Run full local CI simulation:**
   ```bash
   # Test both packages
   python run_tests.py

   # With coverage
   python run_tests.py --coverage
   ```

2. **Check for security issues:**
   ```bash
   pre-commit run bandit --all-files
   pre-commit run detect-secrets --all-files
   ```

## Future Cleanup

### TODO: Gradually Fix Legacy API Files

Track progress of cleaning up `src/node/ethoscope_node/api/`:

**Priority 1 (Easy Wins):**
- [ ] Remove unused imports (F401)
- [ ] Remove unused variables (F841)
- [ ] Add newlines at end of files (W292)
- [ ] Remove trailing whitespace (W293, W291)

**Priority 2 (Medium Effort):**
- [ ] Break long lines (E501)
- [ ] Replace f-strings without placeholders (F541)
- [ ] Replace bare except clauses (E722)

**Priority 3 (Needs Review):**
- [ ] Fix undefined names (F821) - requires code review

### How to Help

When working on any file in `src/node/ethoscope_node/api/`:
1. Run `black` on the file
2. Remove obvious unused imports
3. Fix issues in code you're modifying
4. Update this checklist

## Configuration Files

- **Pre-commit:** `.pre-commit-config.yaml`
- **GitHub Actions:** `.github/workflows/quality.yml`
- **Flake8 Config:** In `pyproject.toml` (both packages)

## Questions?

- Check `.github/CICD.md` for CI/CD documentation
- Check `CLAUDE.md` for pre-commit hook usage
- Open an issue if you find problems with the linting setup
