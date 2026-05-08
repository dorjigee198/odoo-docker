# Customer Support Module: Roles and User Stories

## 1. Purpose of this document
This document defines the main roles in your Odoo `customer_support` project and explicitly describes what each role is expected to do.

It is designed for:
- Product owners and stakeholders
- Developers and QA
- New team members onboarding to the project

Scope is based on current module behavior, route protections, and model permissions.

---

## 2. System context (what this module covers)
The module implements a full support lifecycle:
- Public landing/login/password recovery
- Customer ticket creation and tracking (list + kanban + detail modal)
- Support/Focal operations dashboard
- Project-based ticket boards with columns/tasks/checklists
- SLA tracking and alerting
- Admin operations (dashboard, assignment, user management, project/system config, reporting)
- AI chatbot and knowledge base-backed support

---

## 3. Role model (primary roles)
The module uses Odoo groups as role anchors:

- **Public Visitor**: unauthenticated user
- **Customer (Portal User)**: `base.group_portal`
- **Support Agent / Focal Person (Internal User)**: `base.group_user`
- **System Administrator**: `base.group_system`


### 3.1 Access boundary summary

#### Public Visitor
Can:
- View landing page
- Open login page
- Use forgot/reset password flow
- Access public Dragon chat page (`/dragon-chat`)

Cannot:
- Access customer/support/admin dashboards
- Create or manage tickets
- Access internal analytics/config

#### Customer (Portal)
Can:
- Access customer dashboard
- Create support tickets
- View own tickets in list/kanban and read-only detail
- Receive and mark ticket notifications
- View reporting from customer perspective
- Use support chatbot page
- Manage own profile/password/picture

Cannot:
- View other customers' tickets
- Assign/reassign tickets
- Perform admin config/user management
- Use support internal board operations

#### Support Agent / Focal Person
Can:
- Access support dashboard with analytics and ticket views
- View tickets assigned to self
- Update ticket progress/phase and add notesdd
- See SLA/assignment alerts and mark-read state
- Work via project-centric views (`My Projects`, project tickets, ticket board)
- Manage board structures and tasks (columns/tasks/checklists/member assignment)
- Use knowledge base management endpoints (group_user protected)

Cannot:
- Access admin dashboard/user management/config reserved for admins
- Perform admin-only auto-assignment control

#### System Administrator
Can:
- Full admin dashboard access
- Ticket assignment and ticket quick-view operations
- User lifecycle management (create/edit/activate/deactivate/role changes)
- System configuration and project configuration CRUD
- SLA policy management
- Reporting and export workflows
- Admin notification center + workload views
- Auto-assignment strategy/duration control

Cannot:
- N/A in normal module scope (admin is highest business role)

---

## 4. Detailed user stories by role

## 4.1 Public Visitor stories

### Story P1: Discover service and choose next step
As a public visitor,
I want to access the support landing page,
so that I can either start login or understand support offering.

Acceptance:
- Landing page loads without authentication
- If already logged in, CTA points to appropriate dashboard

### Story P2: Authenticate into the right workspace
As a public visitor,
I want to login using email/login + password,
so that I am redirected to my role-specific dashboard.

Acceptance:
- Admin -> admin dashboard
- Internal support -> support dashboard
- Portal customer -> customer dashboard
- Redirect parameter is sanitized to internal paths only

### Story P3: Recover lost password safely
As a public visitor,
I want a secure forgot/reset password flow,
so that I can recover account access without exposing whether an email exists.

Acceptance:
- Forgot password returns generic response
- Reset uses token verification and password policy checks


## 4.2 Customer (Portal User) stories

### Story C1: Submit a support request
As a customer,
I want to create a ticket with subject, description, priority, project, and attachments,
so that support can resolve my issue.

Acceptance:
- Required fields validated
- Ticket is created under my partner profile
- Attachments are stored and linked to the ticket

### Story C2: Track all my tickets
As a customer,
I want list and kanban views of my tickets,
so that I can quickly understand status and priority.

Acceptance:
- Only my tickets are shown
- Search/filter interactions work
- List and kanban navigation is available

### Story C3: View ticket details without accidental admin actions
As a customer,
I want read-only ticket detail,
so that I can review state, board progress, and history without changing operational workflow.

Acceptance:
- Customer cannot update state/priority/assignment from customer view
- Board/task progress can be seen
- Relevant communication entries are visible

### Story C4: Stay informed through notifications
As a customer,
I want notification updates (status/assignment/SLA),
so that I can react to progress in near real time.

Acceptance:
- Notification feed loads for current customer only
- Mark-all-read works

### Story C5: Manage my profile and security
As a customer,
I want to update my profile picture and password,
so that I can maintain account accuracy and security.

Acceptance:
- Session checks enforced
- Password validation and error handling are clear


## 4.3 Support Agent / Focal Person stories

### Story F1: Monitor assigned work in one place
As a focal person,
I want a dashboard with live ticket and analytics data,
so that I can prioritize daily support execution.

Acceptance:
- Assigned tickets are visible
- Counts/analytics and refresh flows operate

### Story F2: Receive urgency-based SLA alerts
As a focal person,
I want SLA and recent-assignment alerts,
so that I can act before breach and handle newly assigned tickets quickly.

Acceptance:
- Alerts include breached/at-risk and assignment signals
- Mark-read persistence is user-specific

### Story F3: Operate through project-oriented workflow
As a focal person,
I want to work from `My Projects` to project ticket lists to ticket board,
so that work organization matches delivery structure.

Acceptance:
- Only mapped/assigned project tickets are visible
- Public/portal users are redirected out of focal board workflows

### Story F4: Manage ticket execution board
As a focal person,
I want to create/rename/delete board columns and manage tasks/checklists/members,
so that ticket implementation progress is explicit and collaborative.

Acceptance:
- Board actions persist and are logged
- Task completion impacts board progress visibility

### Story F5: Capture operational notes and updates
As a focal person,
I want to add notes and update ticket progress endpoints,
so that activity is documented for customers/admins.

Acceptance:
- Updates are authenticated
- Ticket timeline and derived analytics reflect changes


## 4.4 System Administrator stories

### Story A1: Control support operations globally
As an admin,
I want a global dashboard and ticket management controls,
so that I can manage queue health, ownership, and outcomes.

Acceptance:
- Admin-only checks enforced
- Ticket assignment and quick view are available

### Story A2: Manage user lifecycle by role
As an admin,
I want to create/edit/deactivate/reactivate users and set role (customer/focal),
so that access is governed correctly over time.

Acceptance:
- Role mapping aligns with Odoo groups
- Welcome/notification emails are triggered where configured

### Story A3: Configure projects and system settings
As an admin,
I want project and configuration CRUD,
so that support operations map to actual delivery programs.

Acceptance:
- Project metadata/config are editable
- Deleting project triggers closure report generation

### Story A4: Govern SLA policies and performance reporting
As an admin,
I want SLA policy management and reporting APIs,
so that service quality can be measured and improved.

Acceptance:
- SLA CRUD routes are admin-protected
- Reporting outputs support dashboard visualization/export

### Story A5: Manage auto-assignment strategy
As an admin,
I want to enable/disable auto-assignment with strategy and duration,
so that ticket distribution can be balanced operationally.

Acceptance:
- Only admin can update strategy state
- Runtime status is visible and persisted


## 5. Data permissions snapshot (model-level)
Based on current access rules:

- `customer.support`:
  - portal: read/create (no write/delete)
  - support user: read/write/create
  - admin: full CRUD

- `customer_support.project`:
  - portal: read only
  - support user: read/write/create (no delete)
  - admin: full CRUD

- `customer_support.sla_policy`:
  - portal: read only
  - support user: read only
  - admin: full CRUD

- Board models (`ticket.column`, `ticket.task`) and project members:
  - portal: read only
  - support user: CRUD
  - admin: CRUD

- `ticket.comment`:
  - portal: no direct access entry
  - support user: read/write/create (no delete)
  - admin: full CRUD

Note: Route-level checks are also applied on top of model ACLs for many operations.

---

## 6. Cross-role workflow (end-to-end)
1. Public visitor logs in.
2. Customer creates ticket.
3. Admin or auto-assignment allocates ticket to focal person.
4. Focal person progresses work via board/tasks and notes.
5. SLA alerts guide urgency.
6. Customer tracks status via dashboard/list/kanban/notifications.
7. Admin monitors KPIs, workload, and compliance via reporting.

---

## 7. Recommended backlog items (documentation/governance)
- Add explicit ACL records for models currently warned as missing access rules.
- Standardize route type declarations (`jsonrpc` migration for Odoo 19 deprecation warnings).
- Add a role-to-route matrix appendix for QA regression checks.
- Add UAT checklist per role for each release.

---

## 8. Version note
Prepared for current code state in module `customer_support` as of April 2026.
