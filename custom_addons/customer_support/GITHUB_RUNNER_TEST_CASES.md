# GitHub Runner CI Test Cases - Customer Support Module

Date: 2026-04-24
Target: `custom_addons/customer_support`
Purpose: Define CI test coverage for GitHub Actions (runner) before full CD rollout.

## CI Objectives

1. Block insecure or broken code from merging.
2. Validate Python/XML quality and addon import integrity.
3. Run Odoo module tests in a reproducible runner environment.
4. Surface regressions in authorization and CSRF behavior.

## Recommended Pipeline Stages

1. Static checks (fast fail)
2. Security checks (SAST-lite)
3. Odoo module test execution
4. Optional integration smoke tests

## Test Case Matrix

### Stage 1: Static Quality

TC-001 Manifest sanity
- Goal: Ensure addon metadata is valid.
- Command:
  - `python -m py_compile custom_addons/customer_support/__manifest__.py`
- Pass criteria: command exits 0.

TC-002 Python syntax compile
- Goal: Catch syntax errors early.
- Command:
  - `find custom_addons/customer_support -name "*.py" -print0 | xargs -0 -n1 python -m py_compile`
- Pass criteria: all files compile.

TC-003 XML parse validation
- Goal: Catch malformed XML views/templates/data.
- Command:
  - `xmllint --noout $(find custom_addons/customer_support -name "*.xml")`
- Pass criteria: no XML parse errors.

TC-004 Ruff lint baseline
- Goal: Enforce minimum style and common bug checks.
- Command:
  - `ruff check custom_addons/customer_support`
- Pass criteria: no lint errors (or only approved baseline).

### Stage 2: Security Baseline

TC-005 Detect CSRF-disabled routes
- Goal: Prevent accidental growth of CSRF attack surface.
- Command:
  - `rg -n "csrf=False" custom_addons/customer_support/controllers`
- Pass criteria: count does not increase versus approved baseline.

TC-006 Detect broad sudo usage in controllers
- Goal: Track ACL bypass risk hotspots.
- Command:
  - `rg -n "\.sudo\(" custom_addons/customer_support/controllers`
- Pass criteria: no new unsafe usage without review note.

TC-007 Detect raw redirects
- Goal: Catch weak redirect logic.
- Command:
  - `rg -n "redirect_to|safe_redirect|startswith\(" custom_addons/customer_support/controllers`
- Pass criteria: new redirect logic must include strict allowlist validation.

### Stage 3: Odoo Automated Tests (to be added under tests/)

TC-101 Authorization: cannot read others' ticket
- Type: HttpCase/TransactionCase
- Scenario:
  - Create customer A ticket.
  - Login as customer B.
  - Request `/customer_support/ticket/<id>`.
- Expected:
  - 302 to dashboard with error or 403; no ticket detail rendered.

TC-102 Authorization: customer can read own ticket only
- Scenario:
  - Create customer A ticket.
  - Login as customer A.
  - Open own ticket detail.
- Expected:
  - 200 and ticket content shown.

TC-103 CSRF enforced for password update
- Scenario:
  - POST `/customer_support/profile/update_password` without CSRF token.
- Expected:
  - Request rejected (4xx) once hardening is applied.

TC-104 CSRF enforced for picture update
- Scenario:
  - POST `/customer_support/profile/update_picture` without CSRF token.
- Expected:
  - Request rejected (4xx) once hardening is applied.

TC-105 Redirect allowlist
- Scenario:
  - POST login with suspicious redirect path.
- Expected:
  - Redirect falls back to role dashboard, not arbitrary path.

TC-106 Attachment visibility boundary
- Scenario:
  - User without ownership/admin role attempts to access ticket attachments via detail page.
- Expected:
  - No attachment tokens/records exposed.

TC-107 Customer messages visibility
- Scenario:
  - Internal-only message exists on a ticket.
  - Customer opens ticket detail.
- Expected:
  - Internal-only message is not returned/rendered.

TC-108 Knowledge upload rejects unsupported MIME
- Scenario:
  - Upload file with allowed extension but invalid MIME/content.
- Expected:
  - Validation fails with clear message.

TC-109 Public chatbot abuse guard (future)
- Scenario:
  - Burst requests to `/dragon-chat/message` from same source.
- Expected:
  - Rate-limit response after threshold.

TC-110 Password reset privacy
- Scenario:
  - Existing and non-existing login identifiers submitted.
- Expected:
  - Same user-facing response and no observable enumeration behavior.

### Stage 4: Regression and Packaging

TC-201 Module install smoke
- Goal: Ensure module installs cleanly in test DB.
- Command example:
  - `./odoo19/odoo-bin -c odoo19/odoo.conf -d ci_test_db -i customer_support --stop-after-init`
- Pass criteria: successful install.

TC-202 Module update smoke
- Goal: Ensure upgrade path remains valid.
- Command example:
  - `./odoo19/odoo-bin -c odoo19/odoo.conf -d ci_test_db -u customer_support --stop-after-init`
- Pass criteria: successful update.

## Suggested GitHub Actions Workflow (Blueprint)

```yaml
name: customer-support-ci

on:
  pull_request:
    paths:
      - "custom_addons/customer_support/**"
      - ".github/workflows/customer-support-ci.yml"
  push:
    branches: [main]

jobs:
  static-and-security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install tools
        run: |
          python -m pip install --upgrade pip
          pip install ruff
          sudo apt-get update
          sudo apt-get install -y libxml2-utils ripgrep

      - name: Manifest compile
        run: python -m py_compile custom_addons/customer_support/__manifest__.py

      - name: Python compile
        run: find custom_addons/customer_support -name "*.py" -print0 | xargs -0 -n1 python -m py_compile

      - name: XML lint
        run: xmllint --noout $(find custom_addons/customer_support -name "*.xml")

      - name: Ruff
        run: ruff check custom_addons/customer_support

      - name: CSRF scan
        run: rg -n "csrf=False" custom_addons/customer_support/controllers || true

      - name: sudo scan
        run: rg -n "\.sudo\(" custom_addons/customer_support/controllers || true

  odoo-tests:
    runs-on: ubuntu-latest
    needs: static-and-security
    steps:
      - uses: actions/checkout@v4
      - name: Placeholder
        run: |
          echo "Add Odoo runtime + DB service + --test-tags once tests are committed"
```

## Runner Implementation Notes

1. Add a dedicated `tests/` package under `custom_addons/customer_support` and map TC-101..TC-110 to real Odoo test classes.
2. Use deterministic seed data and isolated test DB per run.
3. Start with static/security gates first, then enable `odoo-tests` once base tests are green.
4. Store secrets in GitHub Actions secrets and avoid printing sensitive values in logs.

## Definition of Done

1. CI workflow executes on pull requests touching the module.
2. Static checks fail the PR on syntax/lint/XML issues.
3. At least TC-101, TC-102, TC-103, TC-105 are implemented as executable tests.
4. Security baseline (`csrf=False`, `.sudo(` counts) is tracked and does not regress without explicit approval.
