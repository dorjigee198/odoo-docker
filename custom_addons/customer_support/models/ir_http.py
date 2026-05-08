# -*- coding: utf-8 -*-
"""
IR HTTP Override
================
Intercepts Odoo's default /web/login redirect and replaces it with
the custom portal login page for all /customer_support/* routes.

Strategy: override _auth_method_user so that for customer_support paths
we raise an HTTPException wrapping a redirect to our custom login instead
of SessionExpiredException (which Odoo's dispatcher turns into /web/login).
"""

import logging
import werkzeug.utils
import werkzeug.exceptions

from odoo import models
from odoo.http import request, SessionExpiredException

_logger = logging.getLogger(__name__)

_CS_PREFIX = "/customer_support/"


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    @classmethod
    def _auth_method_user(cls):
        """
        Override: for unauthenticated requests to /customer_support/* routes,
        redirect to our custom login page instead of Odoo's /web/login.
        """
        if request.env.uid in [None] + cls._get_public_users():
            path = (request.httprequest.full_path or request.httprequest.path or "")
            if path.startswith(_CS_PREFIX):
                from urllib.parse import quote
                redirect_url = "/customer_support/login?next=" + quote(path, safe="")
                _logger.debug("CS auth redirect: %s -> %s", path, redirect_url)
                # Wrap the redirect as an HTTPException so Odoo's dispatcher
                # returns it directly (isinstance(exc, HTTPException) → return exc)
                redirect_resp = werkzeug.utils.redirect(redirect_url, 302)
                exc = werkzeug.exceptions.HTTPException(response=redirect_resp)
                # Do NOT set exc.code — Odoo only returns exc.get_response() when
                # exc.code is None (see _serve_db). Setting it causes a re-raise
                # that the website module mishandles as a missing template.
                raise exc
            raise SessionExpiredException("Session expired")

        # Authenticated — let the base class do its additional checks
        super()._auth_method_user()
