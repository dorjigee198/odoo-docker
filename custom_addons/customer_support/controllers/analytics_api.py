# -*- coding: utf-8 -*-
"""
Analytics API Controller
========================
Provides a single JSON endpoint that returns real-time dashboard analytics
and performance metrics for the currently authenticated user.

The response is role-aware:
  - Admin       → system-wide stats (all tickets)
  - Focal Person → stats for tickets assigned to them
  - Customer     → stats for their own tickets

Used by the dashboard auto-refresh JS to update stat cards without a full
page reload.

Route: GET /customer_support/dashboard/analytics
Auth:  user (must be logged in)
"""

import json
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class DashboardAnalyticsAPI(http.Controller):

    @http.route(
        "/customer_support/dashboard/analytics",
        type="http",
        auth="user",
        methods=["GET"],
        website=True,
        csrf=False,
    )
    def get_analytics(self, **kwargs):
        """
        Live Analytics Endpoint
        Returns JSON with analytics + performance for the current user.

        Response shape:
        {
            "analytics": {
                "total_tickets": 0,
                "open_tickets": 0,
                "high_priority": 0,
                "urgent": 0,
                "avg_open_hours": 0,
                "total_hours": 0,
                "avg_high_hours": 0,
                "avg_urgent_hours": 0,
                "resolved_tickets": 0,
                "solve_rate": 0,
                "high_resolved": 0,
                "urgent_resolved": 0
            },
            "performance": {
                "today_closed": 0,
                "avg_resolve_rate": 0,
                "daily_target": 80.0,
                "achievement": 0,
                "sample_performance": 85.0
            },
            "ticket_counts": {
                "new": 0,
                "assigned": 0,
                "in_progress": 0,
                "resolved": 0,
                "closed": 0,
                "total": 0
            }
        }
        """
        try:
            user = request.env.user

            # Redirect unauthenticated users
            if user.id == request.env.ref("base.public_user").id:
                return request.make_response(
                    json.dumps({"error": "Not authenticated"}),
                    headers=[("Content-Type", "application/json")],
                    status=401,
                )

            # Fetch analytics and performance from the dashboard model
            dashboard = request.env["customer_support.dashboard"]
            analytics = dashboard.get_ticket_analytics(user.id)
            performance = dashboard.get_user_performance(user.id)

            # Build ticket_counts for the assignment tab quick-stat cards
            # (admin only but safe to return for all roles)
            ticket_counts = self._get_ticket_counts(user)

            payload = {
                "analytics": analytics,
                "performance": performance,
                "ticket_counts": ticket_counts,
            }

            return request.make_response(
                json.dumps(payload),
                headers=[("Content-Type", "application/json")],
            )

        except Exception as e:
            _logger.error(f"Analytics API error: {str(e)}")
            return request.make_response(
                json.dumps({"error": str(e)}),
                headers=[("Content-Type", "application/json")],
                status=500,
            )

    def _get_ticket_counts(self, user):
        """
        Build a status count dict scoped to the user's role.
        Used to update the quick-stat cards in the ticket assignment tab.
        """
        try:
            Ticket = request.env["customer.support"]

            if user.has_group("base.group_system"):
                tickets = Ticket.search([])
            elif user.has_group("base.group_user"):
                tickets = Ticket.search([("assigned_to", "=", user.id)])
            else:
                tickets = Ticket.search([("customer_id", "=", user.partner_id.id)])

            return {
                "new": len(tickets.filtered(lambda t: t.state == "new")),
                "assigned": len(tickets.filtered(lambda t: t.state == "assigned")),
                "in_progress": len(
                    tickets.filtered(lambda t: t.state == "in_progress")
                ),
                "resolved": len(tickets.filtered(lambda t: t.state == "resolved")),
                "closed": len(tickets.filtered(lambda t: t.state == "closed")),
                "total": len(tickets),
            }
        except Exception as e:
            _logger.warning(f"_get_ticket_counts failed: {e}")
            return {
                "new": 0,
                "assigned": 0,
                "in_progress": 0,
                "resolved": 0,
                "closed": 0,
                "total": 0,
            }
