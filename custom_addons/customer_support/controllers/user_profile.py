# -*- coding: utf-8 -*-
import base64
import json
import logging
from odoo import http
from odoo.http import request
import werkzeug

_logger = logging.getLogger(__name__)


class UserProfile(http.Controller):

    def _json_resp(self, data):
        return request.make_response(
            json.dumps(data),
            headers=[("Content-Type", "application/json")],
        )

    def _is_admin(self, user):
        return user.has_group("base.group_system")

    def _is_support_user(self, user):
        return user.has_group("base.group_user") and not self._is_admin(user)

    def _login_redirect_url(self):
        from urllib.parse import quote

        next_path = request.httprequest.path or "/customer_support"
        return "/customer_support/login?next=" + quote(next_path, safe="")

    def _ensure_logged_in_page(self):
        if not request.session.uid:
            return werkzeug.utils.redirect(self._login_redirect_url())
        return None

    def _ensure_logged_in_json(self):
        if request.session.uid:
            return None
        return self._json_resp(
            {
                "success": False,
                "error": "Session expired. Please log in again.",
                "redirect_url": self._login_redirect_url(),
            }
        )

    @http.route(
        "/customer_support/profile/close",
        type="http",
        auth="public",
        website=True,
    )
    def close_profile(self, target=None, **kwargs):
        """Close action that avoids auth redirect edge-cases after password changes."""
        if not request.session.uid:
            return werkzeug.utils.redirect("/customer_support/login")

        user = request.env.user
        if target == "admin" and self._is_admin(user):
            return werkzeug.utils.redirect("/customer_support/admin_dashboard")
        if target == "support" and user.has_group("base.group_user"):
            return werkzeug.utils.redirect("/customer_support/support_dashboard")
        if user.has_group("base.group_portal"):
            return werkzeug.utils.redirect("/customer_support/dashboard")
        if user.has_group("base.group_user"):
            return werkzeug.utils.redirect("/customer_support/support_dashboard")
        if self._is_admin(user):
            return werkzeug.utils.redirect("/customer_support/admin_dashboard")
        return werkzeug.utils.redirect("/customer_support/login")

    @http.route(
        "/customer_support/profile",
        type="http",
        auth="public",
        website=True,
    )
    def display_profile(self, **kwargs):
        login_redirect = self._ensure_logged_in_page()
        if login_redirect:
            return login_redirect

        user = request.env.user
        if user.has_group("base.group_system"):
            return werkzeug.utils.redirect("/customer_support/admin_dashboard")
        if user.has_group("base.group_user"):
            return werkzeug.utils.redirect("/customer_support/support_dashboard")

        response = request.render(
            "customer_support.portal_profile_page",
            {
                "user": user,
                "profile_route_base": "/customer_support/profile",
                "back_url": "/customer_support/profile/close?target=portal",
            },
        )
        response.headers["Cache-Control"] = (
            "no-store, no-cache, must-revalidate, max-age=0"
        )
        return response

    @http.route(
        "/customer_support/admin/profile",
        type="http",
        auth="public",
        website=True,
    )
    def display_admin_profile(self, **kwargs):
        login_redirect = self._ensure_logged_in_page()
        if login_redirect:
            return login_redirect

        user = request.env.user
        if not self._is_admin(user):
            return werkzeug.utils.redirect("/customer_support/dashboard")

        response = request.render(
            "customer_support.portal_profile_page",
            {
                "user": user,
                "profile_route_base": "/customer_support/admin/profile",
                "back_url": "/customer_support/profile/close?target=admin",
            },
        )
        response.headers["Cache-Control"] = (
            "no-store, no-cache, must-revalidate, max-age=0"
        )
        return response

    @http.route(
        "/customer_support/support/profile",
        type="http",
        auth="public",
        website=True,
    )
    def display_support_profile(self, **kwargs):
        login_redirect = self._ensure_logged_in_page()
        if login_redirect:
            return login_redirect

        user = request.env.user
        if self._is_admin(user):
            return werkzeug.utils.redirect("/customer_support/admin_dashboard")
        if not self._is_support_user(user):
            return werkzeug.utils.redirect("/customer_support/dashboard")

        response = request.render(
            "customer_support.portal_profile_page",
            {
                "user": user,
                "profile_route_base": "/customer_support/support/profile",
                "back_url": "/customer_support/profile/close?target=support",
            },
        )
        response.headers["Cache-Control"] = (
            "no-store, no-cache, must-revalidate, max-age=0"
        )
        return response

    @http.route(
        "/customer_support/profile/update_password",
        type="http",
        auth="public",
        methods=["POST"],
        website=True,
        csrf=True,
    )
    def update_password(self, **post):
        """AJAX — returns JSON {success, error?}."""
        auth_error = self._ensure_logged_in_json()
        if auth_error:
            return auth_error

        user = request.env.user
        old_pwd = (post.get("old_pwd") or "").strip()
        new_pwd = (post.get("new_pwd") or "").strip()
        confirm_pwd = (post.get("confirm_pwd") or "").strip()

        if not old_pwd or not new_pwd or not confirm_pwd:
            return self._json_resp(
                {"success": False, "error": "All fields are required."}
            )
        if new_pwd != confirm_pwd:
            return self._json_resp(
                {"success": False, "error": "New passwords do not match."}
            )
        if len(new_pwd) < 8:
            return self._json_resp(
                {"success": False, "error": "Password must be at least 8 characters."}
            )
        try:
            user.change_password(old_pwd, new_pwd)
            return self._json_resp({"success": True})
        except Exception:
            return self._json_resp(
                {"success": False, "error": "Current password is incorrect."}
            )

    @http.route(
        "/customer_support/admin/profile/update_password",
        type="http",
        auth="public",
        methods=["POST"],
        website=True,
        csrf=True,
    )
    def update_admin_password(self, **post):
        auth_error = self._ensure_logged_in_json()
        if auth_error:
            return auth_error

        user = request.env.user
        if not self._is_admin(user):
            return self._json_resp({"success": False, "error": "Unauthorized."})
        return self.update_password(**post)

    @http.route(
        "/customer_support/support/profile/update_password",
        type="http",
        auth="public",
        methods=["POST"],
        website=True,
        csrf=True,
    )
    def update_support_password(self, **post):
        auth_error = self._ensure_logged_in_json()
        if auth_error:
            return auth_error

        user = request.env.user
        if not self._is_support_user(user):
            return self._json_resp({"success": False, "error": "Unauthorized."})
        return self.update_password(**post)

    @http.route(
        "/customer_support/profile/update_picture",
        type="http",
        auth="public",
        methods=["POST"],
        website=True,
        csrf=True,
    )
    def update_picture(self, **post):
        """AJAX — returns JSON {success, avatar_url?, error?}."""
        auth_error = self._ensure_logged_in_json()
        if auth_error:
            return auth_error

        user = request.env.user

        try:
            f = request.httprequest.files.get("avatar")
            if not f or not f.filename:
                return self._json_resp({"success": False, "error": "No file received."})
            data = f.read()
            if not data:
                return self._json_resp({"success": False, "error": "Empty file."})
            user.partner_id.sudo().write(
                {"image_1920": base64.b64encode(data).decode("utf-8")}
            )
            avatar_url = "/web/image/res.users/%d/avatar_128?t=%d" % (
                user.id,
                int(__import__("time").time()),
            )
            return self._json_resp({"success": True, "avatar_url": avatar_url})
        except Exception as e:
            _logger.error(f"Profile picture update error: {e}")
            return self._json_resp(
                {"success": False, "error": "Failed to update picture."}
            )

    @http.route(
        "/customer_support/admin/profile/update_picture",
        type="http",
        auth="public",
        methods=["POST"],
        website=True,
        csrf=True,
    )
    def update_admin_picture(self, **post):
        auth_error = self._ensure_logged_in_json()
        if auth_error:
            return auth_error

        user = request.env.user
        if not self._is_admin(user):
            return self._json_resp({"success": False, "error": "Unauthorized."})
        return self.update_picture(**post)

    @http.route(
        "/customer_support/support/profile/update_picture",
        type="http",
        auth="public",
        methods=["POST"],
        website=True,
        csrf=True,
    )
    def update_support_picture(self, **post):
        auth_error = self._ensure_logged_in_json()
        if auth_error:
            return auth_error

        user = request.env.user
        if not self._is_support_user(user):
            return self._json_resp({"success": False, "error": "Unauthorized."})
        return self.update_picture(**post)
