# -*- coding: utf-8 -*-
import json
from datetime import timedelta

from odoo import http, fields
from odoo.http import request


class AutoAssignmentController(http.Controller):

    _ALLOWED_DURATIONS = [30, 60, 120, 240, 480, 1440]
    _ALLOWED_STRATEGIES = ["round_robin", "least_load"]

    def _json_resp(self, data, status=200):
        return request.make_response(
            json.dumps(data),
            headers=[("Content-Type", "application/json")],
            status=status,
        )

    def _ensure_admin_json(self):
        if not request.session.uid:
            return self._json_resp(
                {
                    "success": False,
                    "error": "Session expired. Please log in again.",
                    "redirect_url": "/customer_support/login?next=%2Fcustomer_support%2Fadmin_dashboard",
                },
                status=401,
            )
        if not request.env.user.has_group("base.group_system"):
            return self._json_resp(
                {"success": False, "error": "Access denied."}, status=403
            )
        return None

    def _read_state(self):
        params = request.env["ir.config_parameter"].sudo()
        until_raw = params.get_param("customer_support.auto_assign_enabled_until") or ""
        strategy = (
            params.get_param("customer_support.auto_assign_strategy") or "round_robin"
        )

        enabled_until = False
        if until_raw:
            try:
                enabled_until = fields.Datetime.to_datetime(until_raw)
            except Exception:
                enabled_until = False

        if strategy not in self._ALLOWED_STRATEGIES:
            strategy = "round_robin"

        now = fields.Datetime.now()
        enabled = bool(enabled_until and enabled_until > now)
        remaining_minutes = 0
        if enabled:
            remaining_minutes = max(
                0,
                int((enabled_until - now).total_seconds() // 60),
            )

        return {
            "enabled": enabled,
            "enabled_until": (
                fields.Datetime.to_string(enabled_until) if enabled_until else None
            ),
            "remaining_minutes": remaining_minutes,
            "strategy": strategy,
            "duration_options": self._ALLOWED_DURATIONS,
        }

    @http.route(
        "/customer_support/admin/auto_assignment/status",
        type="http",
        auth="public",
        methods=["GET"],
        website=True,
        csrf=False,
    )
    def auto_assignment_status(self, **kwargs):
        auth_err = self._ensure_admin_json()
        if auth_err:
            return auth_err
        return self._json_resp({"success": True, **self._read_state()})

    @http.route(
        "/customer_support/admin/auto_assignment/update",
        type="http",
        auth="public",
        methods=["POST"],
        website=True,
        csrf=False,
    )
    def auto_assignment_update(self, **post):
        auth_err = self._ensure_admin_json()
        if auth_err:
            return auth_err

        enabled_raw = (post.get("enabled") or "").strip().lower()
        strategy = (post.get("strategy") or "round_robin").strip()
        duration_raw = (post.get("duration_minutes") or "").strip()

        enabled = enabled_raw in ("1", "true", "yes", "on")

        if strategy not in self._ALLOWED_STRATEGIES:
            strategy = "round_robin"

        params = request.env["ir.config_parameter"].sudo()
        params.set_param("customer_support.auto_assign_strategy", strategy)

        if enabled:
            try:
                duration_minutes = int(duration_raw)
            except Exception:
                return self._json_resp(
                    {"success": False, "error": "Invalid duration."},
                    status=400,
                )

            if duration_minutes not in self._ALLOWED_DURATIONS:
                return self._json_resp(
                    {"success": False, "error": "Duration not allowed."},
                    status=400,
                )

            enabled_until = fields.Datetime.now() + timedelta(minutes=duration_minutes)
            params.set_param(
                "customer_support.auto_assign_enabled_until",
                fields.Datetime.to_string(enabled_until),
            )
        else:
            params.set_param("customer_support.auto_assign_enabled_until", "")

        return self._json_resp({"success": True, **self._read_state()})
