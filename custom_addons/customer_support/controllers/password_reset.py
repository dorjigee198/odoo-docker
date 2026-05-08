# -*- coding: utf-8 -*-
"""
Custom password recovery flow for Customer Support.

Routes:
- /customer_support/forgot_password (GET/POST)
- /customer_support/reset_password (GET/POST)
"""

import logging
from urllib.parse import quote

from odoo import _, http
from odoo.http import request
import werkzeug

_logger = logging.getLogger(__name__)


class CustomerSupportPasswordReset(http.Controller):
    """Custom forgot/reset password pages and handlers."""

    def _current_db(self):
        return request.session.db or request.env.cr.dbname

    def _public_login_url(self):
        db = self._current_db()
        return f"/customer_support/login?db={quote(db, safe='')}" if db else "/customer_support/login"

    @http.route(
        "/customer_support/forgot_password",
        type="http",
        auth="public",
        website=True,
        methods=["GET", "POST"],
    )
    def forgot_password(self, **post):
        user = request.env.user
        public_user = request.env.ref("base.public_user")
        if user and user.id != public_user.id and user.active:
            return werkzeug.utils.redirect(self._public_login_url())

        message = ""
        error = ""
        login_value = (post.get("login") or "").strip()

        if request.httprequest.method == "POST":
            if not login_value:
                error = "Please enter your email address."
            else:
                try:
                    # Always produce a generic success response to avoid account enumeration.
                    users = (
                        request.env["res.users"]
                        .sudo()
                        .search(
                            [
                                "|",
                                ("login", "=", login_value),
                                ("email", "=", login_value),
                            ],
                            limit=1,
                        )
                    )
                    if users and users.active and users.partner_id and users.email:
                        partner = users.partner_id.sudo()
                        partner.signup_prepare(signup_type="reset")
                        token = partner._generate_signup_token()

                        base_url = (
                            request.env["ir.config_parameter"]
                            .sudo()
                            .get_param("web.base.url", "")
                            or (request.httprequest.url_root or "")
                        ).rstrip("/")
                        db = self._current_db()
                        reset_link = (
                            f"{base_url}/customer_support/reset_password?db={quote(db, safe='')}&token="
                            f"{quote(token, safe='')}"
                        )

                        template = request.env.ref(
                            "customer_support.mail_template_customer_support_password_reset",
                            raise_if_not_found=False,
                        )
                        if template:
                            template.sudo().with_context(
                                cs_reset_link=reset_link,
                                cs_user_name=users.name or users.login,
                            ).send_mail(users.id, force_send=False)
                        else:
                            _logger.error("Password reset template not found.")

                    message = (
                        "If an account exists for that email, password reset instructions "
                        "have been sent."
                    )
                except Exception as e:
                    _logger.exception("Forgot password request failed: %s", e)
                    message = (
                        "If an account exists for that email, password reset instructions "
                        "have been sent."
                    )

        response = request.render(
            "customer_support.forgot_password_page",
            {
                "error": error,
                "message": message,
                "login": login_value,
            },
        )
        response.headers["Cache-Control"] = (
            "no-store, no-cache, must-revalidate, max-age=0"
        )
        return response

    @http.route(
        "/customer_support/reset_password",
        type="http",
        auth="public",
        website=True,
        methods=["GET", "POST"],
    )
    def reset_password(self, **post):
        user = request.env.user
        public_user = request.env.ref("base.public_user")
        if user and user.id != public_user.id and user.active:
            return werkzeug.utils.redirect(self._public_login_url())

        token = (post.get("token") or request.params.get("token") or "").strip()
        error = ""
        message = ""
        invalid_token = False

        partner = False
        if token:
            try:
                partner = (
                    request.env["res.partner"]
                    .sudo()
                    ._signup_retrieve_partner(
                        token,
                        check_validity=True,
                        raise_exception=True,
                    )
                )
            except Exception:
                invalid_token = True
        else:
            invalid_token = True

        if request.httprequest.method == "POST" and not invalid_token:
            password = post.get("password", "")
            confirm_password = post.get("confirm_password", "")

            if not password or not confirm_password:
                error = "Please enter and confirm your new password."
            elif password != confirm_password:
                error = "Passwords do not match."
            elif len(password) < 8:
                error = "Password must be at least 8 characters long."
            else:
                try:
                    target_user = partner.user_ids[:1]
                    if not target_user:
                        invalid_token = True
                        error = "This reset link is no longer valid."
                    else:
                        target_user.sudo().write({"password": password})
                        partner.sudo().write({"signup_type": False})
                        db = self._current_db()
                        return werkzeug.utils.redirect(
                            "/customer_support/login?db="
                            + quote(db, safe="")
                            + "&success="
                            + quote(
                                "Your password has been reset successfully. Please sign in.",
                                safe="",
                            )
                        )
                except Exception as e:
                    _logger.exception("Password reset failed: %s", e)
                    error = _("Unable to reset password right now. Please try again.")

        response = request.render(
            "customer_support.reset_password_page",
            {
                "token": token,
                "error": error,
                "message": message,
                "invalid_token": invalid_token,
            },
        )
        response.headers["Cache-Control"] = (
            "no-store, no-cache, must-revalidate, max-age=0"
        )
        return response
