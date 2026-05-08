# -*- coding: utf-8 -*-
"""
SLA Policy Controller
=====================
Handles all SLA policy management routes:
  - List all policies (JSON, used to populate Ticket Settings modal)
  - Create a new policy
  - Edit an existing policy
  - Delete a policy
  - Attach a policy to a ticket during assignment

All routes are admin-only except get_policies which is used
by the assignment form dropdown.
"""

import json
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class SLAPolicyController(http.Controller):

    # ── GET: list all active SLA policies ─────────────────────────────────────

    @http.route(
        "/customer_support/sla/policies",
        type="http",
        auth="user",
        methods=["GET"],
        csrf=False,
    )
    def get_policies(self, **kwargs):
        """
        Returns all active SLA policies as JSON.
        Used to populate the Ticket Settings modal table
        and the assignment form SLA dropdown.
        """
        try:
            policies = (
                request.env["customer.support.sla.policy"]
                .sudo()
                .search([("active", "=", True)])
            )
            data = [
                {
                    "id": p.id,
                    "name": p.name,
                    "description": p.description or "",
                    "response_time": p.response_time,
                    "time_unit": p.time_unit,
                    "priority_level": p.priority_level,
                    "display": f"{p.name} ({p.response_time} {p.time_unit})",
                }
                for p in policies
            ]
            return request.make_response(
                json.dumps({"success": True, "policies": data}),
                headers=[("Content-Type", "application/json")],
            )
        except Exception as e:
            _logger.error(f"get_policies error: {e}")
            return request.make_response(
                json.dumps({"success": False, "error": str(e)}),
                headers=[("Content-Type", "application/json")],
            )

    # ── POST: create a new SLA policy ─────────────────────────────────────────

    @http.route(
        "/customer_support/sla/create",
        type="http",
        auth="user",
        methods=["POST"],
        csrf=True,
        website=True,
    )
    def create_policy(self, **post):
        """
        Creates a new SLA policy from the Ticket Settings modal form.
        Redirects back to admin dashboard with success/error message.
        """
        try:
            user = request.env.user
            if not user.has_group("base.group_system"):
                return request.make_response(
                    json.dumps({"success": False, "error": "Admin access required"}),
                    headers=[("Content-Type", "application/json")],
                )

            name = post.get("sla_name", "").strip()
            response_time = int(post.get("sla_response_time", 24))
            time_unit = post.get("sla_time_unit", "hours")
            priority_level = post.get("sla_priority_level", "any")
            description = post.get("sla_description", "").strip()

            if not name:
                return request.redirect(
                    "/customer_support/admin_dashboard?tab=system-configuration&error=Policy name is required"
                )

            request.env["customer.support.sla.policy"].sudo().create(
                {
                    "name": name,
                    "response_time": response_time,
                    "time_unit": time_unit,
                    "priority_level": priority_level,
                    "description": description,
                    "active": True,
                }
            )

            _logger.info(f"SLA policy '{name}' created by {user.name}")
            return request.redirect(
                "/customer_support/admin_dashboard?tab=system-configuration&success=SLA policy created successfully"
            )

        except Exception as e:
            _logger.error(f"create_policy error: {e}")
            return request.redirect(
                f"/customer_support/admin_dashboard?tab=system-configuration&error={str(e)}"
            )

    # ── POST: update an existing SLA policy ───────────────────────────────────

    @http.route(
        "/customer_support/sla/<int:policy_id>/update",
        type="http",
        auth="user",
        methods=["POST"],
        csrf=True,
        website=True,
    )
    def update_policy(self, policy_id, **post):
        """
        Updates an existing SLA policy.
        Returns JSON so the modal can update without a page reload.
        """
        try:
            user = request.env.user
            if not user.has_group("base.group_system"):
                return request.make_response(
                    json.dumps({"success": False, "error": "Admin access required"}),
                    headers=[("Content-Type", "application/json")],
                )

            policy = request.env["customer.support.sla.policy"].sudo().browse(policy_id)
            if not policy.exists():
                return request.make_response(
                    json.dumps({"success": False, "error": "Policy not found"}),
                    headers=[("Content-Type", "application/json")],
                )

            policy.write(
                {
                    "name": post.get("sla_name", policy.name).strip(),
                    "response_time": int(
                        post.get("sla_response_time", policy.response_time)
                    ),
                    "time_unit": post.get("sla_time_unit", policy.time_unit),
                    "priority_level": post.get(
                        "sla_priority_level", policy.priority_level
                    ),
                    "description": post.get(
                        "sla_description", policy.description or ""
                    ).strip(),
                }
            )

            _logger.info(f"SLA policy {policy_id} updated by {user.name}")
            return request.make_response(
                json.dumps({"success": True, "message": "SLA policy updated"}),
                headers=[("Content-Type", "application/json")],
            )

        except Exception as e:
            _logger.error(f"update_policy error: {e}")
            return request.make_response(
                json.dumps({"success": False, "error": str(e)}),
                headers=[("Content-Type", "application/json")],
            )

    # ── POST: delete a SLA policy ─────────────────────────────────────────────

    @http.route(
        "/customer_support/sla/<int:policy_id>/delete",
        type="http",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def delete_policy(self, policy_id, **kwargs):
        """
        Soft-deletes (archives) an SLA policy.
        Returns JSON.
        """
        try:
            user = request.env.user
            if not user.has_group("base.group_system"):
                return request.make_response(
                    json.dumps({"success": False, "error": "Admin access required"}),
                    headers=[("Content-Type", "application/json")],
                )

            policy = request.env["customer.support.sla.policy"].sudo().browse(policy_id)
            if not policy.exists():
                return request.make_response(
                    json.dumps({"success": False, "error": "Policy not found"}),
                    headers=[("Content-Type", "application/json")],
                )

            policy.write({"active": False})
            _logger.info(f"SLA policy {policy_id} archived by {user.name}")

            return request.make_response(
                json.dumps({"success": True, "message": "Policy deleted"}),
                headers=[("Content-Type", "application/json")],
            )

        except Exception as e:
            _logger.error(f"delete_policy error: {e}")
            return request.make_response(
                json.dumps({"success": False, "error": str(e)}),
                headers=[("Content-Type", "application/json")],
            )
