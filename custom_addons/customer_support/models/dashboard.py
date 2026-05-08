# -*- coding: utf-8 -*-
"""
Customer Support Dashboard Model
=================================
Provides analytics and performance metrics for all three portal roles:

  - Admin       → sees stats across ALL tickets in the system
  - Focal Person → sees stats only for tickets ASSIGNED TO them
  - Customer     → sees stats only for tickets THEY CREATED

The correct role is determined by inspecting the user's groups inside
each method, so the same method works correctly regardless of who calls it.

Models:
  - CustomerSupportProject     → support project records
  - ResPartner (inherited)     → adds project_id field to partners
  - CustomerSupportDashboard   → abstract model with analytics methods
"""

from odoo import models, fields, api
from datetime import datetime, timedelta
import logging

_logger = logging.getLogger(__name__)


# =============================================================================
# PROJECT MODEL
# =============================================================================


class CustomerSupportProject(models.Model):
    _name = "customer_support.project"
    _description = "Support Project"

    name = fields.Char(string="Project Name", required=True)
    code = fields.Char(string="Project Code")
    description = fields.Text(string="Description")
    active = fields.Boolean(string="Active", default=True)


# =============================================================================
# EXTEND RES.PARTNER — add project association
# =============================================================================


class ResPartner(models.Model):
    """Extend res.partner to add a project association field."""

    _inherit = "res.partner"

    project_id = fields.Many2one(
        "customer_support.project",
        string="Project",
        help="The project this user/partner is associated with",
    )


# =============================================================================
# DASHBOARD ANALYTICS MODEL
# =============================================================================


class CustomerSupportDashboard(models.AbstractModel):
    _name = "customer_support.dashboard"
    _description = "Customer Support Dashboard Analytics"

    # -------------------------------------------------------------------------
    # PRIVATE HELPERS
    # -------------------------------------------------------------------------

    def _get_tickets_for_user(self, user_id):
        """
        Return the correct ticket recordset based on the user's role.

          - Admin       → ALL tickets in the system
          - Focal Person → tickets where assigned_to == user
          - Customer     → tickets where customer_id == user's partner

        This is the single source of truth for ticket scoping — every
        analytics method calls this instead of building its own domain.
        """
        Ticket = self.env["customer.support"]
        user = self.env["res.users"].browse(user_id)

        try:
            if user.has_group("base.group_system"):
                # Admin — full visibility across all tickets
                _logger.debug(f"Dashboard: admin scope for user {user.name}")
                return Ticket.search([])

            elif user.has_group("base.group_user"):
                # Focal person / support agent — only assigned tickets
                _logger.debug(f"Dashboard: agent scope for user {user.name}")
                return Ticket.search([("assigned_to", "=", user_id)])

            else:
                # Portal user / customer — only their own tickets
                _logger.debug(f"Dashboard: customer scope for user {user.name}")
                return Ticket.search([("customer_id", "=", user.partner_id.id)])

        except Exception as e:
            _logger.error(f"_get_tickets_for_user failed for user {user_id}: {e}")
            return Ticket.browse()  # empty recordset — safe fallback

    # -------------------------------------------------------------------------
    # PUBLIC ANALYTICS METHOD
    # -------------------------------------------------------------------------

    def get_ticket_analytics(self, user_id):
        """
        Return a dict of ticket analytics for the given user.

        Keys returned:
          total_tickets, open_tickets, high_priority, urgent,
          avg_open_hours, total_hours, avg_high_hours, avg_urgent_hours,
          resolved_tickets, solve_rate, high_resolved, urgent_resolved

        Role-aware: uses _get_tickets_for_user() so the numbers are always
        correct regardless of whether the caller is admin, agent, or customer.
        """
        # Safe default — returned on any error so templates never break
        default = {
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
            "urgent_resolved": 0,
        }

        try:
            tickets = self._get_tickets_for_user(user_id)
            total_tickets = len(tickets)

            if total_tickets == 0:
                return default

            # ------------------------------------------------------------------
            # Open tickets — includes all non-terminal states
            # BUG FIX: "assigned" was missing from the original filter
            # ------------------------------------------------------------------
            open_tickets = tickets.filtered(
                lambda t: t.state in ["new", "assigned", "in_progress", "pending"]
            )

            # High priority and urgent — only among OPEN tickets
            high_priority = open_tickets.filtered(lambda t: t.priority == "high")
            urgent_tickets = open_tickets.filtered(lambda t: t.priority == "urgent")

            # Resolved / closed tickets
            resolved_tickets = tickets.filtered(
                lambda t: t.state in ["resolved", "closed"]
            )
            high_resolved = resolved_tickets.filtered(lambda t: t.priority == "high")
            urgent_resolved = resolved_tickets.filtered(
                lambda t: t.priority == "urgent"
            )

            # Solve rate as a percentage
            solve_rate = (
                round(len(resolved_tickets) / total_tickets * 100, 2)
                if total_tickets > 0
                else 0
            )

            # Time-based metrics
            avg_open_hours = self._calc_avg_open_hours(open_tickets)
            total_hours = self._calc_total_hours(tickets)
            avg_high_hours = self._calc_avg_priority_hours(tickets, "high")
            avg_urgent_hours = self._calc_avg_priority_hours(tickets, "urgent")

            result = {
                "total_tickets": total_tickets,
                "open_tickets": len(open_tickets),
                "high_priority": len(high_priority),
                "urgent": len(urgent_tickets),
                "avg_open_hours": avg_open_hours,
                "total_hours": total_hours,
                "avg_high_hours": avg_high_hours,
                "avg_urgent_hours": avg_urgent_hours,
                "resolved_tickets": len(resolved_tickets),
                "solve_rate": solve_rate,
                "high_resolved": len(high_resolved),
                "urgent_resolved": len(urgent_resolved),
            }

            _logger.debug(
                f"Analytics for user {user_id}: "
                f"total={total_tickets}, open={len(open_tickets)}, "
                f"resolved={len(resolved_tickets)}, solve_rate={solve_rate}%"
            )

            return result

        except Exception as e:
            _logger.error(f"get_ticket_analytics failed for user {user_id}: {e}")
            return default

    # -------------------------------------------------------------------------
    # PUBLIC PERFORMANCE METHOD
    # -------------------------------------------------------------------------

    def get_user_performance(self, user_id):
        """
        Return performance metrics for the given user.

        Keys returned:
          today_closed, avg_resolve_rate, daily_target,
          achievement, sample_performance

        Role-aware:
          - Admin / Agent → counts tickets resolved TODAY (assigned_to = user)
          - Customer      → counts their own tickets closed today

        BUG FIX: Original always used assigned_to which returned 0 for customers.
        """
        default = {
            "today_closed": 0,
            "avg_resolve_rate": 0,
            "daily_target": 80.00,
            "achievement": 0,
            "sample_performance": 85.00,
        }

        try:
            user = self.env["res.users"].browse(user_id)
            Ticket = self.env["customer.support"]

            today = fields.Date.today()
            today_start = datetime.combine(today, datetime.min.time())
            today_end = datetime.combine(today, datetime.max.time())
            seven_days_ago = today - timedelta(days=7)

            # ------------------------------------------------------------------
            # Build the base domain depending on role
            # ------------------------------------------------------------------
            if user.has_group("base.group_system"):
                # Admin — system-wide performance
                base_domain = []
            elif user.has_group("base.group_user"):
                # Agent — only their assigned tickets
                base_domain = [("assigned_to", "=", user_id)]
            else:
                # Customer — only their own tickets
                base_domain = [("customer_id", "=", user.partner_id.id)]

            # Tickets closed today
            today_closed = Ticket.search_count(
                base_domain
                + [
                    ("state", "in", ["resolved", "closed"]),
                    ("write_date", ">=", today_start),
                    ("write_date", "<=", today_end),
                ]
            )

            # Tickets created in the last 7 days
            last_week_tickets = Ticket.search(
                base_domain
                + [
                    ("create_date", ">=", seven_days_ago),
                    ("create_date", "<=", today_end),
                ]
            )

            resolved_last_week = last_week_tickets.filtered(
                lambda t: t.state in ["resolved", "closed"]
            )

            # Average resolve rate over the last 7 days
            avg_resolve_rate = (
                round(len(resolved_last_week) / len(last_week_tickets) * 100, 2)
                if len(last_week_tickets) > 0
                else 0
            )

            # Achievement = how close today_closed is to a target of 5 tickets/day
            achievement = round(today_closed / 5 * 100, 2) if today_closed > 0 else 0

            result = {
                "today_closed": today_closed,
                "avg_resolve_rate": avg_resolve_rate,
                "daily_target": 80.00,
                "achievement": achievement,
                "sample_performance": 85.00,
            }

            _logger.debug(
                f"Performance for user {user_id}: "
                f"today_closed={today_closed}, "
                f"avg_resolve_rate={avg_resolve_rate}%"
            )

            return result

        except Exception as e:
            _logger.error(f"get_user_performance failed for user {user_id}: {e}")
            return default

    # -------------------------------------------------------------------------
    # PRIVATE TIME CALCULATION HELPERS
    # -------------------------------------------------------------------------

    def _calc_avg_open_hours(self, open_tickets):
        """
        Calculate the average number of hours tickets have been open.
        Only considers tickets that are still in an open state.
        """
        if not open_tickets:
            return 0

        total_hours = 0
        count = 0
        now = datetime.now()

        for ticket in open_tickets:
            if ticket.create_date:
                delta = now - ticket.create_date
                total_hours += delta.total_seconds() / 3600
                count += 1

        return round(total_hours / count, 2) if count > 0 else 0

    def _calc_total_hours(self, tickets):
        """
        Calculate total hours across all tickets from creation to
        resolution (or now if still open).
        """
        if not tickets:
            return 0

        total_hours = 0
        now = datetime.now()

        for ticket in tickets:
            if not ticket.create_date:
                continue
            try:
                # Use resolved_date or closed_date if available, else now
                end_date = ticket.resolved_date or ticket.closed_date or now
            except Exception:
                end_date = now

            delta = end_date - ticket.create_date
            total_hours += delta.total_seconds() / 3600

        return round(total_hours, 2)

    def _calc_avg_priority_hours(self, tickets, priority):
        """
        Calculate the average hours spent on tickets of a specific priority.
        Used for high-priority and urgent SLA tracking.
        """
        if not tickets:
            return 0

        priority_tickets = tickets.filtered(lambda t: t.priority == priority)
        if not priority_tickets:
            return 0

        total_hours = 0
        count = 0
        now = datetime.now()

        for ticket in priority_tickets:
            if not ticket.create_date:
                continue
            try:
                end_date = ticket.resolved_date or ticket.closed_date or now
            except Exception:
                end_date = now

            delta = end_date - ticket.create_date
            total_hours += delta.total_seconds() / 3600
            count += 1

        return round(total_hours / count, 2) if count > 0 else 0
