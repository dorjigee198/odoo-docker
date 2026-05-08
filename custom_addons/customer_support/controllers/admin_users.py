# -*- coding: utf-8 -*-
"""
Admin User Management Controller
=================================
Handles all routes for system administrators related to:
  - Admin dashboard (tickets overview, analytics, user summary)
  - User management list (focal persons and customers)
  - Create user form and submission
  - Edit user form and update
  - Toggle user active/inactive
  - Delete (archive) user
  - Reporting data API endpoints (JSON) for charts + printable reports
  - Admin notifications bell (SLA breaches, unassigned, status changes)
  - Agent workload overview

Access: All routes require the user to be in base.group_system (admin).
Non-admin users are redirected to the customer dashboard.

Email notifications are delegated to EmailService:
  - Welcome email to new customers
  - Welcome email to new focal persons (different template)
"""

import json
import logging
from urllib.parse import urlencode
from datetime import timedelta
from odoo import http, fields
from odoo.http import request
import werkzeug

from ..services.email_service import EmailService

_logger = logging.getLogger(__name__)


class CustomerSupportAdminUsers(http.Controller):
    """
    Handles the admin dashboard and all user management operations.
    Every route in this class is protected — non-admins are redirected away.
    """

    def _admin_notif_param_key(self):
        return f"customer_support.admin_notif_read_keys.{request.env.user.id}"

    def _redirect_user_management_tab(self, success=None, error=None):
        params = {"tab": "user-management"}
        if success:
            params["success"] = success
        if error:
            params["error"] = error
        return werkzeug.utils.redirect(
            f"/customer_support/admin_dashboard?{urlencode(params)}"
        )

    def _load_admin_read_keys(self):
        raw = (
            request.env["ir.config_parameter"]
            .sudo()
            .get_param(self._admin_notif_param_key())
            or "[]"
        )
        try:
            keys = json.loads(raw)
            if isinstance(keys, list):
                return set(keys)
        except Exception:
            _logger.warning("Failed to parse admin notification read-state payload; using empty set.")
        return set()

    def _save_admin_read_keys(self, keys):
        # Cap stored keys to avoid unbounded growth.
        trimmed = list(keys)[-1000:]
        request.env["ir.config_parameter"].sudo().set_param(
            self._admin_notif_param_key(),
            json.dumps(trimmed),
        )

    def _build_admin_notifications(self, now):
        """Build notification payload with stable keys for per-admin read persistence."""
        Ticket = request.env["customer.support"].sudo()

        breached_tickets = Ticket.search(
            [
                ("sla_deadline", "!=", False),
                ("sla_deadline", "<", now),
                ("state", "not in", ["resolved", "closed"]),
            ],
            limit=20,
            order="sla_deadline asc",
        )

        sla_breaches = []
        for t in breached_tickets:
            over_seconds = (now - t.sla_deadline).total_seconds()
            h = int(over_seconds // 3600)
            m = int((over_seconds % 3600) // 60)
            time_display = (
                f"{h}h {m}m past deadline" if h > 0 else f"{m}m past deadline"
            )
            key = f"sla:{t.id}:{fields.Datetime.to_string(t.sla_deadline) or ''}"
            sla_breaches.append(
                {
                    "_key": key,
                    "ticket_id": t.id,
                    "ticket_name": t.name or "",
                    "subject": t.subject or "(No subject)",
                    "agent_name": t.assigned_to.name if t.assigned_to else "Unassigned",
                    "priority": (t.priority or "low").capitalize(),
                    "time_display": time_display,
                }
            )

        unassigned_tickets = Ticket.search(
            [
                ("assigned_to", "=", False),
                ("state", "in", ["new"]),
            ],
            limit=15,
            order="create_date asc",
        )

        unassigned = []
        for t in unassigned_tickets:
            if t.create_date:
                waiting_secs = (now - t.create_date).total_seconds()
                h = int(waiting_secs // 3600)
                m = int((waiting_secs % 3600) // 60)
                waiting = f"{h}h {m}m" if h > 0 else f"{m}m"
            else:
                waiting = "Unknown"
            key = f"unassigned:{t.id}:{fields.Datetime.to_string(t.create_date) or ''}"
            unassigned.append(
                {
                    "_key": key,
                    "ticket_id": t.id,
                    "ticket_name": t.name or "",
                    "subject": t.subject or "(No subject)",
                    "priority": (t.priority or "low").capitalize(),
                    "waiting": waiting,
                    "create_date": (
                        t.create_date.strftime("%b %d, %H:%M") if t.create_date else "—"
                    ),
                }
            )

        cutoff = now - timedelta(minutes=30)
        recently_changed = Ticket.search(
            [
                ("write_date", ">=", cutoff),
                ("state", "not in", ["new"]),
            ],
            limit=15,
            order="write_date desc",
        )

        status_changes = []
        state_labels = {
            "new": "New",
            "assigned": "Assigned",
            "in_progress": "In Progress",
            "resolved": "Resolved",
            "closed": "Closed",
        }
        for t in recently_changed:
            key = f"status:{t.id}:{fields.Datetime.to_string(t.write_date) or ''}"
            status_changes.append(
                {
                    "_key": key,
                    "ticket_id": t.id,
                    "ticket_name": t.name or "",
                    "subject": t.subject or "(No subject)",
                    "new_state": state_labels.get(t.state, t.state),
                    "agent_name": t.assigned_to.name if t.assigned_to else "Unassigned",
                    "changed_at": (
                        t.write_date.strftime("%b %d, %H:%M") if t.write_date else "—"
                    ),
                }
            )

        return {
            "sla_breaches": sla_breaches,
            "unassigned": unassigned,
            "status_changes": status_changes,
        }

    # =========================================================================
    # ADMIN DASHBOARD
    # =========================================================================

    @http.route(
        "/customer_support/admin_dashboard", type="http", auth="user", website=True
    )
    def admin_dashboard(self, **kw):
        user = request.env.user
        if not user.has_group("base.group_system"):
            return werkzeug.utils.redirect("/customer_support/dashboard")

        Ticket = request.env["customer.support"]
        selected_project_id = 0
        raw_project_id = (request.params.get("project_id") or "").strip()
        if raw_project_id.isdigit():
            selected_project_id = int(raw_project_id)
        assignment_filter = (request.params.get("assignment") or "all").strip().lower()
        if assignment_filter not in {"all", "assigned", "unassigned"}:
            assignment_filter = "all"

        base_tickets = Ticket.search([])
        all_projects_ticket_count = len(base_tickets)
        project_ticket_counts = {}
        for t in base_tickets:
            pid = t.project_id.id if t.project_id else 0
            project_ticket_counts[pid] = project_ticket_counts.get(pid, 0) + 1

        if selected_project_id:
            scoped_tickets = base_tickets.filtered(
                lambda t: t.project_id and t.project_id.id == selected_project_id
            )
        else:
            scoped_tickets = base_tickets

        assignment_counts = {
            "all": len(scoped_tickets),
            "assigned": len(scoped_tickets.filtered(lambda t: bool(t.assigned_to))),
            "unassigned": len(scoped_tickets.filtered(lambda t: not t.assigned_to)),
        }

        tickets = Ticket.search([]).sorted(key=lambda r: r.create_date, reverse=True)

        ticket_counts = {
            "new": len(tickets.filtered(lambda t: t.state == "new")),
            "assigned": len(tickets.filtered(lambda t: t.state == "assigned")),
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
            _logger.warning(f"Admin dashboard analytics failed: {str(e)}")
            open_tickets = ticket_counts.get("new", 0) + ticket_counts.get(
                "assigned", 0
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

        all_users = (
            request.env["res.users"]
            .with_context(active_test=False)
            .search(
                [
                    ("id", "not in", [1, request.env.ref("base.public_user").id]),
                ]
            )
            .sorted(key=lambda r: r.create_date, reverse=True)
        )

        active_users_data = []
        deactivated_users_data = []
        for u in all_users:
            if u.has_group("base.group_system"):
                role = "Admin"
                role_class = "primary"
            elif u.has_group("base.group_user"):
                role = "Focal Person"
                role_class = "info"
            elif u.has_group("base.group_portal"):
                role = "Customer"
                role_class = "secondary"
            else:
                role = "User"
                role_class = "secondary"

            item = {
                "id": u.id,
                "name": u.name,
                "email": u.email or u.login,
                "role": role,
                "role_class": role_class,
                "active": u.active,
            }

            if u.active:
                active_users_data.append(item)
            else:
                deactivated_users_data.append(item)

        projects = (
            request.env["customer_support.project"]
            .sudo()
            .search([("active", "=", True)], order="name asc")
        )

        return request.render(
            "customer_support.admin_dashboard",
            {
                "user": user,
                "tickets": tickets,
                "ticket_counts": ticket_counts,
                "users_data": active_users_data,
                "active_users_data": active_users_data,
                "deactivated_users_data": deactivated_users_data,
                "analytics": analytics,
                "performance": performance,
                "projects": projects,
                "selected_project_id": selected_project_id,
                "assignment_filter": assignment_filter,
                "all_projects_ticket_count": all_projects_ticket_count,
                "project_ticket_counts": project_ticket_counts,
                "assignment_counts": assignment_counts,
                "page_name": "admin_dashboard",
            },
        )

    # =========================================================================
    # ADMIN REPORTING DATA API
    # =========================================================================

    @http.route(
        "/customer_support/admin/reporting/data",
        type="http",
        auth="user",
        methods=["GET"],
        website=True,
        csrf=False,
    )
    def admin_reporting_data(self, **kw):
        """
        Returns all reporting data as JSON for the admin reporting tab.
        Supports ?days=7|30|90 filter.
        """
        try:
            user = request.env.user
            if not user.has_group("base.group_system"):
                return request.make_response(
                    json.dumps({"success": False, "error": "Access denied"}),
                    headers=[("Content-Type", "application/json")],
                    status=403,
                )

            days = int(kw.get("days", 30))
            since = fields.Datetime.now() - timedelta(days=days)

            all_tickets = request.env["customer.support"].sudo().search([])
            period_tickets = all_tickets.filtered(
                lambda t: t.create_date and t.create_date >= since
            )

            # ── Status breakdown ─────────────────────────────────────────────
            states = ["new", "assigned", "in_progress", "resolved", "closed"]
            status_breakdown = {
                s: len(all_tickets.filtered(lambda t: t.state == s)) for s in states
            }

            # ── Priority distribution (open tickets only) ─────────────────────
            open_tickets = all_tickets.filtered(
                lambda t: t.state not in ["resolved", "closed"]
            )
            priorities = ["low", "medium", "high", "urgent"]
            priority_dist = {
                p: len(open_tickets.filtered(lambda t: t.priority == p))
                for p in priorities
            }

            # ── Ticket volume trend (daily for selected period) ───────────────
            volume_trend = []
            for i in range(min(days, 30)):
                day_start = fields.Datetime.now() - timedelta(
                    days=(min(days, 30) - 1 - i)
                )
                day_end = day_start + timedelta(days=1)
                day_start = day_start.replace(hour=0, minute=0, second=0)
                day_end = day_end.replace(hour=0, minute=0, second=0)
                count = len(
                    all_tickets.filtered(
                        lambda t, s=day_start, e=day_end: t.create_date
                        and s <= t.create_date < e
                    )
                )
                volume_trend.append(
                    {
                        "date": day_start.strftime("%b %d"),
                        "count": count,
                    }
                )

            # ── Project health ────────────────────────────────────────────────
            projects = (
                request.env["customer_support.project"]
                .sudo()
                .search([("active", "=", True)])
            )
            project_health = []
            for proj in projects:
                proj_tickets = all_tickets.filtered(
                    lambda t: t.project_id.id == proj.id
                )
                proj_period = period_tickets.filtered(
                    lambda t: t.project_id.id == proj.id
                )
                total = len(proj_tickets)
                open_count = len(
                    proj_tickets.filtered(
                        lambda t: t.state not in ["resolved", "closed"]
                    )
                )
                resolved_count = len(
                    proj_tickets.filtered(lambda t: t.state in ["resolved", "closed"])
                )
                breached = len(
                    proj_tickets.filtered(lambda t: t.sla_status == "breached")
                )

                p_urgent = len(proj_tickets.filtered(lambda t: t.priority == "urgent"))
                p_high = len(proj_tickets.filtered(lambda t: t.priority == "high"))
                p_medium = len(proj_tickets.filtered(lambda t: t.priority == "medium"))
                p_low = len(proj_tickets.filtered(lambda t: t.priority == "low"))

                resolved_with_dates = proj_tickets.filtered(
                    lambda t: t.state in ["resolved", "closed"]
                    and t.resolved_date
                    and t.create_date
                )
                avg_resolution = 0
                if resolved_with_dates:
                    total_hours = sum(
                        (t.resolved_date - t.create_date).total_seconds() / 3600
                        for t in resolved_with_dates
                    )
                    avg_resolution = round(total_hours / len(resolved_with_dates), 1)

                if total == 0:
                    health = "green"
                    health_score = 100
                else:
                    resolve_rate = (resolved_count / total) * 100
                    breach_penalty = (
                        min((breached / total) * 50, 50) if total > 0 else 0
                    )
                    health_score = round(max(0, resolve_rate - breach_penalty), 1)
                    health = (
                        "green"
                        if health_score >= 80
                        else "amber" if health_score >= 50 else "red"
                    )

                prev_since = since - timedelta(days=days)
                prev_tickets = proj_tickets.filtered(
                    lambda t: t.create_date and prev_since <= t.create_date < since
                )
                trend = "stable"
                if len(prev_tickets) > 0:
                    change = len(proj_period) - len(prev_tickets)
                    trend = "up" if change > 0 else "down" if change < 0 else "stable"

                project_health.append(
                    {
                        "id": proj.id,
                        "name": proj.name,
                        "code": proj.code or "",
                        "total": total,
                        "open": open_count,
                        "resolved": resolved_count,
                        "breached": breached,
                        "health": health,
                        "health_score": health_score,
                        "avg_resolution_hours": avg_resolution,
                        "trend": trend,
                        "period_count": len(proj_period),
                        "priorities": {
                            "urgent": p_urgent,
                            "high": p_high,
                            "medium": p_medium,
                            "low": p_low,
                        },
                    }
                )

            project_health.sort(key=lambda p: p["health_score"])

            # ── Focal person leaderboard ──────────────────────────────────────
            focal_persons = (
                request.env["res.users"]
                .sudo()
                .search(
                    [
                        ("id", "not in", [1, request.env.ref("base.public_user").id]),
                        ("active", "=", True),
                    ]
                )
            )
            focal_persons = focal_persons.filtered(
                lambda u: u.has_group("base.group_user")
            )

            focal_leaderboard = []
            for fp in focal_persons:
                fp_tickets = all_tickets.filtered(
                    lambda t: t.assigned_to and t.assigned_to.id == fp.id
                )
                fp_period = period_tickets.filtered(
                    lambda t: t.assigned_to and t.assigned_to.id == fp.id
                )
                assigned = len(fp_tickets)
                resolved = len(
                    fp_tickets.filtered(lambda t: t.state in ["resolved", "closed"])
                )
                breached = len(
                    fp_tickets.filtered(lambda t: t.sla_status == "breached")
                )
                open_count = len(
                    fp_tickets.filtered(lambda t: t.state not in ["resolved", "closed"])
                )

                sla_tickets = fp_tickets.filtered(lambda t: t.sla_policy_id)
                sla_ok = len(sla_tickets.filtered(lambda t: t.sla_status != "breached"))
                sla_rate = (
                    round((sla_ok / len(sla_tickets)) * 100, 1)
                    if sla_tickets
                    else 100.0
                )

                resolved_with_dates = fp_tickets.filtered(
                    lambda t: t.state in ["resolved", "closed"]
                    and t.resolved_date
                    and t.create_date
                )
                avg_res = 0
                if resolved_with_dates:
                    total_h = sum(
                        (t.resolved_date - t.create_date).total_seconds() / 3600
                        for t in resolved_with_dates
                    )
                    avg_res = round(total_h / len(resolved_with_dates), 1)

                resolve_rate = (
                    round((resolved / assigned) * 100, 1) if assigned > 0 else 0
                )

                focal_leaderboard.append(
                    {
                        "id": fp.id,
                        "name": fp.name,
                        "assigned": assigned,
                        "resolved": resolved,
                        "open": open_count,
                        "breached": breached,
                        "resolve_rate": resolve_rate,
                        "sla_rate": sla_rate,
                        "avg_resolution_hours": avg_res,
                        "period_resolved": len(
                            fp_period.filtered(
                                lambda t: t.state in ["resolved", "closed"]
                            )
                        ),
                    }
                )

            focal_leaderboard.sort(key=lambda f: f["resolved"], reverse=True)

            # ── Top customers ─────────────────────────────────────────────────
            from collections import Counter

            customer_counts = Counter(
                t.customer_id.name for t in period_tickets if t.customer_id
            )
            top_customers = [
                {"name": name, "count": count}
                for name, count in customer_counts.most_common(10)
            ]

            # ── Summary KPIs ──────────────────────────────────────────────────
            total_period = len(period_tickets)
            resolved_period = len(
                period_tickets.filtered(lambda t: t.state in ["resolved", "closed"])
            )
            breached_period = len(
                period_tickets.filtered(lambda t: t.sla_status == "breached")
            )
            sla_all = period_tickets.filtered(lambda t: t.sla_policy_id)
            sla_compliant = len(sla_all.filtered(lambda t: t.sla_status != "breached"))
            sla_compliance = (
                round((sla_compliant / len(sla_all)) * 100, 1) if sla_all else 100.0
            )

            summary = {
                "total_period": total_period,
                "resolved_period": resolved_period,
                "breached_period": breached_period,
                "sla_compliance": sla_compliance,
                "resolve_rate": (
                    round((resolved_period / total_period) * 100, 1)
                    if total_period > 0
                    else 0
                ),
                "open_tickets": len(
                    all_tickets.filtered(
                        lambda t: t.state not in ["resolved", "closed"]
                    )
                ),
            }

            return request.make_response(
                json.dumps(
                    {
                        "success": True,
                        "days": days,
                        "summary": summary,
                        "status_breakdown": status_breakdown,
                        "priority_dist": priority_dist,
                        "volume_trend": volume_trend,
                        "project_health": project_health,
                        "focal_leaderboard": focal_leaderboard,
                        "top_customers": top_customers,
                    }
                ),
                headers=[("Content-Type", "application/json")],
            )

        except Exception as e:
            _logger.error(f"Admin reporting data error: {e}")
            return request.make_response(
                json.dumps({"success": False, "error": str(e)}),
                headers=[("Content-Type", "application/json")],
            )

    # =========================================================================
    # PRINTABLE REPORT PAGES
    # =========================================================================

    @http.route(
        "/customer_support/admin/report/project/<int:project_id>",
        type="http",
        auth="user",
        website=True,
    )
    def report_project(self, project_id, **kw):
        """Printable Project Health Report for a single project."""
        user = request.env.user
        if not user.has_group("base.group_system"):
            return werkzeug.utils.redirect("/customer_support/dashboard")

        days = int(kw.get("days", 30))
        since = fields.Datetime.now() - timedelta(days=days)

        proj = request.env["customer_support.project"].sudo().browse(project_id)
        if not proj.exists():
            return werkzeug.utils.redirect(
                "/customer_support/admin_dashboard?tab=reporting&error=Project not found"
            )

        all_tickets = (
            request.env["customer.support"]
            .sudo()
            .search([("project_id", "=", project_id)])
        )
        period_tickets = all_tickets.filtered(
            lambda t: t.create_date and t.create_date >= since
        )

        states = ["new", "assigned", "in_progress", "resolved", "closed"]
        status_breakdown = {
            s: len(all_tickets.filtered(lambda t: t.state == s)) for s in states
        }
        priorities = ["urgent", "high", "medium", "low"]
        priority_breakdown = {
            p: len(all_tickets.filtered(lambda t: t.priority == p)) for p in priorities
        }

        breached = all_tickets.filtered(lambda t: t.sla_status == "breached")
        resolved_tickets = all_tickets.filtered(
            lambda t: t.state in ["resolved", "closed"]
        )
        resolved_with_dates = resolved_tickets.filtered(
            lambda t: t.resolved_date and t.create_date
        )
        avg_resolution = 0
        if resolved_with_dates:
            avg_resolution = round(
                sum(
                    (t.resolved_date - t.create_date).total_seconds() / 3600
                    for t in resolved_with_dates
                )
                / len(resolved_with_dates),
                1,
            )

        total = len(all_tickets)
        resolved_count = len(resolved_tickets)
        breach_count = len(breached)
        resolve_rate = round((resolved_count / total) * 100, 1) if total > 0 else 0
        breach_penalty = min((breach_count / total) * 50, 50) if total > 0 else 0
        health_score = round(max(0, resolve_rate - breach_penalty), 1)
        health = (
            "green" if health_score >= 80 else "amber" if health_score >= 50 else "red"
        )

        focal_map = {}
        for t in all_tickets:
            if t.assigned_to:
                fp_id = t.assigned_to.id
                if fp_id not in focal_map:
                    focal_map[fp_id] = {
                        "name": t.assigned_to.name,
                        "assigned": 0,
                        "resolved": 0,
                    }
                focal_map[fp_id]["assigned"] += 1
                if t.state in ["resolved", "closed"]:
                    focal_map[fp_id]["resolved"] += 1
        focal_summary = sorted(
            focal_map.values(), key=lambda x: x["resolved"], reverse=True
        )

        company = request.env["res.company"].sudo().search([], limit=1)

        return request.render(
            "customer_support.report_project_health",
            {
                "user": user,
                "project": proj,
                "company": company,
                "days": days,
                "since": since,
                "all_tickets": all_tickets,
                "period_tickets": period_tickets,
                "status_breakdown": status_breakdown,
                "priority_breakdown": priority_breakdown,
                "breached": breached,
                "avg_resolution": avg_resolution,
                "total": total,
                "resolved_count": resolved_count,
                "breach_count": breach_count,
                "resolve_rate": resolve_rate,
                "health": health,
                "health_score": health_score,
                "focal_summary": focal_summary,
                "generated_at": fields.Datetime.now().strftime("%Y-%m-%d %H:%M"),
            },
        )

    @http.route(
        "/customer_support/admin/report/focal/<int:focal_id>",
        type="http",
        auth="user",
        website=True,
    )
    def report_focal_person(self, focal_id, **kw):
        """Printable Focal Person Performance Report."""
        user = request.env.user
        if not user.has_group("base.group_system"):
            return werkzeug.utils.redirect("/customer_support/dashboard")

        days = int(kw.get("days", 30))
        since = fields.Datetime.now() - timedelta(days=days)

        fp = request.env["res.users"].sudo().browse(focal_id)
        if not fp.exists():
            return werkzeug.utils.redirect(
                "/customer_support/admin_dashboard?tab=reporting&error=User not found"
            )

        all_tickets = (
            request.env["customer.support"]
            .sudo()
            .search([("assigned_to", "=", focal_id)])
        )
        period_tickets = all_tickets.filtered(
            lambda t: t.create_date and t.create_date >= since
        )

        resolved = all_tickets.filtered(lambda t: t.state in ["resolved", "closed"])
        open_tickets = all_tickets.filtered(
            lambda t: t.state not in ["resolved", "closed"]
        )
        breached = all_tickets.filtered(lambda t: t.sla_status == "breached")

        sla_tickets = all_tickets.filtered(lambda t: t.sla_policy_id)
        sla_ok = len(sla_tickets.filtered(lambda t: t.sla_status != "breached"))
        sla_rate = round((sla_ok / len(sla_tickets)) * 100, 1) if sla_tickets else 100.0

        resolved_with_dates = resolved.filtered(
            lambda t: t.resolved_date and t.create_date
        )
        avg_resolution = 0
        if resolved_with_dates:
            avg_resolution = round(
                sum(
                    (t.resolved_date - t.create_date).total_seconds() / 3600
                    for t in resolved_with_dates
                )
                / len(resolved_with_dates),
                1,
            )

        priorities = ["urgent", "high", "medium", "low"]
        priority_breakdown = {
            p: len(all_tickets.filtered(lambda t: t.priority == p)) for p in priorities
        }

        project_map = {}
        for t in all_tickets:
            if t.project_id:
                pid = t.project_id.id
                if pid not in project_map:
                    project_map[pid] = {
                        "name": t.project_id.name,
                        "count": 0,
                        "resolved": 0,
                    }
                project_map[pid]["count"] += 1
                if t.state in ["resolved", "closed"]:
                    project_map[pid]["resolved"] += 1
        project_summary = sorted(
            project_map.values(), key=lambda x: x["count"], reverse=True
        )

        company = request.env["res.company"].sudo().search([], limit=1)

        return request.render(
            "customer_support.report_focal_performance",
            {
                "user": user,
                "focal": fp,
                "company": company,
                "days": days,
                "since": since,
                "all_tickets": all_tickets,
                "period_tickets": period_tickets,
                "resolved": resolved,
                "open_tickets": open_tickets,
                "breached": breached,
                "sla_rate": sla_rate,
                "avg_resolution": avg_resolution,
                "priority_breakdown": priority_breakdown,
                "project_summary": project_summary,
                "resolve_rate": (
                    round((len(resolved) / len(all_tickets)) * 100, 1)
                    if all_tickets
                    else 0
                ),
                "generated_at": fields.Datetime.now().strftime("%Y-%m-%d %H:%M"),
            },
        )

    @http.route(
        "/customer_support/admin/report/executive",
        type="http",
        auth="user",
        website=True,
    )
    def report_executive(self, **kw):
        """Printable Executive Summary Report — all projects + all focal persons."""
        user = request.env.user
        if not user.has_group("base.group_system"):
            return werkzeug.utils.redirect("/customer_support/dashboard")

        days = int(kw.get("days", 30))
        since = fields.Datetime.now() - timedelta(days=days)

        all_tickets = request.env["customer.support"].sudo().search([])
        period_tickets = all_tickets.filtered(
            lambda t: t.create_date and t.create_date >= since
        )

        total = len(all_tickets)
        resolved_count = len(
            all_tickets.filtered(lambda t: t.state in ["resolved", "closed"])
        )
        open_count = len(
            all_tickets.filtered(lambda t: t.state not in ["resolved", "closed"])
        )
        breached_count = len(all_tickets.filtered(lambda t: t.sla_status == "breached"))
        sla_all = all_tickets.filtered(lambda t: t.sla_policy_id)
        sla_ok = len(sla_all.filtered(lambda t: t.sla_status != "breached"))
        sla_compliance = round((sla_ok / len(sla_all)) * 100, 1) if sla_all else 100.0

        projects = (
            request.env["customer_support.project"]
            .sudo()
            .search([("active", "=", True)])
        )
        project_rows = []
        for proj in projects:
            pt = all_tickets.filtered(lambda t: t.project_id.id == proj.id)
            tot = len(pt)
            res = len(pt.filtered(lambda t: t.state in ["resolved", "closed"]))
            br = len(pt.filtered(lambda t: t.sla_status == "breached"))
            score = (
                round(max(0, (res / tot * 100) - min((br / tot) * 50, 50)), 1)
                if tot > 0
                else 100
            )
            health = "green" if score >= 80 else "amber" if score >= 50 else "red"
            project_rows.append(
                {
                    "name": proj.name,
                    "total": tot,
                    "resolved": res,
                    "open": tot - res,
                    "breached": br,
                    "health": health,
                    "health_score": score,
                }
            )
        project_rows.sort(key=lambda x: x["health_score"])

        focal_persons = (
            request.env["res.users"]
            .sudo()
            .search(
                [
                    ("id", "not in", [1, request.env.ref("base.public_user").id]),
                    ("active", "=", True),
                ]
            )
        )
        focal_persons = focal_persons.filtered(lambda u: u.has_group("base.group_user"))
        focal_rows = []
        for fp in focal_persons:
            ft = all_tickets.filtered(
                lambda t: t.assigned_to and t.assigned_to.id == fp.id
            )
            tot = len(ft)
            res = len(ft.filtered(lambda t: t.state in ["resolved", "closed"]))
            br = len(ft.filtered(lambda t: t.sla_status == "breached"))
            sla_t = ft.filtered(lambda t: t.sla_policy_id)
            sla_r = (
                round(
                    (
                        len(sla_t.filtered(lambda t: t.sla_status != "breached"))
                        / len(sla_t)
                    )
                    * 100,
                    1,
                )
                if sla_t
                else 100.0
            )
            rw = ft.filtered(
                lambda t: t.state in ["resolved", "closed"]
                and t.resolved_date
                and t.create_date
            )
            avg_r = (
                round(
                    sum(
                        (t.resolved_date - t.create_date).total_seconds() / 3600
                        for t in rw
                    )
                    / len(rw),
                    1,
                )
                if rw
                else 0
            )
            focal_rows.append(
                {
                    "name": fp.name,
                    "assigned": tot,
                    "resolved": res,
                    "open": tot - res,
                    "breached": br,
                    "resolve_rate": round((res / tot) * 100, 1) if tot > 0 else 0,
                    "sla_rate": sla_r,
                    "avg_resolution": avg_r,
                }
            )
        focal_rows.sort(key=lambda x: x["resolved"], reverse=True)

        company = request.env["res.company"].sudo().search([], limit=1)

        return request.render(
            "customer_support.report_executive_summary",
            {
                "user": user,
                "company": company,
                "days": days,
                "since": since,
                "total": total,
                "resolved_count": resolved_count,
                "open_count": open_count,
                "breached_count": breached_count,
                "sla_compliance": sla_compliance,
                "resolve_rate": (
                    round((resolved_count / total) * 100, 1) if total > 0 else 0
                ),
                "project_rows": project_rows,
                "focal_rows": focal_rows,
                "period_total": len(period_tickets),
                "generated_at": fields.Datetime.now().strftime("%Y-%m-%d %H:%M"),
            },
        )

    # =========================================================================
    # ADMIN NOTIFICATIONS  — polled every 30s by the bell dropdown
    # =========================================================================

    @http.route(
        "/customer_support/admin/notifications",
        type="http",
        auth="user",
        website=True,
        csrf=False,
    )
    def admin_notifications(self, **kw):
        """
        Returns 3 notification categories for the admin bell:
          1. sla_breaches   — tickets with breached SLA across ALL agents
          2. unassigned     — tickets with no assigned_to and state = 'new'
          3. status_changes — tickets whose write_date is within last 30 min
        """
        try:
            now = fields.Datetime.now()
            payload = self._build_admin_notifications(now)

            # Keep only keys that still exist in current payload.
            current_keys = {
                item.get("_key")
                for section in payload.values()
                for item in section
                if item.get("_key")
            }
            read_keys = self._load_admin_read_keys()
            pruned_read_keys = read_keys.intersection(current_keys)
            if pruned_read_keys != read_keys:
                self._save_admin_read_keys(pruned_read_keys)

            for section_name in ("sla_breaches", "unassigned", "status_changes"):
                filtered = []
                for item in payload[section_name]:
                    if item.get("_key") in pruned_read_keys:
                        continue
                    clean_item = dict(item)
                    clean_item.pop("_key", None)
                    filtered.append(clean_item)
                payload[section_name] = filtered

            return request.make_response(
                json.dumps(payload),
                headers=[("Content-Type", "application/json")],
            )

        except Exception as e:
            _logger.error(f"Admin notifications error: {str(e)}")
            return request.make_response(
                json.dumps(
                    {
                        "sla_breaches": [],
                        "unassigned": [],
                        "status_changes": [],
                    }
                ),
                headers=[("Content-Type", "application/json")],
            )

    @http.route(
        "/customer_support/admin/notifications/mark_read",
        type="http",
        auth="user",
        methods=["POST"],
        website=True,
        csrf=False,
    )
    def admin_notifications_mark_read(self, **kw):
        """Persist 'mark all read' for current admin user across sessions."""
        try:
            if not request.env.user.has_group("base.group_system"):
                return request.make_response(
                    json.dumps({"success": False, "error": "Access denied"}),
                    headers=[("Content-Type", "application/json")],
                    status=403,
                )

            now = fields.Datetime.now()
            payload = self._build_admin_notifications(now)
            current_keys = {
                item.get("_key")
                for section in payload.values()
                for item in section
                if item.get("_key")
            }

            existing = self._load_admin_read_keys()
            self._save_admin_read_keys(existing.union(current_keys))

            return request.make_response(
                json.dumps({"success": True}),
                headers=[("Content-Type", "application/json")],
            )
        except Exception as e:
            _logger.error(f"Admin notifications mark_read error: {str(e)}")
            return request.make_response(
                json.dumps({"success": False}),
                headers=[("Content-Type", "application/json")],
                status=500,
            )

    # =========================================================================
    # AGENT WORKLOAD OVERVIEW  — polled every 60s by the workload panel
    # =========================================================================

    @http.route(
        "/customer_support/admin/workload",
        type="http",
        auth="user",
        website=True,
        csrf=False,
    )
    def admin_workload(self, **kw):
        """
        Returns workload stats per active internal user (focal person).
        For each agent:
          - assigned    : tickets in state 'assigned' or 'new'
          - in_progress : tickets in state 'in_progress'
          - resolved    : tickets in state 'resolved' or 'closed'
          - total_open  : assigned + in_progress
          - breached    : open tickets with sla_deadline < now
          - resolve_rate: resolved / total * 100  (rounded)
        """
        try:
            now = fields.Datetime.now()
            Ticket = request.env["customer.support"].sudo()

            # Active internal users only (exclude admin id=1 and portal users)
            users = (
                request.env["res.users"]
                .sudo()
                .search(
                    [
                        ("active", "=", True),
                        ("id", "!=", 1),
                        ("share", "=", False),
                    ]
                )
            )

            agents = []
            total_open_system = 0
            total_breached_system = 0
            overloaded_count = 0

            for user in users:
                user_tickets = Ticket.search([("assigned_to", "=", user.id)])

                assigned = len(
                    user_tickets.filtered(lambda t: t.state in ["new", "assigned"])
                )
                in_progress = len(
                    user_tickets.filtered(lambda t: t.state == "in_progress")
                )
                resolved = len(
                    user_tickets.filtered(lambda t: t.state in ["resolved", "closed"])
                )
                total_open = assigned + in_progress
                total_all = len(user_tickets)

                breached = len(
                    user_tickets.filtered(
                        lambda t: t.sla_deadline
                        and t.sla_deadline < now
                        and t.state not in ["resolved", "closed"]
                    )
                )

                resolve_rate = (
                    round((resolved / total_all) * 100) if total_all > 0 else 0
                )

                total_open_system += total_open
                total_breached_system += breached
                if total_open > 8:
                    overloaded_count += 1

                agents.append(
                    {
                        "user_id": user.id,
                        "name": user.name,
                        "email": user.email or "",
                        "assigned": assigned,
                        "in_progress": in_progress,
                        "resolved": resolved,
                        "total_open": total_open,
                        "breached": breached,
                        "resolve_rate": resolve_rate,
                    }
                )

            # Sort: most loaded first
            agents.sort(key=lambda a: a["total_open"], reverse=True)

            summary = {
                "total_agents": len(agents),
                "total_open": total_open_system,
                "overloaded": overloaded_count,
                "total_breached": total_breached_system,
            }

            return request.make_response(
                json.dumps({"agents": agents, "summary": summary}),
                headers=[("Content-Type", "application/json")],
            )

        except Exception as e:
            _logger.error(f"Admin workload error: {str(e)}")
            return request.make_response(
                json.dumps({"agents": [], "summary": {}}),
                headers=[("Content-Type", "application/json")],
            )

    # =========================================================================
    # USER MANAGEMENT LIST
    # =========================================================================

    @http.route(
        "/customer_support/admin_dashboard/users",
        type="http",
        auth="user",
        website=True,
    )
    def admin_users_list(self, **kw):
        user = request.env.user
        if not user.has_group("base.group_system"):
            return werkzeug.utils.redirect("/customer_support/dashboard")
        # Legacy route kept for backward compatibility; user management now lives
        # directly in the Admin Dashboard tab.
        return self._redirect_user_management_tab(
            success=kw.get("success"), error=kw.get("error")
        )

    # =========================================================================
    # CREATE USER
    # =========================================================================

    @http.route(
        "/customer_support/admin_dashboard/create_user",
        type="http",
        auth="user",
        website=True,
    )
    def admin_create_user_form(self, **kw):
        user = request.env.user
        if not user.has_group("base.group_system"):
            return werkzeug.utils.redirect("/customer_support/dashboard")

        return request.render(
            "customer_support.admin_create_user_form",
            {
                "user": user,
                "page_name": "create_user",
                "error": kw.get("error", ""),
            },
        )

    @http.route(
        "/customer_support/admin_dashboard/submit_user",
        type="http",
        auth="user",
        methods=["POST"],
        website=True,
        csrf=True,
    )
    def admin_submit_user(self, **post):
        try:
            user = request.env.user
            if not user.has_group("base.group_system"):
                return werkzeug.utils.redirect("/customer_support/dashboard")

            post_dict = dict(post) if not isinstance(post, dict) else post

            name = post_dict.get("name", "").strip()
            email = post_dict.get("email", "").strip()
            password = post_dict.get("password", "").strip()
            user_type = post_dict.get("user_type", "customer")
            phone = post_dict.get("phone", "").strip()

            if not name:
                return werkzeug.utils.redirect(
                    "/customer_support/admin_dashboard/create_user?error=Name is required"
                )
            if not email:
                return werkzeug.utils.redirect(
                    "/customer_support/admin_dashboard/create_user?error=Email is required"
                )
            if not password:
                return werkzeug.utils.redirect(
                    "/customer_support/admin_dashboard/create_user?error=Password is required"
                )

            existing_user = (
                request.env["res.users"]
                .sudo()
                .with_context(active_test=False)
                .search(["|", ("login", "=", email), ("email", "=", email)], limit=1)
            )
            if existing_user:
                return werkzeug.utils.redirect(
                    "/customer_support/admin_dashboard/create_user?error=A user with this email already exists"
                )

            partner = (
                request.env["res.partner"]
                .sudo()
                .create(
                    {
                        "name": name,
                        "email": email,
                        "phone": phone,
                        "is_company": False,
                    }
                )
            )

            if user_type == "focal_person":
                groups_to_add = [request.env.ref("base.group_user").id]
            else:
                groups_to_add = [request.env.ref("base.group_portal").id]

            new_user = (
                request.env["res.users"]
                .sudo()
                .with_context(no_reset_password=True)
                .create(
                    {
                        "name": name,
                        "login": email,
                        "email": email,
                        "partner_id": partner.id,
                        "password": password,
                        "active": True,
                    }
                )
            )

            if groups_to_add:
                new_user.sudo().write({"group_ids": [(6, 0, groups_to_add)]})

            _logger.info(f"User created: {new_user.name} ({user_type}) by {user.name}")

            try:
                if user_type == "customer":
                    EmailService.send_welcome_email(email, name, password)
                elif user_type == "focal_person":
                    EmailService.send_welcome_email_focal_person(email, name, password)
            except Exception as email_error:
                _logger.error(f"Welcome email failed for {email}: {str(email_error)}")

            user_type_label = (
                "Focal Person" if user_type == "focal_person" else "Customer"
            )
            return self._redirect_user_management_tab(
                success=f"{user_type_label} created successfully. Welcome email queued."
            )

        except Exception as e:
            _logger.exception(f"Create user error: {str(e)}")
            return werkzeug.utils.redirect(
                "/customer_support/admin_dashboard/create_user?error=Error creating user. Please try again."
            )

    # =========================================================================
    # EDIT USER
    # =========================================================================

    @http.route(
        "/customer_support/admin_dashboard/user/<int:user_id>/edit",
        type="http",
        auth="user",
        website=True,
    )
    def admin_edit_user_form(self, user_id, **kw):
        current_user = request.env.user
        if not current_user.has_group("base.group_system"):
            return werkzeug.utils.redirect("/customer_support/dashboard")

        edit_user = request.env["res.users"].sudo().browse(user_id)
        if not edit_user.exists():
            return self._redirect_user_management_tab(error="User not found")

        user_type = (
            "focal_person" if edit_user.has_group("base.group_user") else "customer"
        )

        return request.render(
            "customer_support.admin_edit_user_form",
            {
                "user": current_user,
                "edit_user": edit_user,
                "user_type": user_type,
                "page_name": "edit_user",
                "error": kw.get("error", ""),
            },
        )

    @http.route(
        "/customer_support/admin_dashboard/user/<int:user_id>/update",
        type="http",
        auth="user",
        methods=["POST"],
        website=True,
        csrf=True,
    )
    def admin_update_user(self, user_id, **post):
        try:
            current_user = request.env.user
            if not current_user.has_group("base.group_system"):
                return werkzeug.utils.redirect("/customer_support/dashboard")

            edit_user = request.env["res.users"].sudo().browse(user_id)
            if not edit_user.exists():
                return self._redirect_user_management_tab(error="User not found")

            post_dict = dict(post) if not isinstance(post, dict) else post

            name = post_dict.get("name", "").strip()
            email = post_dict.get("email", "").strip()
            phone = post_dict.get("phone", "").strip()
            user_type = post_dict.get("user_type", "customer")
            password = post_dict.get("password", "").strip()

            if not name:
                return werkzeug.utils.redirect(
                    f"/customer_support/admin_dashboard/user/{user_id}/edit?error=Name is required"
                )
            if not email:
                return werkzeug.utils.redirect(
                    f"/customer_support/admin_dashboard/user/{user_id}/edit?error=Email is required"
                )

            existing_user = (
                request.env["res.users"]
                .sudo()
                .search(
                    [
                        "|",
                        ("login", "=", email),
                        ("email", "=", email),
                        ("id", "!=", user_id),
                    ],
                    limit=1,
                )
            )
            if existing_user:
                return werkzeug.utils.redirect(
                    f"/customer_support/admin_dashboard/user/{user_id}/edit?error=Email already exists"
                )

            edit_user.partner_id.sudo().write(
                {"name": name, "email": email, "phone": phone}
            )

            update_vals = {"name": name, "login": email, "email": email}
            if password:
                update_vals["password"] = password

            if user_type == "focal_person":
                groups_to_add = [request.env.ref("base.group_user").id]
                groups_to_remove = [request.env.ref("base.group_portal").id]
            else:
                groups_to_add = [request.env.ref("base.group_portal").id]
                groups_to_remove = [request.env.ref("base.group_user").id]

            update_vals["group_ids"] = [
                (4, groups_to_add[0]),
                (3, groups_to_remove[0]),
            ]

            edit_user.sudo().write(update_vals)
            _logger.info(f"User updated: {edit_user.name} by {current_user.name}")

            return self._redirect_user_management_tab(
                success="User updated successfully"
            )

        except Exception as e:
            _logger.exception(f"Update user error: {str(e)}")
            return werkzeug.utils.redirect(
                f"/customer_support/admin_dashboard/user/{user_id}/edit?error=Error updating user"
            )

    # =========================================================================
    # TOGGLE USER ACTIVE / INACTIVE
    # =========================================================================

    @http.route(
        "/customer_support/admin_dashboard/user/<int:user_id>/toggle_active",
        type="http",
        auth="user",
        methods=["POST"],
        website=True,
        csrf=True,
    )
    def admin_toggle_user_active(self, user_id, **post):
        try:
            current_user = request.env.user
            if not current_user.has_group("base.group_system"):
                return werkzeug.utils.redirect("/customer_support/dashboard")

            edit_user = request.env["res.users"].sudo().browse(user_id)
            if not edit_user.exists():
                return self._redirect_user_management_tab(error="User not found")

            if edit_user.id == current_user.id:
                return self._redirect_user_management_tab(
                    error="Cannot deactivate yourself"
                )

            new_status = not edit_user.active
            edit_user.sudo().write({"active": new_status})
            status_text = "activated" if new_status else "deactivated"
            _logger.info(f"User {status_text}: {edit_user.name} by {current_user.name}")

            return self._redirect_user_management_tab(
                success=f"User {status_text} successfully"
            )

        except Exception as e:
            _logger.exception(f"Toggle user active error: {str(e)}")
            return self._redirect_user_management_tab(
                error="Error updating user status"
            )

    # =========================================================================
    # DELETE (ARCHIVE) USER
    # =========================================================================

    @http.route(
        "/customer_support/admin_dashboard/user/<int:user_id>/delete",
        type="http",
        auth="user",
        methods=["POST"],
        website=True,
        csrf=True,
    )
    def admin_delete_user(self, user_id, **post):
        try:
            current_user = request.env.user
            if not current_user.has_group("base.group_system"):
                return werkzeug.utils.redirect("/customer_support/dashboard")

            edit_user = request.env["res.users"].sudo().browse(user_id)
            if not edit_user.exists():
                return self._redirect_user_management_tab(error="User not found")

            if edit_user.id == current_user.id:
                return self._redirect_user_management_tab(
                    error="Cannot delete yourself"
                )

            user_name = edit_user.name
            edit_user.sudo().write({"active": False})
            _logger.info(f"User archived: {user_name} by {current_user.name}")

            return self._redirect_user_management_tab(
                success="User deleted successfully"
            )

        except Exception as e:
            _logger.exception(f"Delete user error: {str(e)}")
            return self._redirect_user_management_tab(error="Error deleting user")

    @http.route(
        "/customer_support/admin_dashboard/user/<int:user_id>/detail",
        type="jsonrpc",
        auth="user",
        csrf=False,
    )
    def user_detail(self, user_id, **kw):
        if not request.env.user.has_group("base.group_system"):
            return {"error": "Access denied"}
        try:
            user = (
                request.env["res.users"]
                .with_context(active_test=False)
                .sudo()
                .browse(user_id)
            )
            if not user.exists():
                return {"error": "User not found"}

            if user.has_group("base.group_system"):
                role = "Admin"
            elif user.has_group("base.group_user"):
                role = "Focal Person"
            elif user.has_group("base.group_portal"):
                role = "Customer"
            else:
                role = "User"

            projects = []

            if role == "Customer":
                partner = user.partner_id.sudo()
                if partner.project_id:
                    proj = partner.project_id
                    projects.append({
                        "name": proj.name,
                        "key": proj.code or "",
                        "association": "Assigned Project",
                    })
                ticket_projects = (
                    request.env["customer.support"]
                    .sudo()
                    .search([("customer_id", "=", partner.id)])
                    .mapped("project_id")
                )
                seen = {partner.project_id.id} if partner.project_id else set()
                for proj in ticket_projects:
                    if proj.id not in seen:
                        seen.add(proj.id)
                        projects.append({
                            "name": proj.name,
                            "key": proj.code or "",
                            "association": "Has Tickets",
                        })

            elif role == "Focal Person":
                members = (
                    request.env["customer_support.project.member"]
                    .sudo()
                    .search([("user_id", "=", user_id)])
                )
                for m in members:
                    projects.append({
                        "name": m.project_id.name,
                        "key": m.project_id.code or "",
                        "association": m.role_label or m.role.replace("_", " ").title(),
                    })

            return {
                "success": True,
                "user": {
                    "id": user.id,
                    "name": user.name,
                    "email": user.email or user.login,
                    "role": role,
                    "active": user.active,
                    "projects": projects,
                },
            }
        except Exception as e:
            _logger.exception("user_detail error: %s", e)
            return {"error": str(e)}
