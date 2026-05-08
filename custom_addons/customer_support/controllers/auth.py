# -*- coding: utf-8 -*-
"""
Authentication Controller
=========================
Handles all public-facing authentication routes for the Customer Support Portal:
  - Landing page
  - Login page (GET)
  - Login form submission and session handling (POST)
  - Logout (standard and manual)

No authentication is required for any route in this file.
Role-based redirection is handled after successful login.
"""

import logging
from urllib.parse import urlsplit
from odoo import http
from odoo.http import request
import werkzeug

_logger = logging.getLogger(__name__)


class CustomerSupportAuth(http.Controller):
    """
    Handles authentication flow:
      Public user → login → authenticate → redirect to correct dashboard
      Any user    → logout → landing page
    """

    # =========================================================================
    # LANDING PAGE
    # =========================================================================

    @http.route("/customer_support", type="http", auth="public", website=True)
    def landing_page(self, **kw):
        """
        Landing Page - Always shown. If the user is already logged in,
        the CTA button changes to 'Go to Dashboard' instead of 'Get Started'.
        """
        user = request.env.user
        public_user = request.env.ref("base.public_user")
        dashboard_url = ""
        if user and user.id != public_user.id and user.active:
            if user.has_group("base.group_system"):
                dashboard_url = "/customer_support/admin_dashboard"
            elif user.has_group("base.group_user"):
                dashboard_url = "/customer_support/support_dashboard"
            elif user.has_group("base.group_portal"):
                dashboard_url = "/customer_support/dashboard"

        response = request.render(
            "customer_support.landing_page",
            {
                "dashboard_url": dashboard_url,
            },
        )
        response.headers["Cache-Control"] = (
            "no-store, no-cache, must-revalidate, max-age=0"
        )
        return response

    # =========================================================================
    # LOGIN
    # =========================================================================

    @http.route("/customer_support/login", type="http", auth="public", website=True)
    def support_login(self, **kw):
        """
        Login Page - Renders the custom login form
        Working: Shows login form with email/password fields
        Access: Public (no login required) — redirects already-authenticated users
        """
        user = request.env.user
        public_user = request.env.ref("base.public_user")
        # Allow email links to force showing the login page even if a different
        # user is currently authenticated in the browser by supplying
        # ?force_login=1 — this prevents accidental access as an admin/support
        # when a customer clicks an email link from a shared browser.
        force_login = str(kw.get("force_login", "")).lower() in ("1", "true", "yes")
        if user and user.id != public_user.id and user.active and not force_login:
            # User is already logged in — redirect to their dashboard
            if user.has_group("base.group_system"):
                return werkzeug.utils.redirect("/customer_support/admin_dashboard")
            elif user.has_group("base.group_user"):
                return werkzeug.utils.redirect("/customer_support/support_dashboard")
            elif user.has_group("base.group_portal"):
                return werkzeug.utils.redirect("/customer_support/dashboard")

        # Accept both ?next= (from our ir.http override) and ?redirect= (legacy)
        next_url = kw.get("next", "") or kw.get("redirect", "")
        response = request.render(
            "customer_support.portal_login_page",
            {
                "error": kw.get("error", ""),
                "success": kw.get("success", ""),
                "redirect": next_url,
            },
        )
        response.headers["Cache-Control"] = (
            "no-store, no-cache, must-revalidate, max-age=0"
        )
        return response

    @http.route(
        "/customer_support/authenticate",
        type="http",
        auth="public",
        methods=["POST"],
        website=True,
        csrf=True,
    )
    def support_authenticate(self, **post):
        """
        Authentication Handler - Processes login form submission
        Working: Validates credentials, creates session, redirects to the
                 correct dashboard based on the user's role.
                 If a redirect param is present (e.g. from an email link),
                 portal users are sent there instead of the default dashboard.
        Access: Public (no login required)

        Redirect targets:
          - System Admin  → /customer_support/admin_dashboard
          - Portal User   → redirect param OR /customer_support/dashboard
          - Internal User → /customer_support/support_dashboard
        """
        try:
            email = post.get("email", "").strip()
            password = post.get("password", "")

            # ← ADDED: read the redirect URL submitted as a hidden form field
            redirect_url = post.get("redirect", "").strip()

            _logger.info(f"Login attempt for email/login: {email}")

            # Validate that both fields are provided
            if not email or not password:
                return werkzeug.utils.redirect(
                    "/customer_support/login?error=Email and password are required"
                )

            # Ensure a database connection is available
            db = request.session.db
            if not db:
                return werkzeug.utils.redirect(
                    "/customer_support/login?error=Database connection error"
                )

            # Search for matching users by login OR email field
            uid = False
            users = (
                request.env["res.users"]
                .sudo()
                .search(["|", ("login", "=", email), ("email", "=", email)])
            )

            # Try authenticating each matching user until one succeeds
            for u in users:
                try:
                    auth_info = request.session.authenticate(
                        request.env,
                        {"type": "password", "login": u.login, "password": password},
                    )
                    uid = auth_info.get("uid") if auth_info else False
                except Exception as ex:
                    _logger.exception(f"authenticate raised for user {u.login}: {ex}")
                    uid = False
                if uid:
                    break

            if uid:
                user = request.env["res.users"].browse(uid)

                # Block inactive accounts immediately
                if not user.active:
                    request.session.logout()
                    return werkzeug.utils.redirect(
                        "/customer_support/login?error=Your account is inactive"
                    )

                # Route to the correct dashboard based on the user's role
                # Validate redirect_url — allow only safe in-portal relative paths.
                safe_redirect = ""
                if redirect_url:
                    parts = urlsplit(redirect_url)
                    path = parts.path or ""
                    if (
                        not parts.scheme
                        and not parts.netloc
                        and path.startswith("/customer_support/")
                        and not path.startswith("/customer_support//")
                        and ".." not in path
                        and "\\" not in redirect_url
                        and "\x00" not in redirect_url
                    ):
                        safe_redirect = redirect_url

                if user.has_group("base.group_system"):
                    request.session["customer_support_login"] = True
                    destination = safe_redirect or "/customer_support/admin_dashboard"
                    return werkzeug.utils.redirect(destination)

                elif user.has_group("base.group_portal"):
                    request.session["customer_support_login"] = True
                    destination = safe_redirect or "/customer_support/dashboard"
                    return werkzeug.utils.redirect(destination)

                elif user.has_group("base.group_user"):
                    request.session["customer_support_login"] = True
                    destination = safe_redirect or "/customer_support/support_dashboard"
                    return werkzeug.utils.redirect(destination)

                else:
                    # Authenticated but no recognised role — deny access
                    request.session.logout()
                    return werkzeug.utils.redirect(
                        "/customer_support/login?error=You do not have access to the customer support portal"
                    )

            # No user matched the supplied credentials
            return werkzeug.utils.redirect(
                "/customer_support/login?error=Invalid email or password"
            )

        except Exception as e:
            _logger.error(f"Login processing error: {str(e)}")
            return werkzeug.utils.redirect(
                "/customer_support/login?error=An error occurred during login. Please try again."
            )

    # =========================================================================
    # LOGOUT
    # =========================================================================

    @http.route("/customer_support/logout", type="http", auth="public", website=True)
    def support_logout(self, **kw):
        """
        Logout - Clears the session and redirects to the login page
        Access: All authenticated users
        """
        try:
            if request.session.uid:
                request.session.logout()
            response = werkzeug.utils.redirect("/customer_support/login?from_logout=1")
            response.headers["Cache-Control"] = (
                "no-store, no-cache, must-revalidate, max-age=0"
            )
            return response
        except Exception as e:
            _logger.error(f"Logout error: {str(e)}")
            response = werkzeug.utils.redirect("/customer_support/login?from_logout=1")
            response.headers["Cache-Control"] = (
                "no-store, no-cache, must-revalidate, max-age=0"
            )
            return response

    @http.route(
        "/customer_support/logout_manual", type="http", auth="public", website=True
    )
    def logout_manual(self):
        """
        Manual Logout - Alternative logout route
        Working: Clears the session and redirects to the login page
        Access: All authenticated users
        """
        if request.session.uid:
            request.session.logout()
        response = werkzeug.utils.redirect("/customer_support/login?from_logout=1")
        response.headers["Cache-Control"] = (
            "no-store, no-cache, must-revalidate, max-age=0"
        )
        return response
