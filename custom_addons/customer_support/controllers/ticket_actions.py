# -*- coding: utf-8 -*-
"""
Ticket Actions Controller
=========================
Handles all core ticket interaction routes for the Customer Support Portal:
  - View ticket detail page (with message thread)
  - Assign ticket to a support agent (admin only)
  - Update ticket status (admin or assigned agent)

Customer notifications are created automatically on:
  - assign_ticket   → "assigned" notification
  - update_status   → "status_change" notification
"""

import json
import logging
import threading
import odoo
from odoo import http, fields
from odoo.http import request
from odoo.modules.registry import Registry
import werkzeug

from ..services.email_service import EmailService
from ..services.email_templates import render_assignment_agent, render_assignment_customer

_logger = logging.getLogger(__name__)


def _bg_post_assign(dbname, ticket_id, assigned_user_id, sla_note,
                    agent_email, agent_html, customer_email, customer_html,
                    subject_agent, subject_customer, from_email):
    """Background thread: chatter log + in-app notification + mail queue."""
    try:
        with Registry(dbname).cursor() as cr:
            env = odoo.api.Environment(cr, odoo.SUPERUSER_ID, {})
            ticket = env['customer.support'].browse(ticket_id)
            assigned_user = env['res.users'].browse(assigned_user_id)
            if not ticket.exists():
                return

            ticket.message_post(
                body=f"Ticket assigned to {assigned_user.name}{sla_note}",
                subject="Ticket Assigned",
            )

            try:
                env['customer.support.notification'].create_notification(
                    ticket, 'assigned',
                    f"{ticket.name} has been assigned to {assigned_user.name}",
                )
            except Exception as ne:
                _logger.warning("Background notification failed (ticket %s): %s", ticket_id, ne)

            if agent_email and agent_html:
                env['mail.mail'].sudo().create({
                    'subject': subject_agent,
                    'body_html': agent_html,
                    'email_to': agent_email,
                    'email_from': from_email,
                    'auto_delete': False,
                })
            if customer_email and customer_html:
                env['mail.mail'].sudo().create({
                    'subject': subject_customer,
                    'body_html': customer_html,
                    'email_to': customer_email,
                    'email_from': from_email,
                    'auto_delete': False,
                })
            cr.commit()
            _logger.info("Background assignment notifications done for ticket %s", ticket_id)
    except Exception as e:
        _logger.error("Background assignment failed (ticket %s): %s", ticket_id, e)


STATUS_LABELS = {
    "new": "New",
    "assigned": "Assigned",
    "in_progress": "In Progress",
    "pending": "Pending",
    "resolved": "Resolved",
    "closed": "Closed",
}


class CustomerSupportTicketActions(http.Controller):

    # =========================================================================
    # VIEW TICKET DETAIL
    # =========================================================================

    @http.route(
        "/customer_support/ticket/<int:ticket_id>",
        type="http",
        auth="public",  # changed from "user" → supports public check inside
        website=True,
    )
    def view_ticket(self, ticket_id, **kw):
        try:
            user = request.env.user

            # Redirect unauthenticated (public) users to login, preserving destination
            if user.id == request.env.ref("base.public_user").id:
                return werkzeug.utils.redirect(
                    f"/customer_support/login?redirect=/customer_support/ticket/{ticket_id}"
                )

            ticket = request.env["customer.support"].browse(ticket_id)
            if not ticket.exists():
                return werkzeug.utils.redirect(
                    "/customer_support/dashboard?error=Ticket not found"
                )

            is_admin = user.has_group("base.group_system")
            is_assigned = (
                ticket.assigned_to.id == user.id if ticket.assigned_to else False
            )
            is_customer = ticket.customer_id.id == user.partner_id.id

            # Enforce record-level access before loading related ticket data.
            if not (is_admin or is_assigned or is_customer):
                return werkzeug.utils.redirect(
                    "/customer_support/dashboard?error=Access denied"
                )

            focal_persons = []
            if is_admin:
                focal_persons = request.env["res.users"].search(
                    [("active", "=", True), ("id", "!=", 1)]
                )

            # ── Fetch message thread ──────────────────────────────────────────
            activities = []
            try:
                if hasattr(ticket, "message_ids") and ticket.message_ids:
                    activities = list(
                        ticket.message_ids.filtered(
                            lambda m: m.message_type in ["comment", "notification"]
                        ).sorted(key=lambda r: r.date, reverse=True)
                    )
            except Exception as e:
                _logger.error(f"message_ids failed: {str(e)}")

            if not activities:
                try:
                    messages = (
                        request.env["mail.message"]
                        .sudo()
                        .search(
                            [
                                ("model", "=", "customer.support"),
                                ("res_id", "=", ticket_id),
                                ("message_type", "in", ["comment", "notification"]),
                            ],
                            order="date desc",
                        )
                    )
                    activities = list(messages)
                except Exception as e:
                    _logger.error(f"mail.message search failed: {str(e)}")

            # ── Fetch attachments ─────────────────────────────────────────────
            attachments = []
            try:
                attachments = (
                    request.env["ir.attachment"]
                    .sudo()
                    .search(
                        [
                            ("res_model", "=", "customer.support"),
                            ("res_id", "=", ticket_id),
                        ]
                    )
                )
            except Exception as e:
                _logger.error(f"Attachment fetch failed: {str(e)}")

            # ── Fetch activity log for timeline ───────────────────────────────
            ticket_logs = []
            try:
                ticket_logs = (
                    request.env["customer.support.ticket.log"]
                    .sudo()
                    .search(
                        [("ticket_id", "=", ticket_id)],
                        order="timestamp asc",
                    )
                )
            except Exception as e:
                _logger.error(f"Ticket log fetch failed: {str(e)}")

            _logger.info(
                f"User {user.name} viewing ticket {ticket_id}: {len(activities)} messages"
            )

            return request.render(
                "customer_support.ticket_detail",
                {
                    "user": user,
                    "ticket": ticket,
                    "is_admin": is_admin,
                    "is_assigned": is_assigned,
                    "is_customer": is_customer,
                    "focal_persons": focal_persons,
                    "activities": activities,
                    "activities_count": len(activities),
                    "attachments": attachments,
                    "ticket_logs": ticket_logs,
                    "ticket_logs_count": len(ticket_logs),
                    "success": kw.get("success", ""),
                    "error": kw.get("error", ""),
                    "page_name": "ticket_detail",
                },
            )

        except Exception as e:
            _logger.error(f"View ticket error: {str(e)}")
            return werkzeug.utils.redirect(
                "/customer_support/dashboard?error=Error loading ticket"
            )

    # =========================================================================
    # ASSIGN TICKET
    # =========================================================================

    @http.route(
        "/customer_support/ticket/<int:ticket_id>/assign",
        type="http",
        auth="user",
        methods=["POST"],
        website=False,
        csrf=True,
    )
    def assign_ticket(self, ticket_id, **post):
        def _err(msg):
            return request.make_response(
                json.dumps({"success": False, "error": msg}),
                headers=[("Content-Type", "application/json")],
            )

        try:
            user = request.env.user

            if not user.has_group("base.group_system"):
                return _err("Access denied")

            ticket = request.env["customer.support"].browse(ticket_id)
            if not ticket.exists():
                return _err("Ticket not found")

            post_dict = dict(post) if not isinstance(post, dict) else post
            assigned_to = post_dict.get("assigned_to")
            if not assigned_to:
                return _err("Please select a user to assign"
                )

            assigned_user_id = int(assigned_to)
            assigned_user = request.env["res.users"].browse(assigned_user_id)

            write_vals = {
                "assigned_to": assigned_user_id,
                "state": "assigned",
                "assigned_by": user.id,
                "assigned_date": fields.Datetime.now(),
            }

            # Set project_id from form, or auto-detect from focal person's mapping
            project_id = post_dict.get("project_id", "").strip()
            if project_id:
                write_vals["project_id"] = int(project_id)
            elif not ticket.project_id:
                # Auto-detect: if focal has exactly one project, use it
                member = (
                    request.env["customer_support.project.member"]
                    .sudo()
                    .search([("user_id", "=", assigned_user_id), ("role", "=", "focal_person")], limit=1)
                )
                if member:
                    write_vals["project_id"] = member.project_id.id

            # Also create project.member record if not already mapped
            final_project_id = write_vals.get("project_id") or (ticket.project_id.id if ticket.project_id else None)
            if final_project_id:
                existing = (
                    request.env["customer_support.project.member"]
                    .sudo()
                    .search([
                        ("project_id", "=", final_project_id),
                        ("user_id", "=", assigned_user_id),
                    ], limit=1)
                )
                if not existing:
                    request.env["customer_support.project.member"].sudo().create({
                        "project_id": final_project_id,
                        "user_id": assigned_user_id,
                        "role": "focal_person",
                    })

            # SLA Policy
            sla_policy_id = post_dict.get("sla_policy_id", "").strip()
            sla_note = ""
            if sla_policy_id:
                try:
                    policy = (
                        request.env["customer.support.sla.policy"]
                        .sudo()
                        .browse(int(sla_policy_id))
                    )
                    if policy.exists():
                        deadline = policy.get_deadline_from_now()
                        write_vals["sla_policy_id"] = policy.id
                        write_vals["sla_deadline"] = deadline
                        sla_note = (
                            f" | SLA: {policy.name} "
                            f"(due {deadline.strftime('%Y-%m-%d %H:%M')})"
                        )
                        _logger.info(
                            f"SLA policy '{policy.name}' attached to ticket {ticket_id}. "
                            f"Deadline: {deadline}"
                        )
                except Exception as sla_err:
                    _logger.warning(
                        f"Could not attach SLA policy to ticket {ticket_id}: {sla_err}"
                    )

            ticket.write(write_vals)
            _logger.info(
                f"Ticket {ticket.name} assigned to {assigned_user.name} "
                f"by {user.name}{sla_note}"
            )

            # Pre-render email content now (pure string ops, no SMTP, fast)
            # so the background thread doesn't need request.env
            try:
                agent_email = assigned_user.email or assigned_user.login
                customer_email = ticket.customer_id.email if ticket.customer_id else None
                base_url = EmailService._get_base_url()
                from_email = EmailService._get_default_email_from()
                ticket_url = f"{base_url}/customer_support/ticket/{ticket.id}"
                agent_html = render_assignment_agent(ticket, assigned_user, ticket_url) if agent_email else None
                customer_html = render_assignment_customer(ticket, assigned_user, ticket_url) if customer_email else None
                subject_agent = f"New Ticket Assigned: {ticket.name} - {ticket.subject}"
                subject_customer = f"Your Ticket Has Been Assigned: {ticket.name}"
            except Exception as pre_err:
                _logger.warning("Could not pre-render assignment emails: %s", pre_err)
                agent_email = customer_email = agent_html = customer_html = None
                from_email = "noreply@example.com"
                subject_agent = subject_customer = ""

            # Schedule background thread to run after this transaction commits
            dbname = request.env.cr.dbname
            tid = ticket.id
            uid = assigned_user_id

            def _start_bg():
                threading.Thread(
                    target=_bg_post_assign,
                    args=(dbname, tid, uid, sla_note, agent_email, agent_html,
                          customer_email, customer_html, subject_agent,
                          subject_customer, from_email),
                    daemon=True,
                ).start()

            request.env.cr.postcommit.add(_start_bg)

            return request.make_response(
                json.dumps({
                    "success": True,
                    "ticket_id": ticket.id,
                    "ticket_name": ticket.name,
                    "assigned_to": assigned_user.name,
                    "assigned_to_id": assigned_user_id,
                }),
                headers=[("Content-Type", "application/json")],
            )

        except Exception as e:
            _logger.exception(f"Assign ticket error: {str(e)}")
            return request.make_response(
                json.dumps({"success": False, "error": "Error assigning ticket"}),
                headers=[("Content-Type", "application/json")],
            )

    # =========================================================================
    # UPDATE TICKET STATUS — csrf=False + JSON for kanban drag-drop
    # =========================================================================

    @http.route(
        "/customer_support/ticket/<int:ticket_id>/update_status",
        type="http",
        auth="user",
        methods=["POST"],
        website=True,
        csrf=True,
    )
    def update_ticket_status(self, ticket_id, **post):
        def _is_ajax():
            accept = request.httprequest.headers.get("Accept", "")
            x_req = request.httprequest.headers.get("X-Requested-With", "")
            return "application/json" in accept or x_req == "XMLHttpRequest"

        try:
            user = request.env.user
            ticket = request.env["customer.support"].browse(ticket_id)

            if not ticket.exists():
                if _is_ajax():
                    return request.make_response(
                        json.dumps({"success": False, "error": "Ticket not found"}),
                        headers=[("Content-Type", "application/json")],
                        status=404,
                    )
                return werkzeug.utils.redirect(
                    "/customer_support/dashboard?error=Ticket not found"
                )

            is_admin = user.has_group("base.group_system")
            is_assigned = (
                ticket.assigned_to.id == user.id if ticket.assigned_to else False
            )

            if not (is_admin or is_assigned):
                if _is_ajax():
                    return request.make_response(
                        json.dumps({"success": False, "error": "Access denied"}),
                        headers=[("Content-Type", "application/json")],
                        status=403,
                    )
                return werkzeug.utils.redirect(
                    f"/customer_support/ticket/{ticket_id}?error=Access denied"
                )

            post_dict = dict(post) if not isinstance(post, dict) else post
            new_status = post_dict.get("status")

            if not new_status:
                if _is_ajax():
                    return request.make_response(
                        json.dumps({"success": False, "error": "Status is required"}),
                        headers=[("Content-Type", "application/json")],
                        status=400,
                    )
                return werkzeug.utils.redirect(
                    f"/customer_support/ticket/{ticket_id}?error=Status is required"
                )

            old_status = ticket.state
            update_vals = {"state": new_status}

            if new_status == "resolved":
                update_vals["resolved_date"] = fields.Datetime.now()
            elif new_status == "closed":
                update_vals["closed_date"] = fields.Datetime.now()

            resolution_notes = post_dict.get("resolution_notes", "").strip()
            if resolution_notes:
                update_vals["resolution_notes"] = resolution_notes

            ticket.write(update_vals)
            _logger.info(
                f"Ticket {ticket.name} status: {old_status} → {new_status} by {user.name}"
            )

            # Customer notification
            try:
                old_label = STATUS_LABELS.get(old_status, old_status)
                new_label = STATUS_LABELS.get(new_status, new_status)
                focal_name = (
                    ticket.assigned_to.name if ticket.assigned_to else "Support Team"
                )
                notif_msg = (
                    f"{ticket.name} status changed from {old_label} "
                    f"to {new_label} by {focal_name}"
                )
                request.env["customer.support.notification"].create_notification(
                    ticket, "status_change", notif_msg
                )
            except Exception as ne:
                _logger.warning(f"Could not create status notification: {ne}")

            # Email
            try:
                EmailService.send_status_change_email(ticket, old_status, new_status)
            except Exception as email_error:
                _logger.error(
                    f"Status change email failed for ticket {ticket.name}: {str(email_error)}"
                )

            if _is_ajax():
                return request.make_response(
                    json.dumps(
                        {
                            "success": True,
                            "ticket_id": ticket_id,
                            "old_status": old_status,
                            "new_status": new_status,
                        }
                    ),
                    headers=[("Content-Type", "application/json")],
                )

            return werkzeug.utils.redirect(
                f"/customer_support/ticket/{ticket_id}?success=Status updated successfully"
            )

        except Exception as e:
            _logger.exception(f"Update status error: {str(e)}")
            if _is_ajax():
                return request.make_response(
                    json.dumps({"success": False, "error": str(e)}),
                    headers=[("Content-Type", "application/json")],
                    status=500,
                )
            return werkzeug.utils.redirect(
                f"/customer_support/ticket/{ticket_id}?error=Error updating status"
            )
