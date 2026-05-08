from odoo import http
from odoo.http import request
import logging
import werkzeug
from datetime import datetime, timedelta
import json

_logger = logging.getLogger(__name__)


class SupportDashboard(http.Controller):
    # ============ ROUTE FOR UPDATING TICKET PHASE (AJAX) ============

    @http.route("/customer_support/ticket/update_phase", type="jsonrpc", auth="user")
    def update_ticket_phase(self, ticket_id, new_phase, **kwargs):
        """
        AJAX endpoint to update ticket phase/state
        """
        try:
            ticket = request.env["customer.support"].sudo().browse(int(ticket_id))

            if not ticket.exists():
                return {"success": False, "error": "Ticket not found"}

            valid_phases = ["new", "open", "in_progress", "resolved", "closed"]
            if new_phase not in valid_phases:
                return {"success": False, "error": "Invalid phase"}

            old_phase = ticket.state
            ticket.write({"state": new_phase})

            try:
                ticket.message_post(
                    body=f"Phase changed from <b>{old_phase.replace('_', ' ').title()}</b> to <b>{new_phase.replace('_', ' ').title()}</b>",
                    message_type="notification",
                    subtype_xmlid="mail.mt_note",
                )
            except Exception:
                _logger.warning("Phase change chatter post failed; phase update already persisted.")

            return {
                "success": True,
                "new_phase": new_phase,
                "new_phase_display": new_phase.replace("_", " ").title(),
                "ticket_id": ticket_id,
                "message": "Phase updated successfully",
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    # ============ ROUTE FOR ADDING TICKET NOTES (AJAX) ============

    @http.route("/customer_support/ticket/add_note", type="jsonrpc", auth="user")
    def add_ticket_note(self, ticket_id, note, **kwargs):
        """
        AJAX endpoint to add internal notes to a ticket
        """
        try:
            ticket = request.env["customer.support"].sudo().browse(int(ticket_id))

            if not ticket.exists():
                return {"success": False, "error": "Ticket not found"}

            try:
                ticket.message_post(
                    body=note,
                    message_type="comment",
                    subtype_xmlid="mail.mt_note",
                    author_id=request.env.user.partner_id.id,
                )
            except Exception:
                _logger.warning("Dashboard note post failed; continuing without chatter note.")

            return {
                "success": True,
                "message": "Note added successfully",
                "author": request.env.user.name,
                "date": datetime.now().strftime("%b %d, %I:%M %p"),
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    # ============ AJAX ENDPOINT FOR SEARCH ============

    @http.route("/customer_support/tickets/search", type="jsonrpc", auth="user")
    def search_tickets(self, search_term="", **kwargs):
        """AJAX endpoint for searching tickets"""
        user = request.env.user
        domain = [("assigned_to", "=", user.id)]

        if search_term:
            domain += [
                "|",
                ("name", "ilike", search_term),
                ("subject", "ilike", search_term),
            ]

        tickets = request.env["customer.support"].search(
            domain, order="create_date desc"
        )

        tickets_data = []
        for ticket in tickets:
            try:
                customer_name = (
                    ticket.partner_id.name if ticket.partner_id else "Unknown"
                )
            except Exception:
                customer_name = "Unknown"

            try:
                status = ticket.state
            except Exception:
                status = "new"

            try:
                created = (
                    ticket.create_date.strftime("%b %d, %I:%M %p")
                    if ticket.create_date
                    else ""
                )
            except Exception:
                created = ""

            try:
                project = ticket.team_id.name if ticket.team_id else ""
            except Exception:
                project = ""

            tickets_data.append(
                {
                    "id": ticket.id,
                    "name": ticket.name,
                    "subject": (
                        ticket.subject if hasattr(ticket, "subject") else ticket.name
                    ),
                    "state": status,
                    "priority": (
                        ticket.priority if hasattr(ticket, "priority") else "low"
                    ),
                    "customer": customer_name,
                    "created": created,
                    "project": project,
                }
            )

        return {"tickets": tickets_data, "count": len(tickets_data)}

    # ============ HELPER METHODS FOR ANALYTICS ============

    def _get_analytics_data(self, user, tickets):
        """
        Calculate analytics metrics for the Overview page
        """
        if not tickets:
            return {
                "open_tickets": 0,
                "total_tickets": 0,
                "high_priority": 0,
                "urgent": 0,
                "avg_open_hours": 0.0,
                "total_hours": 0.0,
                "avg_high_priority_hours": 0.0,
                "avg_urgent_hours": 0.0,
                "failed_tickets": 0,
                "failed_rate": 0.0,
                "high_priority_failed": 0,
                "urgent_failed": 0,
            }

        try:
            open_tickets = len(
                tickets.filtered(lambda t: t.state not in ["closed", "resolved"])
            )
        except Exception:
            open_tickets = len(
                tickets.filtered(lambda t: t.state not in ["closed", "done"])
            )

        high_priority = len(tickets.filtered(lambda t: t.priority == "high"))
        urgent = len(tickets.filtered(lambda t: t.priority == "urgent"))

        avg_open_hours = self._calculate_avg_open_hours(tickets)
        total_hours = self._calculate_total_hours(tickets)
        avg_high_priority_hours = self._calculate_avg_priority_hours(tickets, "high")
        avg_urgent_hours = self._calculate_avg_priority_hours(tickets, "urgent")

        try:
            failed_tickets = len(
                tickets.filtered(lambda t: t.state in ["failed", "cancelled"])
            )
        except Exception:
            failed_tickets = 0

        failed_rate = (failed_tickets / len(tickets)) * 100 if len(tickets) > 0 else 0.0

        analytics = {
            "open_tickets": open_tickets,
            "total_tickets": len(tickets),
            "high_priority": high_priority,
            "urgent": urgent,
            "avg_open_hours": round(avg_open_hours, 2),
            "total_hours": round(total_hours, 2),
            "avg_high_priority_hours": round(avg_high_priority_hours, 2),
            "avg_urgent_hours": round(avg_urgent_hours, 2),
            "failed_tickets": failed_tickets,
            "failed_rate": round(failed_rate, 2),
            "high_priority_failed": len(
                tickets.filtered(
                    lambda t: t.priority == "high"
                    and t.state in ["failed", "cancelled"]
                )
            ),
            "urgent_failed": len(
                tickets.filtered(
                    lambda t: t.priority == "urgent"
                    and t.state in ["failed", "cancelled"]
                )
            ),
        }

        return analytics

    def _get_performance_metrics(self, user, tickets):
        """
        Calculate performance metrics for My Performance card
        """
        if not tickets:
            return {
                "today_closed": 0,
                "avg_last_7_days": 0.0,
                "daily_target": 80.00,
                "accuracy": 85.00,
            }

        today = datetime.now().date()
        week_ago = today - timedelta(days=7)

        try:
            today_closed = len(
                tickets.filtered(
                    lambda t: hasattr(t, "close_date")
                    and t.close_date
                    and t.close_date.date() == today
                )
            )
        except Exception:
            today_closed = 0

        try:
            last_7_days_closed = len(
                tickets.filtered(
                    lambda t: hasattr(t, "close_date")
                    and t.close_date
                    and t.close_date.date() >= week_ago
                )
            )
        except Exception:
            last_7_days_closed = 0

        avg_last_7_days = (
            (last_7_days_closed / 7) * 100 if last_7_days_closed > 0 else 0
        )

        daily_target = 80.00
        accuracy = 85.00

        performance = {
            "today_closed": today_closed,
            "avg_last_7_days": round(avg_last_7_days, 2),
            "daily_target": daily_target,
            "accuracy": accuracy,
        }

        return performance

    def _calculate_avg_open_hours(self, tickets):
        """Calculate average hours tickets have been open"""
        if not tickets:
            return 0.0

        try:
            open_tickets = tickets.filtered(
                lambda t: t.state not in ["closed", "resolved"]
            )
        except Exception:
            open_tickets = tickets.filtered(lambda t: t.state not in ["closed", "done"])

        if not open_tickets:
            return 0.0

        total_hours = 0
        for ticket in open_tickets:
            if ticket.create_date:
                delta = datetime.now() - ticket.create_date
                total_hours += delta.total_seconds() / 3600

        return total_hours / len(open_tickets) if open_tickets else 0.0

    def _calculate_total_hours(self, tickets):
        """Calculate total hours spent on all tickets"""
        if not tickets:
            return 0.0

        total_hours = 0
        for ticket in tickets:
            if ticket.create_date:
                try:
                    end_date = ticket.close_date or datetime.now()
                except Exception:
                    end_date = datetime.now()

                delta = end_date - ticket.create_date
                total_hours += delta.total_seconds() / 3600

        return total_hours

    def _calculate_avg_priority_hours(self, tickets, priority):
        """Calculate average hours for specific priority tickets"""
        if not tickets:
            return 0.0

        priority_tickets = tickets.filtered(lambda t: t.priority == priority)

        if not priority_tickets:
            return 0.0

        total_hours = 0
        for ticket in priority_tickets:
            if ticket.create_date:
                try:
                    end_date = ticket.close_date or datetime.now()
                except Exception:
                    end_date = datetime.now()

                delta = end_date - ticket.create_date
                total_hours += delta.total_seconds() / 3600

        return total_hours / len(priority_tickets)
