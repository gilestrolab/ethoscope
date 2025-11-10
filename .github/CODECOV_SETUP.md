# Codecov Setup Guide

## Your Codecov Token

**Token:** `0690a06c-2270-4ed1-8d6d-003d518ecf77`

This token allows the CI/CD pipeline to upload coverage reports to Codecov for tracking and visualization.

---

## Adding the Token to GitHub

### Step 1: Navigate to Repository Settings

1. Go to: https://github.com/gilestrolab/ethoscope
2. Click **Settings** (top right, requires admin access)
3. In the left sidebar, click **Secrets and variables** → **Actions**

### Step 2: Add Repository Secret

1. Click **New repository secret**
2. Fill in the form:
   - **Name:** `CODECOV_TOKEN`
   - **Secret:** `0690a06c-2270-4ed1-8d6d-003d518ecf77`
3. Click **Add secret**

### Step 3: Verify Secret is Added

You should see `CODECOV_TOKEN` listed under "Repository secrets" with a green checkmark.

---

## What This Enables

Once the secret is added, the CI workflow (`.github/workflows/ci.yml`) will automatically:

✅ **Upload Device Coverage:**
- File: `src/ethoscope/coverage-device.xml`
- Flag: `device`
- Coverage for ethoscope device package

✅ **Upload Node Coverage:**
- File: `src/node/coverage-node.xml`
- Flag: `node`
- Coverage for ethoscope_node package

✅ **Codecov Features:**
- Coverage reports on every PR
- Coverage diff showing changes
- Coverage trends over time
- Interactive coverage browser
- Automatic PR comments with coverage info

---

## Verifying It Works

### After Adding the Secret

1. **Trigger a workflow run:**
   ```bash
   # Make a small change and push
   git commit --allow-empty -m "test: Trigger CI to verify Codecov"
   git push origin dev
   ```

2. **Check the workflow run:**
   - Go to: https://github.com/gilestrolab/ethoscope/actions
   - Click on the latest "CI" workflow run
   - Look for the "Coverage Report" job
   - Check the "Upload device coverage to Codecov" step
   - Should show: ✅ Coverage uploaded successfully

3. **View coverage on Codecov:**
   - Go to: https://codecov.io/gh/gilestrolab/ethoscope
   - You should see coverage reports with two flags: `device` and `node`
   - Coverage graphs and trends will appear

### Expected Output

When working correctly, you'll see in the workflow logs:

```
[2024-xx-xx] Uploading coverage reports...
==> Codecov CI detected.
==> Uploading reports to Codecov
    View upload reports at: https://app.codecov.io/gh/gilestrolab/ethoscope
    Upload successful!
```

---

## Codecov Badge

The README.md already includes the Codecov badge:

```markdown
[![codecov](https://codecov.io/gh/gilestrolab/ethoscope/branch/dev/graph/badge.svg)](https://codecov.io/gh/gilestrolab/ethoscope)
```

This badge will:
- Show current coverage percentage
- Update automatically after each push
- Link to the full coverage report

---

## Troubleshooting

### Secret Not Working

**Symptom:** Workflow fails with "Error: Codecov token not found"

**Solution:**
1. Verify secret name is exactly `CODECOV_TOKEN` (case-sensitive)
2. Check you have admin access to the repository
3. Try re-creating the secret

### Coverage Not Uploading

**Symptom:** Workflow succeeds but coverage doesn't appear on Codecov

**Solution:**
1. Check that tests are generating coverage files:
   - `src/ethoscope/coverage-device.xml`
   - `src/node/coverage-node.xml`
2. Verify the files are in the correct location
3. Check Codecov logs for upload errors

### Token Expired

**Symptom:** "Invalid token" error in workflow

**Solution:**
1. Generate a new token on Codecov
2. Update the GitHub secret with the new token

---

## Alternative: Tokenless Upload (GitHub Actions Only)

If you prefer not to use a token, Codecov supports tokenless uploads for public repositories:

**To enable:**
1. Remove the `token: ${{ secrets.CODECOV_TOKEN }}` lines from `.github/workflows/ci.yml`
2. Codecov will automatically authenticate using GitHub Actions OIDC

**However, using a token is recommended because:**
- More reliable authentication
- Works for private repositories
- Better security control
- Consistent across all CI providers

---

## Configuration Files

The Codecov integration is configured in:

**Workflow file:** `.github/workflows/ci.yml`
```yaml
- name: Upload device coverage to Codecov
  uses: codecov/codecov-action@v4
  with:
    file: ./src/ethoscope/coverage-device.xml
    flags: device
    name: device-coverage
    fail_ci_if_error: false
    token: ${{ secrets.CODECOV_TOKEN }}
```

**Optional:** Create `codecov.yml` in repository root for advanced configuration:
```yaml
coverage:
  status:
    project:
      default:
        target: 70%
        threshold: 1%
    patch:
      default:
        target: 80%

comment:
  layout: "reach, diff, files"
  behavior: default

flags:
  device:
    paths:
      - src/ethoscope/
  node:
    paths:
      - src/node/
```

---

## Next Steps

1. ✅ Add `CODECOV_TOKEN` secret to GitHub
2. ✅ Push a commit to trigger CI
3. ✅ Verify coverage uploads successfully
4. ✅ Check Codecov dashboard at https://codecov.io/gh/gilestrolab/ethoscope
5. ✅ Configure coverage thresholds (optional)
6. ✅ Enable PR comments (optional)

---

## Quick Command Reference

```bash
# Test coverage locally
python run_tests.py --coverage

# View local coverage report
cd src/ethoscope && open htmlcov-device/index.html
cd src/node && open htmlcov-node/index.html

# Trigger CI manually
git commit --allow-empty -m "test: Trigger CI"
git push origin dev

# Check workflow status
gh run list --workflow=ci.yml
gh run watch
```

---

## Support

- **Codecov Dashboard:** https://codecov.io/gh/gilestrolab/ethoscope
- **Codecov Docs:** https://docs.codecov.com/docs
- **GitHub Actions Logs:** https://github.com/gilestrolab/ethoscope/actions
- **Issues:** https://github.com/gilestrolab/ethoscope/issues

For any issues with Codecov integration, check the workflow logs first, then consult the Codecov documentation.
