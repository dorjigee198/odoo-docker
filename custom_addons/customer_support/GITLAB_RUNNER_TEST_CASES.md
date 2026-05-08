# GitLab Runner CI Test Cases - Customer Support Module

Date: 2026-04-27
Target: `custom_addons/customer_support`
Purpose: Define CI/CD test coverage for GitLab Runner and provide a baseline `.gitlab-ci.yml` implementation.

## CI Objectives

1. Block insecure or broken code from merging.
2. Validate Python/XML quality and addon import integrity.
3. Run Odoo module tests in a reproducible runner environment.
4. Provide controlled deployment from GitLab main branch.

## Implemented Pipeline Stages

1. Static checks (fast fail)
2. Security checks (SAST-lite)
3. Optional Odoo module test execution
4. Manual production deployment

Pipeline file: `.gitlab-ci.yml`

## Test Case Matrix

### Stage 1: Static Quality

TC-001 Manifest sanity
- Goal: Ensure addon metadata is valid.
- Job: `manifest_sanity`
- Command:
  - `python -m py_compile __manifest__.py`
- Pass criteria: job exits 0.

TC-002 Python syntax compile
- Goal: Catch syntax errors early.
- Job: `python_compile`
- Command:
  - `find . -name "*.py" -print0 | xargs -0 -n1 python -m py_compile`
- Pass criteria: all files compile.

TC-003 XML parse validation
- Goal: Catch malformed XML views/templates/data.
- Job: `xml_parse_validation`
- Command:
  - `xmllint --noout $(find . -name "*.xml")`
- Pass criteria: no XML parse errors.

TC-004 Ruff lint baseline
- Goal: Enforce minimum style and common bug checks.
- Job: `ruff_lint`
- Command:
  - `ruff check .`
- Pass criteria: no lint errors (or only approved baseline).

### Stage 2: Security Baseline

TC-005 Detect CSRF-disabled routes
- Goal: Prevent accidental growth of CSRF attack surface.
- Job: `csrf_disabled_scan`
- Command:
  - `rg -n "csrf=False" controllers`
- Pass criteria: count does not increase versus approved baseline.

TC-006 Detect broad sudo usage in controllers
- Goal: Track ACL bypass risk hotspots.
- Job: `controller_sudo_scan`
- Command:
  - `rg -n "\.sudo\(" controllers`
- Pass criteria: no new unsafe usage without review note.

TC-007 Detect raw redirects
- Goal: Catch weak redirect logic.
- Job: `redirect_logic_scan`
- Command:
  - `rg -n "redirect_to|safe_redirect|startswith\(" controllers`
- Pass criteria: new redirect logic must include strict allowlist validation.

### Stage 3: Odoo Automated Tests (toggle with variable)

TC-101 Module install smoke
- Job: `odoo_module_install_smoke`
- Condition: `RUN_ODOO_TESTS=1`
- Expected: module installs successfully in CI DB.

TC-102 Module update smoke
- Job: `odoo_module_update_smoke`
- Condition: `RUN_ODOO_TESTS=1`
- Expected: module upgrade runs cleanly.

### Stage 4: Deployment

TC-201 Manual deploy from main branch
- Job: `deploy_customer_support`
- Condition: branch is `main`, manual trigger.
- Expected:
  - Sync addon files to target host/path.
  - Optional remote restart/command runs successfully.

## Required GitLab CI/CD Variables

Set these in GitLab project CI/CD settings:

1. `DEPLOY_SSH_PRIVATE_KEY` (masked, protected)
2. `DEPLOY_HOST` (protected)
3. `DEPLOY_USER` (protected)
4. `DEPLOY_PATH` (protected)
5. `DEPLOY_SSH_KNOWN_HOSTS` (optional but recommended)
6. `REMOTE_POST_DEPLOY_COMMAND` (optional, e.g. service restart)
7. `RUN_ODOO_TESTS` (optional; set to `1` to enable Odoo smoke jobs)

## Definition of Done

1. `.gitlab-ci.yml` runs on merge requests and main branch pushes.
2. Static checks fail merge requests on syntax/lint/XML issues.
3. Security scans provide visibility on CSRF/sudo/redirect hotspots.
4. Deployment is manually triggerable from main with protected variables.
