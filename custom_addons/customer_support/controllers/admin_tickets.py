# -*- coding: utf-8 -*-
import json
import logging

import werkzeug

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class AdminTicketController(http.Controller):

    @http.route(
        ["/customer_support/admin_view/ticket/<int:ticket_id>"],
        type="http",
        auth="user",
        website=True,
    )
    def admin_ticket_detail_page(self, ticket_id, **kw):
        """Deprecated page route: keep as fallback, redirect to dashboard modal flow."""
        try:
            ticket = request.env["customer.support"].sudo().browse(ticket_id)
            if not ticket.exists():
                _logger.warning(
                    f"Admin tried to access non-existent ticket ID: {ticket_id}"
                )
                return request.render("website.404")

            return request.redirect(
                f"/customer_support/admin_dashboard?tab=ticket-assignment&project_id={ticket.project_id.id if ticket.project_id else 0}&ticket_modal={ticket.id}"
            )

        except Exception as e:
            _logger.error(f"Admin detail route error for ticket {ticket_id}: {str(e)}")
            return request.redirect(
                "/customer_support/admin_dashboard?error=Could not load ticket details"
            )

    @http.route(
        ["/customer_support/admin/ticket/<int:ticket_id>/quick_view"],
        type="http",
        auth="user",
        methods=["GET"],
        website=True,
    )
    def admin_ticket_quick_view(self, ticket_id, **kw):
        """Return ticket details as JSON for admin dashboard popup."""
        user = request.env.user
        if not user.has_group("base.group_system"):
            return request.make_response(
                json.dumps({"success": False, "error": "Access denied"}),
                headers=[("Content-Type", "application/json")],
                status=403,
            )

        ticket = request.env["customer.support"].sudo().browse(ticket_id)
        if not ticket.exists():
            return request.make_response(
                json.dumps({"success": False, "error": "Ticket not found"}),
                headers=[("Content-Type", "application/json")],
                status=404,
            )

        attachments = (
            request.env["ir.attachment"]
            .sudo()
            .search(
                [("res_model", "=", "customer.support"), ("res_id", "=", ticket.id)]
            )
        )
        payload_attachments = []
        for attach in attachments:
            if not attach.access_token:
                attach.sudo().generate_access_token()
            payload_attachments.append(
                {
                    "id": attach.id,
                    "name": attach.name,
                    "url": f"/web/content/{attach.id}?download=true&access_token={attach.access_token}",
                }
            )

        data = {
            "success": True,
            "ticket": {
                "id": ticket.id,
                "name": ticket.name,
                "subject": ticket.subject or "-",
                "description": ticket.description or "No description provided.",
                "customer": ticket.customer_id.name if ticket.customer_id else "-",
                "priority": ticket.priority or "-",
                "state": ticket.state or "-",
                "created_on": (
                    ticket.create_date.strftime("%Y-%m-%d %H:%M")
                    if ticket.create_date
                    else "-"
                ),
                "assigned_to": (
                    ticket.assigned_to.name if ticket.assigned_to else "Unassigned"
                ),
                "project": ticket.project_id.name if ticket.project_id else "-",
                "sla_policy": (
                    ticket.sla_policy_id.name if ticket.sla_policy_id else "No SLA"
                ),
                "sla_status": ticket.sla_status or "-",
                "attachments": payload_attachments,
            },
        }
        return request.make_response(
            json.dumps(data),
            headers=[("Content-Type", "application/json")],
        )
