# Customer Support Module - Detailed Code Review

Date: 2026-04-24
Scope: `custom_addons/customer_support` (controllers, models, services, security, views touchpoints)
Review type: Static analysis and code inspection

## Executive Summary

This module is feature-rich and production-oriented, but it currently carries meaningful security and maintainability risk in request-handling paths.

Top risks are:
1. Missing authorization enforcement in some endpoints before rendering sensitive records.
2. Broad usage of `csrf=False` on mutating routes.
3. Widespread `sudo()` usage in controllers, often in user-facing flows.
4. Very large controller files that are difficult to reason about and safely change.

Observed metrics from current codebase:
- Controller Python files total: 7,566 lines
- `sudo(` occurrences in controllers: 167
- `csrf=False` occurrences in controllers: 32
- Largest controller file: `controllers/admin_users.py` (1,548 lines)

## Findings (Ordered by Severity)

### Critical

1. Missing access gate in ticket detail route
- File: `controllers/ticket_actions.py:47`
- Evidence:
  - Access flags are calculated (`is_admin`, `is_assigned`, `is_customer`) at `controllers/ticket_actions.py:63-67`
  - Route renders ticket anyway at `controllers/ticket_actions.py:139` with no deny check.
- Risk:
  - Any authenticated user can attempt to open another ticket ID and receive ticket details.
- Recommendation:
  - Add explicit deny condition before loading/rendering details:
    - `if not (is_admin or is_assigned or is_customer): return access denied redirect/403`

2. CSRF protection disabled on authentication endpoint
- File: `controllers/auth.py:100-105`
- Evidence:
  - `@http.route("/customer_support/authenticate", ..., methods=["POST"], csrf=False)`
- Risk:
  - Login flow can be targeted by forged cross-site POSTs (session confusion/login CSRF style behavior).
- Recommendation:
  - Enable CSRF (`csrf=True` default) and ensure login form carries the token.

3. Mutating profile endpoints with CSRF disabled
- File: `controllers/user_profile.py`
- Evidence:
  - Password endpoints with `csrf=False`: `:166`, `:205`, `:223`
  - Picture endpoints with `csrf=False`: `:241`, `:278`, `:296`
- Risk:
  - Cross-site requests could trigger profile mutations for logged-in users.
- Recommendation:
  - Re-enable CSRF and update frontend AJAX calls to include CSRF token.

### High

4. Weak redirect allowlist logic after login
- File: `controllers/auth.py:177-179`
- Evidence:
  - Redirect acceptance only checks `startswith("/customer_support/")`.
- Risk:
  - This guard is better than open redirect, but still too broad and fragile.
- Recommendation:
  - Use strict endpoint allowlist or signed internal return URLs.

5. Attachment/message loading with `sudo()` in ticket detail flow
- File: `controllers/ticket_actions.py:90-126`
- Evidence:
  - Fallback message query uses `.sudo()`.
  - Attachment query uses `.sudo()`.
  - Ticket logs query uses `.sudo()`.
- Risk:
  - Combined with missing authorization gate, this expands data exposure impact.
- Recommendation:
  - Enforce access first, then query without `sudo()` when possible, or with narrower domains + explicit access checks.

6. Customer detail route reads message thread with `sudo()`
- File: `controllers/tickets.py:111`
- Evidence:
  - `all_messages = ticket.sudo().message_ids.sorted(...)`
- Risk:
  - Could expose internal notes/messages not intended for portal users depending on data model usage.
- Recommendation:
  - Query only customer-visible messages and avoid blanket `sudo()` for message retrieval.

7. Public chatbot message endpoint without CSRF
- File: `controllers/chatbot_controller.py:92`
- Evidence:
  - `/dragon-chat/message` is `auth="public"` and `csrf=False`.
- Risk:
  - Abuse/spam surface; potential cost amplification if backend does expensive calls.
- Recommendation:
  - Add rate-limiting, abuse checks, and CSRF/session hardening (or move to tokenized API design).

### Medium

8. Upload validation relies on extension only
- File: `controllers/chatbot_controller.py:164`
- Evidence:
  - `allowed = (".pdf", ".docx", ".txt", ".xlsx")`
- Risk:
  - Extension-only checks are bypassable and do not validate file content.
- Recommendation:
  - Validate MIME and enforce file-size limits before processing.

9. Redirect parameter passed through without strict allowlist in KB upload
- File: `controllers/chatbot_controller.py:156`
- Evidence:
  - `redirect_to = kw.get("redirect_to", "/customer_support/knowledge")` then redirect usage.
- Risk:
  - Navigation manipulation and UX confusion; potential open redirect patterns if expanded.
- Recommendation:
  - Enforce known-good routes only.

10. Controllers are oversized and mix concerns
- Files:
  - `controllers/admin_users.py` (1,548 lines)
  - `controllers/focal_board.py` (1,206 lines)
  - `controllers/project_conf.py` (724 lines)
- Risk:
  - High regression risk, difficult review, test gaps, poor change isolation.
- Recommendation:
  - Split by bounded contexts (users/projects/tickets/reporting).

11. Project README is template placeholder
- File: `README.md`
- Risk:
  - Onboarding and CI adoption friction.
- Recommendation:
  - Replace with module-specific setup, run, and test instructions.

## Security and Access Notes

- ACL file exists and is generally structured (`security/ir.model.access.csv`), but controller-level bypasses via `sudo()` can undermine ACL intents.
- `base.group_portal` has create rights on `customer.support` (`security/ir.model.access.csv`), which may be intended, but should be explicitly validated with business rules.

## Testing and CI Gaps

1. No `tests/` package found in `custom_addons/customer_support`.
2. No automated regression checks around route authorization.
3. No CSRF behavior tests on mutating routes.
4. No upload validation/security tests.
5. No workflow to enforce lint/static checks at PR time.

## Priority Action Plan

P0 (Immediate)
1. Add authorization guard in `controllers/ticket_actions.py` before render.
2. Remove `csrf=False` from auth/profile mutation routes.
3. Add route-level tests for unauthorized ticket access.

P1 (Short term)
1. Reduce `sudo()` usage in user paths.
2. Tighten redirect policies.
3. Add rate-limiting and abuse controls for public chatbot endpoint.

P2 (Medium term)
1. Refactor oversized controllers.
2. Add structured module README and CI badges.
3. Introduce coverage and security checks in CI.

## Positive Observations

1. Route organization is mostly coherent by feature area.
2. Logging is present across many paths, aiding diagnostics.
3. Multiple pages explicitly set `Cache-Control` to reduce stale sensitive views.
4. Model layer includes SLA and activity-log semantics that can support robust reporting.

## Final Assessment

The module appears functionally mature but needs security hardening and test automation before CI/CD rollout. With the P0 changes and a baseline GitHub runner pipeline, quality risk can be reduced substantially in a short cycle.
