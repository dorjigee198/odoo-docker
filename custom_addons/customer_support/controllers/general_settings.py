# -*- coding: utf-8 -*-
import logging
import pytz
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class GeneralSettingsController(http.Controller):

    @http.route(
        "/customer_support/admin_dashboard/general_settings/save",
        type="jsonrpc",
        auth="user",
        methods=["POST"],
        csrf=True,
    )
    def save_general_settings(self, **kw):
        try:
            if not request.env.user.has_group("base.group_system"):
                return {"error": "Access denied"}

            system_name = (kw.get("system_name") or "").strip()
            timezone = (kw.get("timezone") or "UTC").strip()

            if not system_name:
                return {"error": "System name cannot be empty"}

            if timezone not in pytz.all_timezones:
                return {"error": "Invalid timezone selected"}

            config = request.env["ir.config_parameter"].sudo()
            config.set_param("customer_support.system_name", system_name)
            config.set_param("customer_support.timezone", timezone)

            _logger.info(
                f"General settings saved: name={system_name!r}, tz={timezone!r}"
            )
            return {"success": True, "system_name": system_name, "timezone": timezone}

        except Exception as e:
            _logger.error(f"save_general_settings error: {e}")
            return {"error": str(e)}
