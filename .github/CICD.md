# CI/CD Pipeline Documentation

## Overview

The Ethoscope project uses GitHub Actions for continuous integration and continuous delivery. The pipeline consists of three main workflows that automatically test, validate, and release the software.

## Workflows

### 1. CI Workflow (`.github/workflows/ci.yml`)

**Purpose**: Automated testing across multiple Python versions

**Triggers**:
- Push to `dev` or `main` branches
- Pull requests targeting `dev` or `main`
- Manual workflow dispatch

**Jobs**:

#### `test-device`
- Tests the device package (`src/ethoscope`)
- Python versions: 3.8, 3.9, 3.10, 3.11, 3.12
- Runs unit and integration tests
- Uploads test results as artifacts

#### `test-node`
- Tests the node package (`src/node`)
- Python versions: 3.8, 3.9, 3.10, 3.11, 3.12
- Runs unit, integration, and functional tests
- Uploads test results as artifacts

#### `coverage`
- Generates code coverage reports for both packages
- Uploads coverage to Codecov (requires `CODECOV_TOKEN` secret)
- Uploads HTML coverage reports as artifacts

#### `test-comprehensive`
- Runs the project-wide test runner (`run_tests.py`)
- Comprehensive test suite with coverage
- Uses Python 3.11

**Features**:
- ✅ Matrix testing across Python versions
- ✅ Dependency caching for faster builds
- ✅ Coverage reporting
- ✅ Test result artifacts (30-day retention)

### 2. Code Quality Workflow (`.github/workflows/quality.yml`)

**Purpose**: Enforce code quality standards

**Triggers**:
- Pull requests
- Push to `dev` or `main` branches
- Manual workflow dispatch

**Jobs**:

#### `lint-device` & `lint-node`
- **flake8**: PEP8 style checking
- **ruff**: Fast Python linter
- **black**: Code formatting verification

#### `type-check-device` & `type-check-node`
- **mypy**: Static type checking
- Runs with strict type checking flags

#### `security-scan`
- **bandit**: Security vulnerability scanning
- Scans for common security issues
- Generates JSON reports (uploaded as artifacts)

#### `dependency-check`
- **pip-audit**: Dependency vulnerability scanning
- Checks for known vulnerabilities in dependencies
- Generates audit reports

**Features**:
- ✅ Comprehensive linting and formatting checks
- ✅ Type safety verification
- ✅ Security vulnerability detection
- ✅ Dependency security auditing
- ✅ GitHub annotations on PRs

### 3. Release Workflow (`.github/workflows/release.yml`)

**Purpose**: Automated release creation and package distribution

**Triggers**:
- Push of version tags (`v*.*.*`, e.g., `v1.0.0`)
- Manual workflow dispatch

**Jobs**:

#### `build`
- Builds wheel and source distributions for both packages
- Validates packages with `twine check`
- Uploads packages as artifacts (90-day retention)

#### `test-installation`
- Tests package installation across Python versions
- Verifies packages can be imported
- Ensures distribution quality

#### `create-release`
- Automatically generates changelog from git commits
- Creates GitHub release with version tag
- Attaches distribution packages to release
- Generates formatted release notes

#### `publish-pypi`
- **Currently disabled** (placeholder)
- Can be enabled for PyPI publishing
- Uses trusted publishing (OIDC)
- Requires PyPI environment configuration

**Features**:
- ✅ Automated changelog generation
- ✅ Multi-version installation testing
- ✅ GitHub release creation
- ✅ Package validation
- 🔄 PyPI publishing (ready to enable)

### 4. Docker Workflow (`.github/workflows/docker.yml`)

**Purpose**: Build and publish Docker images to GitHub Container Registry (GHCR)

**Triggers**:
- Push to `dev` or `main` branches
- Push of version tags (`v*.*.*`)
- Manual workflow dispatch

**Jobs**:

#### `build-node`
- Builds the ethoscope-node image from `Docker/node/node.dockerfile`
- Passes the branch/tag name as `ETHOSCOPE_BRANCH` build argument
- Pushes to `ghcr.io/gilestrolab/ethoscope-node`

#### `build-git-server`
- Builds the git daemon image from `Docker/node/git-server/git-daemon.dockerfile`
- Pushes to `ghcr.io/gilestrolab/ethoscope-git-server`

**Tagging Strategy**:
| Trigger | Tags |
|---------|------|
| Push to `dev` | `dev` |
| Push to `main` | `main`, `latest` |
| Tag `v1.2.3` | `v1.2.3`, `1.2.3`, `1.2`, `latest` |

**Features**:
- ✅ Automatic image publishing on push
- ✅ Semantic version tagging
- ✅ BuildKit layer caching via GitHub Actions cache
- ✅ No extra secrets required (uses `GITHUB_TOKEN`)

## Setup Instructions

### 1. Enable Workflows

The workflows will automatically run when:
- Code is pushed to `dev` or `main` branches
- Pull requests are opened or updated
- Version tags are pushed (for releases)

### 2. Configure Secrets

#### Codecov Integration (Required for Coverage Tracking)

**Your Codecov Token:** `0690a06c-2270-4ed1-8d6d-003d518ecf77`

To enable coverage tracking and reporting:

1. **Add the token to GitHub:**
   - Go to: https://github.com/gilestrolab/ethoscope/settings/secrets/actions
   - Click **New repository secret**
   - Name: `CODECOV_TOKEN`
   - Secret: `0690a06c-2270-4ed1-8d6d-003d518ecf77`
   - Click **Add secret**

2. **Verify it works:**
   ```bash
   # Trigger CI by pushing a commit
   git commit --allow-empty -m "test: Verify Codecov integration"
   git push origin dev

   # Check workflow status
   open https://github.com/gilestrolab/ethoscope/actions

   # View coverage reports
   open https://codecov.io/gh/gilestrolab/ethoscope
   ```

3. **Expected outcome:**
   - ✅ CI workflow uploads coverage without errors
   - ✅ Codecov badge in README shows coverage percentage
   - ✅ Coverage reports appear on Codecov dashboard
   - ✅ PR comments show coverage changes

**Documentation:** See `.github/CODECOV_SETUP.md` for detailed setup guide

**Quick Reference:** See `ADD_CODECOV_SECRET.txt` for one-page instructions

#### PyPI Publishing
To enable PyPI publishing:
1. Set up trusted publishing on PyPI
2. Configure the `pypi` environment in repository settings
3. Uncomment PyPI publishing steps in `release.yml`

### 3. Branch Protection Rules (Recommended)

Configure branch protection for `dev` and `main`:

1. Go to **Settings** → **Branches** → **Add rule**
2. Branch name pattern: `dev` or `main`
3. Enable:
   - ✅ Require pull request reviews before merging
   - ✅ Require status checks to pass before merging
   - ✅ Require branches to be up to date before merging
4. Required status checks:
   - `Test Device Package (Python 3.11)`
   - `Test Node Package (Python 3.11)`
   - `Lint Device Package`
   - `Lint Node Package`
   - `Security Scan`

## Usage

### Running Tests Locally

Before pushing, run tests locally:

```bash
# Run all tests
python run_tests.py

# Run with coverage
python run_tests.py --coverage

# Run specific package
python run_tests.py --package device
python run_tests.py --package node

# Run specific test type
python run_tests.py --type unit
python run_tests.py --type integration
```

### Code Quality Checks

Run quality checks locally:

```bash
# Linting
cd src/ethoscope && flake8 ethoscope/ --max-line-length=88 --extend-ignore=E203,W503
cd src/node && flake8 ethoscope_node/ --max-line-length=88 --extend-ignore=E203,W503

# Format code
cd src/ethoscope && black ethoscope/
cd src/node && black ethoscope_node/

# Type checking
cd src/ethoscope && mypy ethoscope/ --ignore-missing-imports
cd src/node && mypy ethoscope_node/ --ignore-missing-imports

# Security scan
cd src/ethoscope && bandit -r ethoscope/
cd src/node && bandit -r ethoscope_node/
```

### Creating a Release

1. Ensure all tests pass on `main` branch
2. Update version numbers in `pyproject.toml` files
3. Create and push a version tag:

```bash
git tag -a v1.0.0 -m "Release version 1.0.0"
git push origin v1.0.0
```

4. The release workflow will automatically:
   - Build packages
   - Test installation
   - Create GitHub release
   - Generate changelog

### Viewing Results

#### CI Status
- View workflow runs: https://github.com/gilestrolab/ethoscope/actions
- Check status badges in README.md
- Review PR checks before merging

#### Coverage Reports
- Download coverage HTML reports from workflow artifacts
- View coverage trends on Codecov (if configured)

#### Security Reports
- Download security scan reports from workflow artifacts
- Review security findings in Actions logs

## Workflow Badges

Add these badges to documentation:

```markdown
[![CI](https://github.com/gilestrolab/ethoscope/actions/workflows/ci.yml/badge.svg)](https://github.com/gilestrolab/ethoscope/actions/workflows/ci.yml)
[![Code Quality](https://github.com/gilestrolab/ethoscope/actions/workflows/quality.yml/badge.svg)](https://github.com/gilestrolab/ethoscope/actions/workflows/quality.yml)
```

## Maintenance

### Updating Dependencies
- Update Python versions in workflow matrices as needed
- Update action versions (checkout, setup-python, etc.)
- Review and update linting/testing tool versions

### Monitoring
- Review failed workflow runs regularly
- Address security findings from dependency scans
- Keep coverage levels above 70%

### Troubleshooting

#### Tests fail in CI but pass locally
- Check Python version (CI tests multiple versions)
- Verify dependencies are correctly specified
- Check for platform-specific issues

#### Coverage not uploading
- Verify `CODECOV_TOKEN` is set correctly
- Check Codecov service status
- Review workflow logs for errors

#### Release workflow fails
- Ensure version tag format is correct (`v*.*.*`)
- Check that packages build successfully
- Verify GitHub token permissions

## Best Practices

1. **Always run tests locally before pushing**
2. **Keep test coverage above 70%**
3. **Address linting issues before submitting PRs**
4. **Review security scan results**
5. **Write meaningful commit messages** (used in changelogs)
6. **Test across Python versions** when adding new features
7. **Update documentation** when changing workflows

## Next Steps

Consider adding:
- [ ] Automated dependency updates (Dependabot)
- [ ] Performance benchmarking
- [ ] Documentation building and deployment
- [x] Docker image building and publishing
- [ ] Slack/Discord notifications for failures
- [ ] Code coverage enforcement (fail below threshold)

## Support

For issues with CI/CD:
1. Check workflow logs in GitHub Actions
2. Review this documentation
3. Open an issue at https://github.com/gilestrolab/ethoscope/issues
