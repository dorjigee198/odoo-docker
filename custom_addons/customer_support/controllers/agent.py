# -*- coding: utf-8 -*-
"""
Support Agent (Focal Person) Dashboard Controller
==================================================
Handles the dashboard route for internal users (focal persons / support agents):
  - Displays tickets assigned to the logged-in agent
  - Shows ticket status counts and analytics
  - Redirects admins and customers to their own dashboards
  - Provides SLA alerts JSON endpoint for the bell notification dropdown
  - Provides live ticket list JSON endpoint for polling

Access: Authenticated internal users (base.group_user).
Admins and portal users are redirected away automatically.
"""

import logging
import json
from odoo import http, fields
from odoo.http import request
import werkzeug

_logger = logging.getLogger(__name__)


class CustomerSupportAgent(http.Controller):
    """
    Handles the support agent (focal person) dashboard.
    Only internal users reach this view — admins and customers
    are redirected to their respective dashboards.
    """

    def _support_notif_param_key(self):
        return f"customer_support.support_notif_read_keys.{request.env.user.id}"

    def _load_support_read_keys(self):
        raw = (
            request.env["ir.config_parameter"]
            .sudo()
            .get_param(self._support_notif_param_key())
            or "[]"
        )
        try:
            keys = json.loads(raw)
            if isinstance(keys, list):
                return set(keys)
        except Exception:
            _logger.warning("Failed to parse support notification read-state payload; using empty set.")
        return set()

    def _save_support_read_keys(self, keys):
        trimmed = list(keys)[-1000:]
        request.env["ir.config_parameter"].sudo().set_param(
            self._support_notif_param_key(),
            json.dumps(trimmed),
        )

    def _build_support_sla_alerts(self, user, now):
        """Build SLA/assignment alerts with stable internal keys for read persistence."""
        tickets = (
            request.env["customer.support"]
            .sudo()
            .search(
                [
                    ("assigned_to", "=", user.id),
                    ("state", "not in", ["resolved", "closed"]),
                ]
            )
        )

        alerts = []
        for ticket in tickets:
            project_name = (
                ticket.project_id.name
                if "project_id" in ticket._fields and ticket.project_id
                else "General"
            )
            remaining_seconds = None
            live_status = "on_track"
            if ticket.sla_deadline:
                remaining_seconds = (ticket.sla_deadline - now).total_seconds()
                if remaining_seconds <= 0:
                    live_status = "breached"
                elif remaining_seconds <= 2 * 3600:
                    live_status = "at_risk"
                else:
                    if ticket.assigned_date:
                        total_seconds = (
                            ticket.sla_deadline - ticket.assigned_date
                        ).total_seconds()
                        pct_remaining = (
                            (remaining_seconds / total_seconds * 100)
                            if total_seconds > 0
                            else 100
                        )
                        live_status = "at_risk" if pct_remaining <= 20 else "on_track"

            if live_status in ["at_risk", "breached"]:
                if remaining_seconds <= 0:
                    over = abs(remaining_seconds)
                    h = int(over // 3600)
                    m = int((over % 3600) // 60)
                    time_display = (
                        f"{h}h {m}m past deadline" if h > 0 else f"{m}m past deadline"
                    )
                else:
                    h = int(remaining_seconds // 3600)
                    m = int((remaining_seconds % 3600) // 60)
                    time_display = (
                        f"{h}h {m}m remaining" if h > 0 else f"{m}m remaining"
                    )

                alert_key = "sla:%s:%s:%s" % (
                    ticket.id,
                    fields.Datetime.to_string(ticket.sla_deadline) or "",
                    live_status,
                )

                alerts.append(
                    {
                        "_key": alert_key,
                        "ticket_id": ticket.id,
                        "ticket_name": ticket.name,
                        "subject": ticket.subject or "(No subject)",
                        "project_name": project_name,
                        "alert_type": "sla",
                        "sla_status": live_status,
                        "time_display": time_display,
                        "policy_name": (
                            ticket.sla_policy_id.name if ticket.sla_policy_id else "SLA"
                        ),
                    }
                )
                continue

            # Also show recent assignments even when SLA is still on track.
            # This gives focal users immediate visibility when new tickets are assigned.
            if not ticket.assigned_date:
                continue
            age_seconds = (now - ticket.assigned_date).total_seconds()
            if age_seconds < 0 or age_seconds > 24 * 3600:
                continue

            ah = int(age_seconds // 3600)
            am = int((age_seconds % 3600) // 60)
            assigned_display = (
                f"assigned {ah}h {am}m ago" if ah > 0 else f"assigned {am}m ago"
            )
            assigned_key = "assign:%s:%s" % (
                ticket.id,
                fields.Datetime.to_string(ticket.assigned_date) or "",
            )
            alerts.append(
                {
                    "_key": assigned_key,
                    "ticket_id": ticket.id,
                    "ticket_name": ticket.name,
                    "subject": ticket.subject or "(No subject)",
                    "project_name": project_name,
                    "alert_type": "assignment",
                    "sla_status": "on_track",
                    "time_display": assigned_display,
                    "policy_name": (
                        ticket.sla_policy_id.name if ticket.sla_policy_id else "SLA"
                    ),
                }
            )

        priority = {"breached": 0, "at_risk": 1, "on_track": 2}
        alerts.sort(key=lambda a: priority.get(a.get("sla_status"), 3))
        return alerts

    # =========================================================================
    # SUPPORT AGENT DASHBOARD
    # =========================================================================

    @http.route(
        "/customer_support/support_dashboard", type="http", auth="public", website=True
    )
    def support_agent_dashboard(self, **kw):
        """
        Support Agent Dashboard - Main view for focal persons.
        Access: Authenticated internal users (focal persons)
        """
        try:
            user = request.env.user

            if user.id == request.env.ref("base.public_user").id:
                response = request.render(
                    "customer_support.portal_login_page",
                    {
                        "error": "Please login to access dashboard",
                        "success": "",
                        "redirect": "/customer_support/support_dashboard",
                    },
                )
                response.headers["Cache-Control"] = (
                    "no-store, no-cache, must-revalidate, max-age=0"
                )
                return response

            if user.has_group("base.group_system"):
                return werkzeug.utils.redirect("/customer_support/admin_dashboard")

            if user.has_group("base.group_portal"):
                return werkzeug.utils.redirect("/customer_support/dashboard")

            tickets = (
                request.env["customer.support"]
                .sudo()
                .search([("assigned_to", "=", user.id)])
                .sorted(key=lambda r: r.create_date, reverse=True)
            )

            _logger.info(f"========== TICKETS FOR DASHBOARD ==========")
            _logger.info(f"User: {user.name} (ID: {user.id})")
            _logger.info(f"Found {len(tickets)} tickets")
            for t in tickets:
                _logger.info(
                    f"  - Ticket {t.id}: {t.name} | "
                    f"State: {t.state} | Priority: {t.priority}"
                )
            _logger.info(f"===========================================")

            ticket_counts = {
                "new": len(tickets.filtered(lambda t: t.state == "new")),
                "assigned": len(tickets.filtered(lambda t: t.state == "assigned")),
                "in_progress": len(
                    tickets.filtered(lambda t: t.state == "in_progress")
                ),
                "resolved": len(tickets.filtered(lambda t: t.state == "resolved")),
                "closed": len(tickets.filtered(lambda t: t.state == "closed")),
                "total": len(tickets),
            }

            analytics = {}
            performance = {}
            try:
                dashboard_model = request.env["customer_support.dashboard"]
                analytics = dashboard_model.get_ticket_analytics(user.id)
                performance = dashboard_model.get_user_performance(user.id)
            except Exception as e:
                _logger.warning(f"Support dashboard analytics failed: {str(e)}")
                open_tickets = (
                    ticket_counts.get("new", 0)
                    + ticket_counts.get("assigned", 0)
                    + ticket_counts.get("in_progress", 0)
                )
                analytics = {
                    "open_tickets": open_tickets,
                    "total_tickets": ticket_counts.get("total", 0),
                    "high_priority": 0,
                    "urgent": 0,
                    "avg_open_hours": 0,
                    "total_hours": 0,
                    "avg_high_hours": 0,
                    "avg_urgent_hours": 0,
                    "resolved_tickets": ticket_counts.get("resolved", 0)
                    + ticket_counts.get("closed", 0),
                    "solve_rate": 0,
                    "high_resolved": 0,
                    "urgent_resolved": 0,
                }
                performance = {
                    "today_closed": 0,
                    "avg_resolve_rate": 0,
                    "daily_target": 80.00,
                    "achievement": 0,
                    "sample_performance": 85.00,
                }

            response = request.render(
                "customer_support.support_agent_dashboard",
                {
                    "user": user,
                    "tickets": tickets,
                    "ticket_counts": ticket_counts,
                    "analytics": analytics,
                    "performance": performance,
                    "page_name": "support_dashboard",
                },
            )
            response.headers["Cache-Control"] = (
                "no-store, no-cache, must-revalidate, max-age=0"
            )
            return response

        except Exception as e:
            _logger.error(f"Support dashboard error: {str(e)}")
            response = request.render(
                "customer_support.portal_login_page",
                {
                    "error": "Error loading support dashboard",
                    "success": "",
                    "redirect": "/customer_support/support_dashboard",
                },
            )
            response.headers["Cache-Control"] = (
                "no-store, no-cache, must-revalidate, max-age=0"
            )
            return response

    # =========================================================================
    # LIVE TICKET LIST — Polled every 20 s by the focal dashboard frontend
    # =========================================================================

    @http.route(
        "/customer_support/dashboard/tickets",
        type="http",
        auth="user",
        website=True,
        csrf=False,
    )
    def dashboard_tickets(self, **kw):
        """
        Returns the current focal user's assigned tickets as JSON.
        Polled every 20 s by the dashboard JS so that newly assigned
        tickets (state = 'assigned') appear in the Kanban "New" column
        and the list view without requiring a page refresh.
        """
        try:
            user = request.env.user

            tickets = (
                request.env["customer.support"]
                .sudo()
                .search(
                    [("assigned_to", "=", user.id)],
                    order="create_date desc",
                )
            )

            ticket_list = []
            for t in tickets:
                ticket_list.append(
                    {
                        "id": t.id,
                        "name": t.name or "",
                        "subject": t.subject or "",
                        "state": t.state or "new",
                        "priority": t.priority or "low",
                        "customer_id": t.customer_id.id if t.customer_id else None,
                        "customer_name": (
                            t.customer_id.name if t.customer_id else "Unknown"
                        ),
                        "create_date": (
                            t.create_date.strftime("%b %d, %I:%M %p")
                            if t.create_date
                            else "N/A"
                        ),
                    }
                )

            _logger.info(
                f"Ticket poll — {user.name} (ID: {user.id}): {len(ticket_list)} tickets"
            )

            return request.make_response(
                json.dumps({"tickets": ticket_list}),
                headers=[("Content-Type", "application/json")],
            )

        except Exception as e:
            _logger.error(f"Dashboard tickets poll error: {str(e)}")
            return request.make_response(
                json.dumps({"tickets": [], "error": str(e)}),
                headers=[("Content-Type", "application/json")],
            )

    # =========================================================================
    # LIVE ANALYTICS — Polled every 15 s by the focal dashboard frontend
    # =========================================================================

    @http.route(
        "/customer_support/dashboard/analytics",
        type="http",
        auth="user",
        website=True,
        csrf=False,
    )
    def dashboard_analytics(self, **kw):
        """
        Returns analytics + performance JSON for the overview cards.
        Polled every 15 s by the dashboard JS.
        """
        try:
            user = request.env.user

            analytics = {}
            performance = {}
            try:
                dashboard_model = request.env["customer_support.dashboard"]
                analytics = dashboard_model.get_ticket_analytics(user.id)
                performance = dashboard_model.get_user_performance(user.id)
            except Exception as e:
                _logger.warning(f"Analytics model error: {str(e)}")
                tickets = (
                    request.env["customer.support"]
                    .sudo()
                    .search([("assigned_to", "=", user.id)])
                )
                open_count = len(
                    tickets.filtered(
                        lambda t: t.state in ["new", "assigned", "in_progress"]
                    )
                )
                resolved_count = len(
                    tickets.filtered(lambda t: t.state in ["resolved", "closed"])
                )
                total = len(tickets)
                analytics = {
                    "open_tickets": open_count,
                    "total_tickets": total,
                    "high_priority": len(
                        tickets.filtered(lambda t: t.priority == "high")
                    ),
                    "urgent": len(tickets.filtered(lambda t: t.priority == "urgent")),
                    "avg_open_hours": 0,
                    "total_hours": 0,
                    "avg_high_hours": 0,
                    "avg_urgent_hours": 0,
                    "resolved_tickets": resolved_count,
                    "solve_rate": (
                        round(resolved_count / total * 100, 1) if total else 0
                    ),
                    "high_resolved": 0,
                    "urgent_resolved": 0,
                }
                performance = {
                    "today_closed": 0,
                    "avg_resolve_rate": 0,
                    "daily_target": 80.00,
                    "achievement": 0,
                    "sample_performance": 85.00,
                }

            return request.make_response(
                json.dumps({"analytics": analytics, "performance": performance}),
                headers=[("Content-Type", "application/json")],
            )

        except Exception as e:
            _logger.error(f"Dashboard analytics error: {str(e)}")
            return request.make_response(
                json.dumps({"analytics": {}, "performance": {}, "error": str(e)}),
                headers=[("Content-Type", "application/json")],
            )

    # =========================================================================
    # SLA ALERTS — Bell notification endpoint, polled every 30 s
    # =========================================================================

    @http.route(
        "/customer_support/dashboard/sla_alerts",
        type="http",
        auth="user",
        website=True,
        csrf=False,
    )
    def sla_alerts(self, **kw):
        """
        Returns JSON list of SLA at-risk and breached tickets for the
        logged-in agent. Used by the bell notification dropdown in the
        support dashboard.

        SLA status is calculated LIVE from sla_deadline vs now —
        we do NOT rely on the stored sla_status field because it may
        not have been recomputed yet after deadline was set.

        At-risk threshold: less than 20% of total SLA time remaining
        OR less than 2 hours remaining — whichever comes first.
        """
        try:
            user = request.env.user
            now = fields.Datetime.now()

            alerts = self._build_support_sla_alerts(user, now)

            current_keys = {a.get("_key") for a in alerts if a.get("_key")}
            read_keys = self._load_support_read_keys()
            pruned_read = read_keys.intersection(current_keys)
            if pruned_read != read_keys:
                self._save_support_read_keys(pruned_read)

            filtered_alerts = []
            for a in alerts:
                if a.get("_key") in pruned_read:
                    continue
                clean = dict(a)
                clean.pop("_key", None)
                filtered_alerts.append(clean)

            _logger.info(f"SLA alerts for {user.name}: {len(filtered_alerts)} alerts")

            return request.make_response(
                json.dumps({"alerts": filtered_alerts}),
                headers=[("Content-Type", "application/json")],
            )

        except Exception as e:
            _logger.error(f"SLA alerts error: {str(e)}")
            return request.make_response(
                json.dumps({"alerts": [], "error": str(e)}),
                headers=[("Content-Type", "application/json")],
            )

    @http.route(
        "/customer_support/dashboard/sla_alerts/mark_read",
        type="http",
        auth="user",
        methods=["POST"],
        website=True,
        csrf=False,
    )
    def sla_alerts_mark_read(self, **kw):
        """Persist support SLA alerts as read for current user across sessions."""
        try:
            user = request.env.user
            now = fields.Datetime.now()
            alerts = self._build_support_sla_alerts(user, now)
            current_keys = {a.get("_key") for a in alerts if a.get("_key")}

            existing = self._load_support_read_keys()
            self._save_support_read_keys(existing.union(current_keys))

            return request.make_response(
                json.dumps({"success": True}),
                headers=[("Content-Type", "application/json")],
            )
        except Exception as e:
            _logger.error(f"SLA alerts mark_read error: {str(e)}")
            return request.make_response(
                json.dumps({"success": False}),
                headers=[("Content-Type", "application/json")],
                status=500,
            )
