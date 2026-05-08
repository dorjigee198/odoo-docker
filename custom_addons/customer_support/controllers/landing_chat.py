from odoo import http
from odoo.http import request


class CustomerSupportPublic(http.Controller):

    @http.route("/dragon-chat", type="http", auth="public", website=True)
    def public_chat(self, **kwargs):
        return request.render("customer_support.landing_chat")
