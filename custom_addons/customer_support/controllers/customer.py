# -*- coding: utf-8 -*-
import base64
import json
import logging
from odoo import http, fields
from odoo.http import request
from datetime import datetime, timedelta
import werkzeug

_logger = logging.getLogger(__name__)


class CustomerSupportCustomer(http.Controller):

    @http.route("/customer_support/dashboard", type="http", auth="user", website=True)
    def support_dashboard(self, **kw):
        try:
            user = request.env.user
            if user.id == request.env.ref("base.public_user").id:
                return werkzeug.utils.redirect(
                    "/customer_support/login?error=Please login to access dashboard"
                )
            if user.has_group("base.group_system"):
                return werkzeug.utils.redirect("/customer_support/admin_dashboard")
            tickets = (
                request.env["customer.support"]
                .search([("customer_id", "=", user.partner_id.id)])
                .sorted(key=lambda r: r.create_date, reverse=True)
            )
            ticket_counts = {
                "new": len(tickets.filtered(lambda t: t.state == "new")),
                "in_progress": len(
                    tickets.filtered(lambda t: t.state == "in_progress")
                ),
                "resolved": len(tickets.filtered(lambda t: t.state == "resolved")),
                "closed": len(tickets.filtered(lambda t: t.state == "closed")),
                "total": len(tickets),
            }
            response = request.render(
                "customer_support.portal_dashboard",
                {
                    "user": user,
                    "tickets": tickets,
                    "ticket_counts": ticket_counts,
                    "analytics": {},
                    "performance": {},
                    "page_name": "dashboard",
                },
            )
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            return response
        except Exception as e:
            _logger.error(f"Dashboard error: {str(e)}")
            return werkzeug.utils.redirect(
                "/customer_support/login?error=Error loading dashboard"
            )

    @http.route(
        "/customer_support/create_ticket", type="http", auth="user", website=True
    )
    def create_ticket_form(self, **kw):
        try:
            user = request.env.user
            if user.id == request.env.ref("base.public_user").id:
                return werkzeug.utils.redirect(
                    "/customer_support/login?error=Please login"
                )
            projects = (
                request.env["customer_support.project"]
                .sudo()
                .search([("active", "=", True)])
            )
            response = request.render(
                "customer_support.create_ticket_form",
                {
                    "user": user,
                    "projects": projects,
                    "error": kw.get("error", ""),
                    "page_name": "create_ticket",
                },
            )
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            return response
        except Exception as e:
            _logger.error(f"Create ticket form error: {str(e)}")
            return werkzeug.utils.redirect("/customer_support/dashboard")

    @http.route(
        "/customer_support/submit_ticket",
        type="http",
        auth="user",
        methods=["POST"],
        website=True,
        csrf=True,
    )
    def submit_ticket(self, **post):
        try:
            user = request.env.user

            _logger.info(f"POST data type: {type(post)}")

            # Robust post data normalization
            post_dict = {}
            if hasattr(post, "items"):
                post_dict = dict(post)
            elif isinstance(post, (list, tuple)):
                post_dict = dict(post)
            else:
                try:
                    post_dict = dict(post)
                except Exception as conv_err:
                    _logger.error(
                        f"Cannot convert post to dict: {type(post)}, {conv_err}"
                    )
                    return werkzeug.utils.redirect(
                        "/customer_support/create_ticket?error=Invalid form data"
                    )

            subject = post_dict.get("subject", "").strip()
            description = post_dict.get("description", "").strip()
            project_id = post_dict.get("project_id")

            if not subject:
                return werkzeug.utils.redirect(
                    "/customer_support/create_ticket?error=Subject is required"
                )
            if not description:
                return werkzeug.utils.redirect(
                    "/customer_support/create_ticket?error=Description is required"
                )
            if not project_id:
                return werkzeug.utils.redirect(
                    "/customer_support/create_ticket?error=Project is required"
                )

            ticket = (
                request.env["customer.support"]
                .sudo()
                .create(
                    {
                        "subject": subject,
                        "description": description,
                        "priority": post_dict.get("priority", "medium"),
                        "customer_id": user.partner_id.id,
                        "project_id": int(project_id),
                        "state": "new",
                    }
                )
            )

            # Handle attachments
            try:
                if hasattr(request, "httprequest") and hasattr(
                    request.httprequest, "files"
                ):
                    for file_key in request.httprequest.files:
                        uploaded_file = request.httprequest.files[file_key]
                        if uploaded_file and uploaded_file.filename:
                            file_data = uploaded_file.read()
                            if file_data:
                                request.env["ir.attachment"].sudo().create(
                                    {
                                        "name": uploaded_file.filename,
                                        "type": "binary",
                                        "datas": base64.b64encode(file_data).decode(
                                            "utf-8"
                                        ),
                                        "res_model": "customer.support",
                                        "res_id": ticket.id,
                                        "mimetype": uploaded_file.content_type
                                        or "application/octet-stream",
                                    }
                                )
                                _logger.info(
                                    f"Attachment added: {uploaded_file.filename}"
                                )
            except Exception as attach_err:
                _logger.warning(
                    f"Attachment processing error (ticket still created): {attach_err}"
                )

            _logger.info(
                f"Ticket created: {ticket.name} by {user.name} for project {project_id}"
            )

            return werkzeug.utils.redirect(
                "/customer_support/dashboard?success=Ticket submitted successfully"
            )

        except Exception as e:
            _logger.exception(f"Submit ticket error: {str(e)}")
            return werkzeug.utils.redirect(
                "/customer_support/create_ticket?error=Error creating ticket. Please try again."
            )

    # =========================================================================
    # CUSTOMER NOTIFICATIONS — fetch unread
    # =========================================================================

    @http.route(
        "/customer_support/customer/notifications",
        type="http",
        auth="user",
        methods=["GET"],
        website=True,
        csrf=False,
    )
    def get_customer_notifications(self, **kw):
        """
        Returns unread notifications for the logged-in customer as JSON.
        Polled every 30 seconds by the portal dashboard bell.
        """
        try:
            user = request.env.user
            partner = user.partner_id

            notifications = (
                request.env["customer.support.notification"]
                .sudo()
                .search(
                    [("customer_id", "=", partner.id), ("is_read", "=", False)],
                    order="create_date desc",
                    limit=30,
                )
            )

            items = []
            for n in notifications:
                type_meta = {
                    "status_change": {"icon": "bi-arrow-left-right", "cls": "status"},
                    "assigned": {"icon": "bi-person-check-fill", "cls": "assigned"},
                    "sla_breach": {
                        "icon": "bi-exclamation-octagon-fill",
                        "cls": "breach",
                    },
                }.get(n.notification_type, {"icon": "bi-bell-fill", "cls": "status"})

                # Human-readable time
                time_str = ""
                if n.create_date:
                    now = fields.Datetime.now()
                    secs = int((now - n.create_date).total_seconds())
                    if secs < 60:
                        time_str = "just now"
                    elif secs < 3600:
                        time_str = f"{secs // 60}m ago"
                    elif secs < 86400:
                        time_str = f"{secs // 3600}h ago"
                    else:
                        time_str = f"{secs // 86400}d ago"

                items.append(
                    {
                        "id":          n.id,
                        "ticket_id":   n.ticket_id.id if n.ticket_id else None,
                        "ticket_name": n.ticket_name or "",
                        "message":     n.message or "",
                        "type":        n.notification_type,
                        "icon":        type_meta["icon"],
                        "cls":         type_meta["cls"],
                        "time":        time_str,
                    }
                )

            return request.make_response(
                json.dumps(
                    {"success": True, "notifications": items, "count": len(items)}
                ),
                headers=[("Content-Type", "application/json")],
            )

        except Exception as e:
            _logger.error(f"Customer notifications error: {e}")
            return request.make_response(
                json.dumps({"success": False, "notifications": [], "count": 0}),
                headers=[("Content-Type", "application/json")],
            )

    # =========================================================================
    # CUSTOMER NOTIFICATIONS — mark all read
    # =========================================================================

    @http.route(
        "/customer_support/customer/notifications/mark_read",
        type="http",
        auth="user",
        methods=["POST"],
        website=True,
        csrf=False,
    )
    def mark_notifications_read(self, **kw):
        """Marks all unread notifications for the current customer as read."""
        try:
            user = request.env.user
            partner = user.partner_id

            unread = (
                request.env["customer.support.notification"]
                .sudo()
                .search([("customer_id", "=", partner.id), ("is_read", "=", False)])
            )
            unread.write({"is_read": True})

            return request.make_response(
                json.dumps({"success": True, "marked": len(unread)}),
                headers=[("Content-Type", "application/json")],
            )

        except Exception as e:
            _logger.error(f"Mark notifications read error: {e}")
            return request.make_response(
                json.dumps({"success": False}),
                headers=[("Content-Type", "application/json")],
            )

    # =========================================================================
    # CUSTOMER REPORTING — data API
    # =========================================================================

    @http.route(
        "/customer_support/customer/reporting",
        type="http",
        auth="user",
        methods=["GET"],
        website=True,
        csrf=False,
    )
    def get_customer_reporting(self, days="30", **kw):
        """
        Returns reporting data for the logged-in customer as JSON.
        Used by the Reporting tab charts on the portal dashboard.
        Query param: ?days=7|30|90
        """
        try:
            user = request.env.user
            partner = user.partner_id
            days_int = int(days) if str(days).isdigit() else 30
            since = datetime.now() - timedelta(days=days_int)

            # All tickets for this customer
            all_tickets = (
                request.env["customer.support"]
                .sudo()
                .search([("customer_id", "=", partner.id)])
            )

            # Tickets within the selected period
            period_tickets = all_tickets.filtered(
                lambda t: t.create_date
                and t.create_date >= fields.Datetime.to_datetime(since)
            )

            # ── KPI cards ────────────────────────────────────────────────
            total = len(period_tickets)
            resolved = len(
                period_tickets.filtered(lambda t: t.state in ("resolved", "closed"))
            )
            open_count = len(
                period_tickets.filtered(lambda t: t.state in ("new", "in_progress"))
            )

            # Avg resolution time (hours) for resolved tickets in period
            res_times = []
            for t in period_tickets.filtered(
                lambda t: t.state in ("resolved", "closed")
            ):
                if t.create_date and t.write_date:
                    diff = (t.write_date - t.create_date).total_seconds() / 3600
                    res_times.append(diff)
            avg_resolution = (
                round(sum(res_times) / len(res_times), 1) if res_times else 0
            )

            # ── Status breakdown ─────────────────────────────────────────
            status_data = {
                "New": len(period_tickets.filtered(lambda t: t.state == "new")),
                "In Progress": len(
                    period_tickets.filtered(lambda t: t.state == "in_progress")
                ),
                "Resolved": len(
                    period_tickets.filtered(lambda t: t.state == "resolved")
                ),
                "Closed": len(period_tickets.filtered(lambda t: t.state == "closed")),
            }

            # ── Priority breakdown ────────────────────────────────────────
            priority_data = {
                "Low": len(
                    period_tickets.filtered(lambda t: (t.priority or "low") == "low")
                ),
                "Medium": len(
                    period_tickets.filtered(lambda t: (t.priority or "low") == "medium")
                ),
                "High": len(
                    period_tickets.filtered(lambda t: (t.priority or "low") == "high")
                ),
                "Urgent": len(
                    period_tickets.filtered(lambda t: (t.priority or "low") == "urgent")
                ),
            }

            # ── Ticket timeline (daily counts for selected period) ────────
            timeline = []
            for i in range(days_int):
                day = since + timedelta(days=i)
                day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
                day_end = day_start + timedelta(days=1)
                count = len(
                    period_tickets.filtered(
                        lambda t, ds=day_start, de=day_end: t.create_date
                        and ds <= t.create_date < de
                    )
                )
                timeline.append(
                    {
                        "date": day_start.strftime("%b %d"),
                        "count": count,
                    }
                )

            # ── Resolve rate trend (weekly buckets) ──────────────────────
            resolve_trend = []
            weeks = max(1, days_int // 7)
            for w in range(weeks):
                wk_start = since + timedelta(weeks=w)
                wk_end = wk_start + timedelta(weeks=1)
                wk_tickets = period_tickets.filtered(
                    lambda t, ws=wk_start, we=wk_end: t.create_date
                    and ws <= t.create_date < we
                )
                wk_total = len(wk_tickets)
                wk_resolved = len(
                    wk_tickets.filtered(lambda t: t.state in ("resolved", "closed"))
                )
                rate = round((wk_resolved / wk_total * 100), 1) if wk_total else 0
                resolve_trend.append(
                    {
                        "week": f"Wk {w + 1}",
                        "rate": rate,
                    }
                )

            data = {
                "success": True,
                "days": days_int,
                "kpis": {
                    "total": total,
                    "resolved": resolved,
                    "open": open_count,
                    "avg_resolution_hours": avg_resolution,
                    "resolve_rate": round((resolved / total * 100), 1) if total else 0,
                },
                "status_breakdown": status_data,
                "priority_breakdown": priority_data,
                "timeline": timeline,
                "resolve_trend": resolve_trend,
            }

            return request.make_response(
                json.dumps(data),
                headers=[("Content-Type", "application/json")],
            )

        except Exception as e:
            _logger.error(f"Customer reporting error: {e}")
            return request.make_response(
                json.dumps({"success": False, "error": str(e)}),
                headers=[("Content-Type", "application/json")],
            )
