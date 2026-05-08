# -*- coding: utf-8 -*-
"""
Focal Person Board Controller
==============================
Routes for the project-based ticket management flow:

  GET  /customer_support/my_projects
       → Project cards view (replaces flat ticket list)

  GET  /customer_support/my_projects/<project_id>/tickets
       → Tickets for that project assigned to the focal person

  GET  /customer_support/ticket/<ticket_id>/board
       → Trello-like board view for a single ticket

  POST /customer_support/ticket/<ticket_id>/board/column/add
       → Create a new column on the board

  POST /customer_support/ticket/column/<column_id>/rename
       → Rename a column

  POST /customer_support/ticket/column/<column_id>/delete
       → Delete a column (and its tasks)

  POST /customer_support/ticket/column/<column_id>/task/add
       → Add a task to a column

  POST /customer_support/ticket/task/<task_id>/toggle
       → Toggle task done/not-done

  POST /customer_support/ticket/task/<task_id>/update
       → Update task title, description, members

  POST /customer_support/ticket/task/<task_id>/delete
       → Delete a task

  GET  /customer_support/my_projects/<project_id>/members_json
       → JSON list of project members (for assignee picker)
"""

import json
import logging
import secrets
from odoo import http
from odoo.http import request
import werkzeug
from ..services.email_service import EmailService

_CSRF_PLACEHOLDER = None  # csrf token added via request at render time

_logger = logging.getLogger(__name__)


def _member_payload(member):
    """Return the serialisable task-assignee payload for a project member."""
    name = member.user_id.name if member.user_id else (member.member_name or "")
    if not name:
        return None
    email = member.user_id.email if member.user_id else (member.member_email or "")
    return {
        "member_id": member.id,
        "user_id": member.user_id.id if member.user_id else None,
        "name": name,
        "email": email,
        "role": member.role_label or "Other",
        "role_key": member.role,
        "initials": "".join(p[0].upper() for p in name.split()[:2]) if name else "?",
    }


def _email_prefix(name):
    """Return the part before @ for email-style names, otherwise return name as-is."""
    if not name:
        return "Unknown"
    return name.split('@')[0] if '@' in name else name


def _comment_author(c):
    """Return the display name for a comment, preferring author_name over user.name."""
    raw = c.author_name or (c.user_id.name if c.user_id else "Unknown")
    return _email_prefix(raw)


def _task_member_ids(task):
    """Return the assigned project member IDs for a task, including legacy user-only data."""
    if task.project_member_ids:
        return task.project_member_ids.ids
    if not task.ticket_id.project_id or not task.member_ids:
        return []
    members = (
        request.env["customer_support.project.member"]
        .sudo()
        .search(
            [
                ("project_id", "=", task.ticket_id.project_id.id),
                ("user_id", "in", task.member_ids.ids),
            ]
        )
    )
    return members.ids


def _build_task_dict(task):
    """Build a serialisable dict for a task including checklist items."""
    due = task.due_date.isoformat() if task.due_date else None
    members = task.project_member_ids
    if not members and task.ticket_id.project_id and task.member_ids:
        members = (
            request.env["customer_support.project.member"]
            .sudo()
            .search(
                [
                    ("project_id", "=", task.ticket_id.project_id.id),
                    ("user_id", "in", task.member_ids.ids),
                ],
                order="role, id",
            )
        )
    return {
        "id": task.id,
        "name": task.name,
        "description": task.description or "",
        "is_done": task.is_done,
        "due_date": due,
        "task_priority": task.task_priority or "none",
        "members": [payload for m in members if (payload := _member_payload(m))],
        "checklist": [
            {"id": c.id, "name": c.name, "is_done": c.is_done}
            for c in task.checklist_ids
        ],
        "notes": [
            {
                "id": n.id,
                "author": n.user_id.name if n.user_id else (n.author_name or "Board Member"),
                "author_id": n.user_id.id if n.user_id else False,
                "message": n.message or "",
                "created": n.create_date.strftime("%b %d, %Y %H:%M") if n.create_date else "",
            }
            for n in task.note_ids
        ],
    }


def _require_focal(user):
    """Return True if user is a valid internal (focal) user, False otherwise."""
    if user.id == request.env.ref("base.public_user").id:
        return False
    if user.has_group("base.group_portal"):
        return False
    return True


def _log(ticket_id, event_type, summary, actor=None, detail=None, old_value=None, new_value=None):
    """Write a single entry to customer.support.ticket.log."""
    try:
        vals = {
            "ticket_id": ticket_id,
            "event_type": event_type,
            "summary": summary,
        }
        if actor:
            vals["actor_id"] = actor.id
        if detail:
            vals["detail"] = detail
        if old_value:
            vals["old_value"] = old_value
        if new_value:
            vals["new_value"] = new_value
        request.env["customer.support.ticket.log"].sudo().create(vals)
    except Exception as e:
        _logger.warning("Board activity log failed: %s", e)


def _conversation_messages(ticket, user, limit=80):
    """Return customer-facing chatter entries for ticket as serializable dicts."""
    raw_messages = (
        request.env["mail.message"]
        .sudo()
        .search(
            [
                ("model", "=", "customer.support"),
                ("res_id", "=", ticket.id),
                ("message_type", "in", ["comment", "notification"]),
                ("subtype_id.internal", "=", False),
            ],
            order="date asc",
            limit=limit,
        )
    )
    customer_partner_id = ticket.customer_id.id if ticket.customer_id else False

    def _initials(name):
        parts = (name or "?").split()
        return "".join(p[0].upper() for p in parts[:2]) or "?"

    return [
        {
            "id": m.id,
            "author": m.author_id.name if m.author_id else "System",
            "author_id": m.author_id.id if m.author_id else False,
            "initials": _initials(m.author_id.name if m.author_id else "System"),
            "body": m.body or "",
            "created": m.date.strftime("%b %d, %Y %H:%M") if m.date else "",
            "from_customer": bool(customer_partner_id and m.author_id.id == customer_partner_id),
            "is_me": bool(user and m.author_id and m.author_id.id == user.partner_id.id),
        }
        for m in raw_messages
    ]


class FocalBoardController(http.Controller):

    def _authorize_for_ticket(self, ticket, kw=None):
        """Return True if the current request is allowed to modify the given ticket.

        Logged-in focal users (internal) keep existing rights. Public requests must
        supply a matching `board_token` parameter to be allowed.
        """
        try:
            user = request.env.user
            public_user_id = request.env.ref('base.public_user').id
            # Logged-in internal focal users
            if user and user.id != public_user_id and _require_focal(user):
                return True

            # Public access via token
            token = None
            if kw and isinstance(kw, dict):
                token = kw.get('board_token') or kw.get('token')
            if not token:
                token = request.params.get('board_token') or request.params.get('token')
            if token and ticket and ticket.board_token and token == ticket.board_token:
                return True
        except Exception:
            _logger.warning("Board access check failed; denying access by default.")
        return False


    # =========================================================================
    # PROJECT CARDS
    # =========================================================================

    @http.route(
        "/customer_support/my_projects",
        type="http",
        auth="user",
        website=True,
    )
    def my_projects(self, **kw):
        """
        Main landing for focal persons: shows project cards.
        Each card displays the project name, open ticket count,
        total ticket count, and number of team members.
        """
        user = request.env.user

        if not _require_focal(user):
            return werkzeug.utils.redirect("/customer_support/dashboard")
        if user.has_group("base.group_system"):
            return werkzeug.utils.redirect("/customer_support/admin_dashboard")

        try:
            # Projects this focal person is explicitly mapped to via project.member
            member_records = (
                request.env["customer_support.project.member"]
                .sudo()
                .search([("user_id", "=", user.id)])
            )
            mapped_project_ids = set(member_records.mapped("project_id.id"))

            if not mapped_project_ids:
                _logger.info("my_projects: user=%s has no mapped projects", user.name)
                return request.render(
                    "customer_support.focal_projects_page",
                    {"user": user, "projects": [], "page_name": "my_projects"},
                )

            mapped_projects = (
                request.env["customer_support.project"]
                .sudo()
                .search([("id", "in", list(mapped_project_ids)), ("active", "=", True)])
            )

            # All tickets assigned to this focal person
            assigned_tickets = (
                request.env["customer.support"]
                .sudo()
                .search([("assigned_to", "=", user.id)])
            )

            _logger.info(
                "my_projects: user=%s mapped_projects=%d assigned_tickets=%d",
                user.name, len(mapped_projects), len(assigned_tickets),
            )

            projects = []
            for proj in mapped_projects:
                proj_tickets = assigned_tickets.filtered(
                    lambda t, pid=proj.id: t.project_id.id == pid
                )
                open_tickets = proj_tickets.filtered(
                    lambda t: t.state not in ["resolved", "closed"]
                )
                member_count = (
                    request.env["customer_support.project.member"]
                    .sudo()
                    .search_count([("project_id", "=", proj.id)])
                )
                projects.append({
                    "id": proj.id,
                    "name": proj.name,
                    "code": proj.code or "",
                    "total_tickets": len(proj_tickets),
                    "open_tickets": len(open_tickets),
                    "member_count": member_count,
                })

            _logger.info("my_projects: rendering %d project cards", len(projects))

            return request.render(
                "customer_support.focal_projects_page",
                {
                    "user": user,
                    "projects": projects,
                    "page_name": "my_projects",
                },
            )

        except Exception as e:
            _logger.error("my_projects error: %s", e)
            return werkzeug.utils.redirect(
                "/customer_support/support_dashboard?error=Error loading projects"
            )

    # =========================================================================
    # PROJECT TICKETS
    # =========================================================================

    @http.route(
        "/customer_support/my_projects/<int:project_id>/tickets",
        type="http",
        auth="user",
        website=True,
    )
    def project_tickets(self, project_id, **kw):
        """Tickets for the given project assigned to the current focal person."""
        user = request.env.user

        if not _require_focal(user):
            return werkzeug.utils.redirect("/customer_support/dashboard")

        try:
            project = request.env["customer_support.project"].sudo().browse(project_id)
            if not project.exists():
                return werkzeug.utils.redirect("/customer_support/my_projects")

            tickets = (
                request.env["customer.support"]
                .sudo()
                .search(
                    [
                        ("assigned_to", "=", user.id),
                        ("project_id", "=", project_id),
                    ],
                    order="create_date desc",
                )
            )

            return request.render(
                "customer_support.focal_project_tickets_page",
                {
                    "user": user,
                    "project": project,
                    "tickets": tickets,
                    "page_name": "project_tickets",
                },
            )

        except Exception as e:
            _logger.error("project_tickets error: %s", e)
            return werkzeug.utils.redirect("/customer_support/my_projects")

    # =========================================================================
    # TICKET BOARD (Trello view)
    # =========================================================================

    @http.route(
        "/customer_support/ticket/<int:ticket_id>/board",
        type="http",
        auth="user",
        website=True,
    )
    def ticket_board(self, ticket_id, **kw):
        """Trello-like board for a single ticket."""
        user = request.env.user

        if not _require_focal(user):
            return werkzeug.utils.redirect("/customer_support/dashboard")

        try:
            ticket = request.env["customer.support"].sudo().browse(ticket_id)
            if not ticket.exists():
                return werkzeug.utils.redirect("/customer_support/my_projects")

            columns = (
                request.env["customer_support.ticket.column"]
                .sudo()
                .search([("ticket_id", "=", ticket_id)], order="sequence, id")
            )

            # Project members for the assignee picker (only Odoo users can be assigned)
            project_members = []
            if ticket.project_id:
                members = (
                    request.env["customer_support.project.member"]
                    .sudo()
                    .search([("project_id", "=", ticket.project_id.id)])
                )
                for m in members:
                    if m.user_id:
                        name = m.user_id.name
                        project_members.append({
                            "member_id": m.id,
                            "user_id": m.user_id.id,
                            "email": m.user_id.email or "",
                            "name": name,
                            "role": m.role_label or "Other",
                            "role_key": m.role,
                            "initials": "".join(p[0].upper() for p in name.split()[:2]),
                        })
                    elif m.member_name:
                        name = m.member_name
                        project_members.append({
                            "member_id": m.id,
                            "user_id": None,
                            "email": m.member_email or "",
                            "name": name,
                            "role": m.role_label or "Other",
                            "role_key": m.role,
                            "initials": "".join(p[0].upper() for p in name.split()[:2]),
                        })

            # Build column data with tasks
            board_columns = []
            for col in columns:
                tasks = [
                    _build_task_dict(task)
                    for task in col.task_ids.sorted(key=lambda t: (t.sequence, t.id))
                ]
                board_columns.append({
                    "id": col.id,
                    "name": col.name,
                    "color": col.color or "#e2e8f0",
                    "task_count": col.task_count,
                    "done_count": col.done_count,
                    "tasks": tasks,
                })

            # Ticket attachments (uploaded by customer)
            attachments = (
                request.env["ir.attachment"]
                .sudo()
                .search([
                    ("res_model", "=", "customer.support"),
                    ("res_id", "=", ticket_id),
                ])
            )
            attachment_list = [
                {
                    "id": a.id,
                    "name": a.name,
                    "mimetype": a.mimetype or "",
                    "url": (
                        f"/customer_support/attachment/{a.id}/download?board_token={ticket.board_token}"
                        if ticket.board_token else f"/web/content/{a.id}?download=true"
                    ),
                }
                for a in attachments
            ]

            # Project documents (linked by admin during project config)
            project_docs = []
            if ticket.project_id:
                docs = (
                    request.env["dc.knowledge.document"]
                    .sudo()
                    .search([
                        ("project_id", "=", ticket.project_id.id),
                        ("active", "=", True),
                    ])
                )
                project_docs = [
                    {
                        "id": d.id,
                        "name": d.name,
                        "filename": d.filename or d.name,
                        "file_type": d.file_type or "other",
                        "description": d.description or "",
                        "url": (
                            f"/customer_support/document/{d.id}/download?board_token={ticket.board_token}"
                            if ticket.board_token else f"/web/content/dc.knowledge.document/{d.id}/file/{d.filename or 'document'}?download=true"
                        ),
                    }
                    for d in docs
                ]

            # Internal comments
            comments_recs = (
                request.env["customer_support.ticket.comment"]
                .sudo()
                .search([("ticket_id", "=", ticket_id)])
            )
            comments = [
                {
                    "id": c.id,
                    "author": _comment_author(c),
                    "author_id": c.user_id.id if c.user_id else 0,
                    "initials": "".join(p[0].upper() for p in _comment_author(c).split()[:2]),
                    "message": c.message,
                    "created": c.create_date.strftime("%b %d, %Y %H:%M") if c.create_date else "",
                }
                for c in comments_recs
            ]

            customer_conversation = _conversation_messages(ticket, user)

            # Activity log (last 40 entries)
            log_recs = (
                request.env["customer.support.ticket.log"]
                .sudo()
                .search([("ticket_id", "=", ticket_id)], order="timestamp desc", limit=40)
            )
            activity_log = [
                {
                    "event_type": l.event_type,
                    "message": l.summary,
                    "detail": l.detail or "",
                    "actor": l.actor_id.name if l.actor_id else "",
                    "timestamp": l.timestamp.strftime("%b %d, %H:%M") if l.timestamp else "",
                }
                for l in log_recs
            ]

            return request.render(
                "customer_support.ticket_board_page",
                {
                    "user": user,
                    "ticket": ticket,
                    "board_columns": board_columns,
                    "board_columns_json": json.dumps(board_columns),
                    "project_members": project_members,
                    "project_members_json": json.dumps(project_members),
                    "attachments": attachment_list,
                    "project_docs": project_docs,
                    "comments": comments,
                    "customer_conversation_json": json.dumps(customer_conversation),
                    "activity_log": activity_log,
                    "page_name": "ticket_board",
                    "board_bg_json": json.dumps(ticket.board_bg or ''),
                },
            )

        except Exception as e:
            _logger.error("ticket_board error: %s", e)
            return werkzeug.utils.redirect("/customer_support/my_projects")

    # =========================================================================
    # PUBLIC BOARD — token-based access for team members (no login required)
    # =========================================================================

    @http.route(
        "/board/<string:token>",
        type="http",
        auth="public",
        website=True,
    )
    def public_ticket_board(self, token, **kw):
        """Read-only board accessible to team members via emailed token link."""
        try:
            ticket = (
                request.env["customer.support"]
                .sudo()
                .search([("board_token", "=", token)], limit=1)
            )
            if not ticket:
                return request.render("customer_support.board_token_invalid", {})

            ticket_id = ticket.id

            columns = (
                request.env["customer_support.ticket.column"]
                .sudo()
                .search([("ticket_id", "=", ticket_id)], order="sequence, id")
            )

            board_columns = []
            for col in columns:
                tasks = [
                    _build_task_dict(task)
                    for task in col.task_ids.sorted(key=lambda t: (t.sequence, t.id))
                ]
                board_columns.append({
                    "id": col.id,
                    "name": col.name,
                    "color": col.color or "#e2e8f0",
                    "task_count": col.task_count,
                    "done_count": col.done_count,
                    "tasks": tasks,
                })

            project_docs = []
            if ticket.project_id:
                docs = (
                    request.env["dc.knowledge.document"]
                    .sudo()
                    .search([
                        ("project_id", "=", ticket.project_id.id),
                        ("active", "=", True),
                    ])
                )
                project_docs = [
                    {
                        "id": d.id,
                        "name": d.name,
                        "filename": d.filename or d.name,
                        "file_type": d.file_type or "other",
                        "description": d.description or "",
                        "url": f"/web/content/dc.knowledge.document/{d.id}/file/{d.filename or 'document'}?download=true",
                    }
                    for d in docs
                ]

            # Load project members so token users can assign tasks
            project_members = []
            if ticket.project_id:
                members = (
                    request.env["customer_support.project.member"]
                    .sudo()
                    .search([("project_id", "=", ticket.project_id.id)])
                )
                for m in members:
                    payload = _member_payload(m)
                    if payload:
                        project_members.append(payload)

            # Load internal comments so token users see existing notes
            comments_recs = (
                request.env["customer_support.ticket.comment"]
                .sudo()
                .search([("ticket_id", "=", ticket_id)])
            )
            comments = [
                {
                    "id": c.id,
                    "author": _comment_author(c),
                    "author_id": c.user_id.id if c.user_id else 0,
                    "initials": "".join(p[0].upper() for p in _comment_author(c).split()[:2]),
                    "message": c.message,
                    "created": c.create_date.strftime("%b %d, %Y %H:%M") if c.create_date else "",
                }
                for c in comments_recs
            ]

            return request.render(
                "customer_support.ticket_board_page",
                {
                    "user": None,
                    "ticket": ticket,
                    "board_columns": board_columns,
                    "board_columns_json": json.dumps(board_columns),
                    "project_members": project_members,
                    "project_members_json": json.dumps(project_members),
                    "attachments": [],
                    "project_docs": project_docs,
                    "comments": comments,
                    "customer_conversation_json": "[]",
                    "activity_log": [],
                    "page_name": "ticket_board",
                    "public_board": True,
                    "board_token": token,
                    "board_bg_json": json.dumps(ticket.board_bg or ''),
                },
            )

        except Exception as e:
            _logger.error("public_ticket_board error: %s", e)
            return request.render("customer_support.board_token_invalid", {})

    # =========================================================================
    # COLUMN CRUD (JSON endpoints)
    # =========================================================================

    @http.route(
        "/customer_support/ticket/<int:ticket_id>/board/column/add",
        type="jsonrpc",
        auth="user",
        csrf=True,
    )
    def add_column(self, ticket_id, **kw):
        try:
            name = (kw.get("name") or "").strip()
            color = kw.get("color") or "#e2e8f0"
            if not name:
                return {"error": "Column name is required"}

            ticket = request.env["customer.support"].sudo().browse(ticket_id)
            if not ticket.exists():
                return {"error": "Ticket not found"}

            # Next sequence
            last = request.env["customer_support.ticket.column"].sudo().search(
                [("ticket_id", "=", ticket_id)], order="sequence desc", limit=1
            )
            seq = (last.sequence + 10) if last else 10

            col = request.env["customer_support.ticket.column"].sudo().create({
                "ticket_id": ticket_id,
                "name": name,
                "color": color,
                "sequence": seq,
            })
            _log(ticket_id, "board_col_add",
                 f'{request.env.user.name} added column "{name}"',
                 actor=request.env.user)
            return {"success": True, "column_id": col.id, "name": col.name, "color": col.color}

        except Exception as e:
            _logger.error("add_column error: %s", e)
            return {"error": str(e)}

    @http.route(
        "/customer_support/ticket/column/<int:column_id>/rename",
        type="jsonrpc",
        auth="user",
        csrf=True,
    )
    def rename_column(self, column_id, **kw):
        try:
            name = (kw.get("name") or "").strip()
            color = kw.get("color")
            if not name:
                return {"error": "Column name is required"}

            col = request.env["customer_support.ticket.column"].sudo().browse(column_id)
            if not col.exists():
                return {"error": "Column not found"}

            old_name = col.name
            vals = {"name": name}
            if color:
                vals["color"] = color
            col.write(vals)
            ticket_id = col.ticket_id.id
            _log(ticket_id, "board_col_rename",
                 f'{request.env.user.name} renamed column "{old_name}" → "{name}"',
                 actor=request.env.user, old_value=old_name, new_value=name)
            return {"success": True, "name": col.name, "color": col.color}

        except Exception as e:
            _logger.error("rename_column error: %s", e)
            return {"error": str(e)}

    @http.route(
        "/customer_support/ticket/column/<int:column_id>/delete",
        type="jsonrpc",
        auth="user",
        csrf=True,
    )
    def delete_column(self, column_id, **kw):
        try:
            col = request.env["customer_support.ticket.column"].sudo().browse(column_id)
            if not col.exists():
                return {"error": "Column not found"}
            ticket_id = col.ticket_id.id
            col_name = col.name
            col.unlink()
            _log(ticket_id, "board_col_delete",
                 f'{request.env.user.name} deleted column "{col_name}"',
                 actor=request.env.user)
            return {"success": True}

        except Exception as e:
            _logger.error("delete_column error: %s", e)
            return {"error": str(e)}

    @http.route(
        "/customer_support/project_member/<int:member_id>/set_role",
        type="jsonrpc", auth="user", csrf=True,
    )
    def set_member_role(self, member_id, **kw):
        try:
            role = (kw.get("role") or "other").strip()
            valid = {"focal_person", "frontend_dev", "backend_dev", "network_manager", "designer", "qa_engineer", "other"}
            if role not in valid:
                return {"error": "Invalid role"}
            member = request.env["customer_support.project.member"].sudo().browse(member_id)
            if not member.exists():
                return {"error": "Member not found"}
            member.write({"role": role})
            return {"success": True, "role_label": member.role_label}
        except Exception as e:
            _logger.error("set_member_role error: %s", e)
            return {"error": str(e)}

    @http.route(
        "/customer_support/ticket/<int:ticket_id>/board/set_bg",
        type="jsonrpc", auth="user", csrf=True,
    )
    def set_board_bg(self, ticket_id, **kw):
        try:
            bg = (kw.get("bg") or "").strip()
            ticket = request.env["customer.support"].sudo().browse(ticket_id)
            if not ticket.exists():
                return {"error": "Ticket not found"}
            ticket.write({"board_bg": bg})
            return {"success": True}
        except Exception as e:
            _logger.error("set_board_bg error: %s", e)
            return {"error": str(e)}

    @http.route(
        "/customer_support/ticket/<int:ticket_id>/columns/reorder",
        type="jsonrpc",
        auth="user",
        csrf=True,
    )
    def reorder_columns(self, ticket_id, **kw):
        try:
            column_ids = [cid for cid in (kw.get("column_ids") or []) if isinstance(cid, int) and cid > 0]
            ticket = request.env["customer.support"].sudo().browse(ticket_id)
            if not ticket.exists():
                return {"error": "Ticket not found"}
            for seq, col_id in enumerate(column_ids):
                col = request.env["customer_support.ticket.column"].sudo().browse(col_id)
                if col.exists() and col.ticket_id.id == ticket_id:
                    col.write({"sequence": (seq + 1) * 10})
            return {"success": True}
        except Exception as e:
            _logger.error("reorder_columns error: %s", e)
            return {"error": str(e)}

    # =========================================================================
    # TASK CRUD (JSON endpoints)
    # =========================================================================

    @http.route(
        "/customer_support/ticket/column/<int:column_id>/task/add",
        type="jsonrpc",
        auth="public",
        csrf=True,
    )
    def add_task(self, column_id, **kw):
        try:
            name = (kw.get("name") or "").strip()
            if not name:
                return {"error": "Task title is required"}

            col = request.env["customer_support.ticket.column"].sudo().browse(column_id)
            if not col.exists():
                return {"error": "Column not found"}

            # Authorization: allow focal users or public token matching the ticket
            if not self._authorize_for_ticket(col.ticket_id, kw):
                return {"error": "Access denied"}

            member_ids = [mid for mid in (kw.get("member_ids") or []) if isinstance(mid, int) and mid > 0]
            description = (kw.get("description") or "").strip()
            due_date = kw.get("due_date") or False
            task_priority = kw.get("task_priority") or "none"
            selected_members = request.env["customer_support.project.member"].sudo().browse(member_ids)
            selected_user_ids = selected_members.mapped("user_id").ids

            last = request.env["customer_support.ticket.task"].sudo().search(
                [("column_id", "=", column_id)], order="sequence desc", limit=1
            )
            seq = (last.sequence + 10) if last else 10

            task = request.env["customer_support.ticket.task"].sudo().create({
                "column_id": column_id,
                "name": name,
                "description": description or False,
                "project_member_ids": [(6, 0, selected_members.ids)],
                "member_ids": [(6, 0, selected_user_ids)],
                "sequence": seq,
                "due_date": due_date or False,
                "task_priority": task_priority,
            })
            ticket_id = col.ticket_id.id
            assigned_names = ""
            if selected_members:
                assigned_names = ", ".join(
                    member.user_id.name if member.user_id else (member.member_name or "")
                    for member in selected_members
                    if (member.user_id or member.member_name)
                )
            summary = f'{request.env.user.name} added task "{name}" to "{col.name}"'
            if assigned_names:
                summary += f" — assigned to {assigned_names}"
            _log(ticket_id, "board_task_add", summary, actor=request.env.user)
            # Send assignment emails to selected members
            try:
                ticket = col.ticket_id
                # Ensure a board token exists so external members get a direct link
                has_external = any(not m.user_id for m in selected_members)
                if has_external and not ticket.board_token:
                    ticket.sudo().write({"board_token": secrets.token_urlsafe(32)})
                for member in selected_members:
                    try:
                        EmailService.send_task_assignment(ticket, member, task)
                    except Exception as mail_err:
                        _logger.warning("Task assignment email failed: %s", mail_err)
            except Exception:
                _logger.warning("Post-create task assignment/update block failed; continuing task creation flow.")
            return {"success": True, "task": _build_task_dict(task)}

        except Exception as e:
            _logger.error("add_task error: %s", e)
            return {"error": str(e)}

    @http.route(
        "/customer_support/ticket/task/<int:task_id>/toggle",
        type="jsonrpc",
        auth="public",
        csrf=True,
    )
    def toggle_task(self, task_id, **kw):
        try:
            task = request.env["customer_support.ticket.task"].sudo().browse(task_id)
            if not task.exists():
                return {"error": "Task not found"}
            # Checklist completion is focal-only; board members can add notes instead.
            if not self._authorize_for_ticket(task.ticket_id, kw):
                return {"error": "Access denied"}
            task.write({"is_done": not task.is_done})
            ticket_id = task.ticket_id.id
            evt = "board_task_done" if task.is_done else "board_task_undone"
            verb = "completed" if task.is_done else "reopened"
            _log(ticket_id, evt,
                 f'{request.env.user.name} {verb} task "{task.name}"',
                 actor=request.env.user)
            return {"success": True, "is_done": task.is_done}

        except Exception as e:
            _logger.error("toggle_task error: %s", e)
            return {"error": str(e)}

    @http.route(
        "/customer_support/ticket/task/<int:task_id>/update",
        type="jsonrpc",
        auth="public",
        csrf=True,
    )
    def update_task(self, task_id, **kw):
        try:
            task = request.env["customer_support.ticket.task"].sudo().browse(task_id)
            if not task.exists():
                return {"error": "Task not found"}

            # Authorization
            if not self._authorize_for_ticket(task.ticket_id, kw):
                return {"error": "Access denied"}

            vals = {}
            if "name" in kw and kw["name"].strip():
                vals["name"] = kw["name"].strip()
            if "description" in kw:
                vals["description"] = kw["description"].strip() or False
            if "member_ids" in kw:
                clean_ids = [mid for mid in (kw["member_ids"] or []) if isinstance(mid, int) and mid > 0]
                selected_members = request.env["customer_support.project.member"].sudo().browse(clean_ids)
                vals["project_member_ids"] = [(6, 0, selected_members.ids)]
                vals["member_ids"] = [(6, 0, selected_members.mapped("user_id").ids)]
            if "due_date" in kw:
                vals["due_date"] = kw["due_date"] or False
            if "task_priority" in kw:
                vals["task_priority"] = kw["task_priority"] or "none"

            old_members = set(_task_member_ids(task))
            task.write(vals)
            ticket_id = task.ticket_id.id
            # Log member assignments if changed
            if "member_ids" in kw:
                new_members = set(_task_member_ids(task))
                added = new_members - old_members
                removed = old_members - new_members
                if added:
                    names = ", ".join(
                        member.user_id.name if member.user_id else (member.member_name or "")
                        for member in request.env["customer_support.project.member"].sudo().browse(list(added))
                        if (member.user_id or member.member_name)
                    )
                    _log(ticket_id, "board_task_assign",
                         f'{request.env.user.name} assigned "{task.name}" to {names}',
                         actor=request.env.user)
                    # Send assignment emails for newly added members
                    try:
                        new_members = request.env["customer_support.project.member"].sudo().browse(list(added))
                        # Ensure a board token exists so external members get a direct link
                        has_external = any(not m.user_id for m in new_members)
                        if has_external and not task.ticket_id.board_token:
                            task.ticket_id.sudo().write({"board_token": secrets.token_urlsafe(32)})
                        for member in new_members:
                            try:
                                EmailService.send_task_assignment(task.ticket_id, member, task)
                            except Exception as mail_err:
                                _logger.warning("Task assignment email failed: %s", mail_err)
                    except Exception:
                        _logger.warning("Post-assignee update notification block failed; continuing update flow.")
                if removed:
                    names = ", ".join(
                        member.user_id.name if member.user_id else (member.member_name or "")
                        for member in request.env["customer_support.project.member"].sudo().browse(list(removed))
                        if (member.user_id or member.member_name)
                    )
                    _log(ticket_id, "board_task_assign",
                         f'{request.env.user.name} removed {names} from task "{task.name}"',
                         actor=request.env.user)
            elif vals:
                _log(ticket_id, "board_task_edit",
                     f'{request.env.user.name} edited task "{task.name}"',
                     actor=request.env.user)
            return {"success": True, "task": _build_task_dict(task)}

        except Exception as e:
            _logger.error("update_task error: %s", e)
            return {"error": str(e)}

    @http.route(
        "/customer_support/ticket/task/<int:task_id>/delete",
        type="jsonrpc",
        auth="public",
        csrf=True,
    )
    def delete_task(self, task_id, **kw):
        try:
            task = request.env["customer_support.ticket.task"].sudo().browse(task_id)
            if not task.exists():
                return {"error": "Task not found"}
            if not self._authorize_for_ticket(task.ticket_id, kw):
                return {"error": "Access denied"}
            ticket_id = task.ticket_id.id
            task_name = task.name
            task.unlink()
            _log(ticket_id, "board_task_delete",
                 f'{request.env.user.name} deleted task "{task_name}"',
                 actor=request.env.user)
            return {"success": True}

        except Exception as e:
            _logger.error("delete_task error: %s", e)
            return {"error": str(e)}

    # =========================================================================
    # TASK MOVE (drag-and-drop between columns)
    # =========================================================================

    @http.route(
        "/customer_support/ticket/task/<int:task_id>/move",
        type="jsonrpc",
        auth="public",
        csrf=True,
    )
    def move_task(self, task_id, **kw):
        try:
            column_id = kw.get("column_id")
            if not column_id:
                return {"error": "column_id is required"}

            task = request.env["customer_support.ticket.task"].sudo().browse(task_id)
            if not task.exists():
                return {"error": "Task not found"}

            # Authorization
            if not self._authorize_for_ticket(task.ticket_id, kw):
                return {"error": "Access denied"}

            col = request.env["customer_support.ticket.column"].sudo().browse(int(column_id))
            if not col.exists():
                return {"error": "Column not found"}

            old_col_name = task.column_id.name
            task.write({"column_id": col.id})
            ticket_id = task.ticket_id.id
            _log(ticket_id, "board_task_move",
                 f'{request.env.user.name} moved "{task.name}" from "{old_col_name}" → "{col.name}"',
                 actor=request.env.user, old_value=old_col_name, new_value=col.name)
            return {"success": True}

        except Exception as e:
            _logger.error("move_task error: %s", e)
            return {"error": str(e)}

    # NOTE: Ticket status change is handled by ticket_actions.py
    # POST /customer_support/ticket/<id>/update_status  (type=http, param: status)

    # =========================================================================
    # INTERNAL COMMENTS
    # =========================================================================

    @http.route(
        "/customer_support/ticket/<int:ticket_id>/comment/add",
        type="jsonrpc",
        auth="public",
        csrf=True,
    )
    def add_comment(self, ticket_id, **kw):
        try:
            message = (kw.get("message") or "").strip()
            # mentioned_users is a list of {user_id, email, name} objects
            mentioned_users = kw.get("mentioned_users") or []
            if not message:
                return {"error": "Message is required"}

            ticket = request.env["customer.support"].sudo().browse(ticket_id)
            if not ticket.exists():
                return {"error": "Ticket not found"}

            # Authorization: allow focal users or public token matching the ticket
            if not self._authorize_for_ticket(ticket, kw):
                return {"error": "Access denied"}

            user = request.env.user
            public_user_id = request.env.ref("base.public_user").id
            poster_name = (kw.get("poster_name") or "").strip()
            author_name = poster_name if (user.id == public_user_id and poster_name) else None

            comment = request.env["customer_support.ticket.comment"].sudo().create({
                "ticket_id": ticket_id,
                "user_id": user.id,
                "message": message,
                "author_name": author_name,
            })

            # Send @mention notifications
            if mentioned_users:
                try:
                    for m in mentioned_users:
                        uid = m.get("user_id")
                        email = m.get("email") or ""
                        name = m.get("name") or ""
                        if uid:
                            # Internal Odoo user — look up fresh to get current email
                            mentioned_user = request.env["res.users"].sudo().browse(int(uid))
                            if mentioned_user.exists():
                                email = mentioned_user.email or email
                                name = mentioned_user.name or name
                        if email:
                            EmailService.send_mention_notification(
                                email, name, user.name, ticket, message
                            )
                except Exception as mention_err:
                    _logger.warning("Mention notification failed: %s", mention_err)

            display_name = _email_prefix(author_name or user.name)
            mentions_str = ""
            if mentioned_users:
                mentions_str = " — mentioned: " + ", ".join(m.get("name", "") for m in mentioned_users)
            short_msg = (message[:60] + "…") if len(message) > 60 else message
            _log(ticket_id, "board_comment",
                 f'{display_name} posted an internal note{mentions_str}',
                 actor=user, detail=short_msg)

            initials = "".join(p[0].upper() for p in display_name.split()[:2])
            return {
                "success": True,
                "comment": {
                    "id": comment.id,
                    "author": display_name,
                    "author_id": user.id,
                    "initials": initials,
                    "message": comment.message,
                    "created": comment.create_date.strftime("%b %d, %Y %H:%M") if comment.create_date else "",
                },
            }

        except Exception as e:
            _logger.error("add_comment error: %s", e)
            return {"error": str(e)}

    # =========================================================================
    # PROJECT MEMBERS JSON (for assignee picker)
    # =========================================================================

    @http.route(
        "/customer_support/my_projects/<int:project_id>/members_json",
        type="jsonrpc",
        auth="user",
        csrf=True,
    )
    def project_members_json(self, project_id, **kw):
        try:
            members = (
                request.env["customer_support.project.member"]
                .sudo()
                .search([("project_id", "=", project_id)])
            )
            result = []
            for m in members:
                if m.user_id:
                    name = m.user_id.name
                    result.append({
                        "user_id": m.user_id.id,
                        "email": m.user_id.email or "",
                        "name": name,
                        "role": m.role_label,
                        "initials": "".join(p[0].upper() for p in name.split()[:2]),
                    })
                elif m.member_name:
                    name = m.member_name
                    result.append({
                        "user_id": None,
                        "email": m.member_email or "",
                        "name": name,
                        "role": m.role_label,
                        "initials": "".join(p[0].upper() for p in name.split()[:2]),
                    })
            return {"success": True, "members": result}
        except Exception as e:
            _logger.error("project_members_json error: %s", e)
            return {"error": str(e)}

    # =========================================================================
    # BOARD INVITE — focal person invites a member directly from the board
    # =========================================================================

    @http.route(
        "/customer_support/ticket/<int:ticket_id>/board/invite",
        type="jsonrpc",
        auth="user",
        csrf=True,
    )
    def board_invite_member(self, ticket_id, **kw):
        """Add a team member from the board and send them the board invite email."""
        try:
            name  = (kw.get("name") or "").strip()
            email = (kw.get("email") or "").strip()

            if not name:
                return {"error": "Name is required"}
            if not email:
                return {"error": "Email is required"}

            ticket = request.env["customer.support"].sudo().browse(ticket_id)
            if not ticket.exists():
                return {"error": "Ticket not found"}

            project_id = ticket.project_id.id if ticket.project_id else False
            if not project_id:
                return {"error": "This ticket is not linked to a project"}

            role = kw.get("role") or "other"
            # Auto-link to existing Odoo user if their email matches
            existing_user = request.env["res.users"].sudo().search(
                [("email", "=", email), ("active", "=", True)], limit=1
            )
            member_vals = {"project_id": project_id, "role": role}
            if existing_user:
                member_vals["user_id"] = existing_user.id
            else:
                member_vals["member_name"] = name
                member_vals["member_email"] = email
            member = request.env["customer_support.project.member"].sudo().create(member_vals)

            # Ensure the ticket has a board token
            if not ticket.board_token:
                ticket.sudo().write({"board_token": secrets.token_urlsafe(32)})

            # Send board invite email
            base_url = request.env["ir.config_parameter"].sudo().get_param("web.base.url", "").rstrip("/")
            board_url = f"{base_url}/board/{ticket.board_token}"
            try:
                sent = EmailService.send_board_invite(name, email, ticket, board_url)
                if not sent:
                    _logger.warning(
                        "Board invite email was not sent for ticket %s to %s",
                        ticket.id,
                        email,
                    )
            except Exception as mail_err:
                _logger.warning("Board invite email failed: %s", mail_err)

            _log(ticket_id, "board_invite",
                 f'{request.env.user.name} invited {name} ({email}) to the board',
                 actor=request.env.user)
            display_name = member.user_id.name if member.user_id else name
            display_email = member.user_id.email if member.user_id else email
            initials = "".join(p[0].upper() for p in display_name.split()[:2]) if display_name else "?"
            return {
                "success": True,
                "member": {
                    "user_id": member.user_id.id if member.user_id else None,
                    "name": display_name,
                    "email": display_email,
                    "initials": initials,
                    "role": member.role_label or "Other",
                    "role_key": member.role,
                    "member_id": member.id,
                },
            }

        except Exception as e:
            _logger.error("board_invite_member error: %s", e)
            return {"error": str(e)}

    # =========================================================================
    # ACTIVITY LOG — live fetch endpoint
    # =========================================================================

    @http.route(
        "/customer_support/ticket/<int:ticket_id>/activity_log",
        type="jsonrpc",
        auth="user",
        csrf=False,
    )
    def activity_log_json(self, ticket_id, **kw):
        """Return the latest activity log entries for the board's live-refresh."""
        try:
            log_recs = (
                request.env["customer.support.ticket.log"]
                .sudo()
                .search([("ticket_id", "=", ticket_id)], order="timestamp desc", limit=40)
            )
            return {
                "success": True,
                "entries": [
                    {
                        "event_type": l.event_type,
                        "message": l.summary,
                        "detail": l.detail or "",
                        "actor": l.actor_id.name if l.actor_id else "",
                        "timestamp": l.timestamp.strftime("%b %d, %H:%M") if l.timestamp else "",
                    }
                    for l in log_recs
                ],
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # =========================================================================
    # ATTACHMENT / DOCUMENT DOWNLOAD FOR PUBLIC BOARD TOKEN
    # =========================================================================

    @http.route(
        "/customer_support/attachment/<int:att_id>/download",
        type="http",
        auth="public",
        website=True,
    )
    def download_attachment(self, att_id, **kw):
        try:
            token = kw.get('board_token') or request.params.get('board_token')
            att = request.env['ir.attachment'].sudo().browse(att_id)
            if not att.exists():
                return request.not_found()
            if att.res_model != 'customer.support':
                return request.not_found()
            ticket = request.env['customer.support'].sudo().browse(att.res_id)
            if not ticket.exists():
                return request.not_found()
            if not self._authorize_for_ticket(ticket, {'board_token': token}):
                return request.make_response('Access denied', status=403)

            data_b64 = att.sudo().datas or ''
            if not data_b64:
                return request.not_found()
            import base64
            content = base64.b64decode(data_b64)
            headers = [
                ('Content-Type', att.mimetype or 'application/octet-stream'),
                ('Content-Disposition', f'attachment; filename="{att.name or "attachment"}"'),
            ]
            return request.make_response(content, headers)
        except Exception as e:
            _logger.error('download_attachment error: %s', e)
            return request.make_response('Error', status=500)

    @http.route(
        "/customer_support/document/<int:doc_id>/download",
        type="http",
        auth="public",
        website=True,
    )
    def download_document(self, doc_id, **kw):
        try:
            token = kw.get('board_token') or request.params.get('board_token')
            doc = request.env['dc.knowledge.document'].sudo().browse(doc_id)
            if not doc.exists():
                return request.not_found()
            # Find ticket that has this board token and belongs to same project
            ticket = request.env['customer.support'].sudo().search([('board_token', '=', token)], limit=1) if token else None
            if not ticket or not ticket.project_id or ticket.project_id.id != doc.project_id.id:
                return request.make_response('Access denied', status=403)
            # Try common file fields
            data_b64 = getattr(doc.sudo(), 'file', None) or getattr(doc.sudo(), 'datas', None) or getattr(doc.sudo(), 'data', None) or ''
            if not data_b64:
                return request.not_found()
            import base64
            content = base64.b64decode(data_b64)
            fname = doc.filename or doc.name or f'document_{doc.id}'
            headers = [
                ('Content-Type', doc.file_type or 'application/octet-stream'),
                ('Content-Disposition', f'attachment; filename="{fname}"'),
            ]
            return request.make_response(content, headers)
        except Exception as e:
            _logger.error('download_document error: %s', e)
            return request.make_response('Error', status=500)

    # =========================================================================
    # REPLY TO CUSTOMER
    # =========================================================================

    @http.route(
        "/customer_support/ticket/<int:ticket_id>/reply_customer",
        type="jsonrpc",
        auth="user",
        csrf=True,
    )
    def reply_customer(self, ticket_id, **kw):
        """Send a message from the focal/team directly to the customer."""
        try:
            message = (kw.get("message") or "").strip()
            if not message:
                return {"error": "Message is required"}

            ticket = request.env["customer.support"].sudo().browse(ticket_id)
            if not ticket.exists():
                return {"error": "Ticket not found"}

            customer_email = ticket.customer_id.email if ticket.customer_id else None
            if not customer_email:
                return {"error": "Customer has no email address on file"}

            EmailService.send_customer_reply(ticket, message, request.env.user.name)
            # Persist the same reply in the ticket chatter so it is visible in customer detail views.
            ticket.message_post(
                body=message,
                message_type="comment",
                subtype_xmlid="mail.mt_comment",
                author_id=request.env.user.partner_id.id,
            )
            short_msg = (message[:60] + "…") if len(message) > 60 else message
            _log(ticket_id, "board_reply",
                 f'{request.env.user.name} sent a reply to customer',
                 actor=request.env.user, detail=short_msg)
            return {"success": True}

        except Exception as e:
            _logger.error("reply_customer error: %s", e)
            return {"error": str(e)}

    @http.route(
        "/customer_support/ticket/<int:ticket_id>/conversation/messages",
        type="jsonrpc",
        auth="user",
        csrf=True,
    )
    def conversation_messages(self, ticket_id, **kw):
        """Return ticket conversation thread for focal-side chat UI."""
        try:
            user = request.env.user
            if not _require_focal(user):
                return {"success": False, "error": "Access denied"}

            ticket = request.env["customer.support"].sudo().browse(ticket_id)
            if not ticket.exists():
                return {"success": False, "error": "Ticket not found"}

            return {
                "success": True,
                "messages": _conversation_messages(ticket, user),
            }
        except Exception as e:
            _logger.error("conversation_messages error: %s", e)
            return {"success": False, "error": str(e)}

    # =========================================================================
    # TASK CHECKLIST CRUD
    # =========================================================================

    @http.route(
        "/customer_support/ticket/task/<int:task_id>/checklist/add",
        type="jsonrpc",
        auth="public",
        csrf=True,
    )
    def add_checklist_item(self, task_id, **kw):
        try:
            name = (kw.get("name") or "").strip()
            if not name:
                return {"error": "Item text is required"}

            task = request.env["customer_support.ticket.task"].sudo().browse(task_id)
            if not task.exists():
                return {"error": "Task not found"}

            # Checklist editing is focal-only.
            if request.env.user.id == request.env.ref('base.public_user').id or not _require_focal(request.env.user):
                return {"error": "Access denied"}

            last = request.env["customer_support.task.checklist"].sudo().search(
                [("task_id", "=", task_id)], order="sequence desc", limit=1
            )
            seq = (last.sequence + 10) if last else 10

            item = request.env["customer_support.task.checklist"].sudo().create({
                "task_id": task_id,
                "name": name,
                "sequence": seq,
            })
            ticket_id = task.ticket_id.id
            _log(ticket_id, "board_checklist_add",
                 f'{request.env.user.name} added checklist item "{name}" to task "{task.name}"',
                 actor=request.env.user)
            return {"success": True, "item": {"id": item.id, "name": item.name, "is_done": False}}

        except Exception as e:
            _logger.error("add_checklist_item error: %s", e)
            return {"error": str(e)}

    @http.route(
        "/customer_support/ticket/task/checklist/<int:item_id>/toggle",
        type="jsonrpc",
        auth="public",
        csrf=True,
    )
    def toggle_checklist_item(self, item_id, **kw):
        try:
            item = request.env["customer_support.task.checklist"].sudo().browse(item_id)
            if not item.exists():
                return {"error": "Item not found"}
            if request.env.user.id == request.env.ref('base.public_user').id or not _require_focal(request.env.user):
                return {"error": "Access denied"}
            item.write({"is_done": not item.is_done})
            if item.is_done:
                ticket_id = item.task_id.ticket_id.id
                _log(ticket_id, "board_checklist_done",
                     f'{request.env.user.name} checked off "{item.name}" in task "{item.task_id.name}"',
                     actor=request.env.user)
            return {"success": True, "is_done": item.is_done}
        except Exception as e:
            _logger.error("toggle_checklist_item error: %s", e)
            return {"error": str(e)}

    @http.route(
        "/customer_support/ticket/task/checklist/<int:item_id>/delete",
        type="jsonrpc",
        auth="public",
        csrf=True,
    )
    def delete_checklist_item(self, item_id, **kw):
        try:
            item = request.env["customer_support.task.checklist"].sudo().browse(item_id)
            if not item.exists():
                return {"error": "Item not found"}
            if request.env.user.id == request.env.ref('base.public_user').id or not _require_focal(request.env.user):
                return {"error": "Access denied"}
            item.unlink()
            return {"success": True}
        except Exception as e:
            _logger.error("delete_checklist_item error: %s", e)
            return {"error": str(e)}

    @http.route(
        "/customer_support/ticket/task/<int:task_id>/note/add",
        type="jsonrpc",
        auth="public",
        csrf=True,
    )
    def add_task_note(self, task_id, **kw):
        try:
            message = (kw.get("message") or "").strip()
            if not message:
                return {"error": "Note is required"}

            task = request.env["customer_support.ticket.task"].sudo().browse(task_id)
            if not task.exists():
                return {"error": "Task not found"}

            if not self._authorize_for_ticket(task.ticket_id, kw):
                return {"error": "Access denied"}

            user = request.env.user
            author_name = (kw.get("author_name") or "").strip()
            if user.id != request.env.ref("base.public_user").id:
                author_name = user.name

            note = request.env["customer_support.task.note"].sudo().create({
                "task_id": task.id,
                "user_id": user.id if user.id != request.env.ref("base.public_user").id else False,
                "author_name": author_name or False,
                "message": message,
            })

            _log(
                task.ticket_id.id,
                "board_task_note",
                f'{author_name or "Board Member"} added a resolving note to task "{task.name}"',
                actor=user if user.id != request.env.ref("base.public_user").id else None,
                detail=message[:120],
            )

            return {
                "success": True,
                "note": {
                    "id": note.id,
                    "author": note.user_id.name if note.user_id else (note.author_name or "Board Member"),
                    "author_id": note.user_id.id if note.user_id else False,
                    "message": note.message,
                    "created": note.create_date.strftime("%b %d, %Y %H:%M") if note.create_date else "",
                },
            }

        except Exception as e:
            _logger.error("add_task_note error: %s", e)
            return {"error": str(e)}
