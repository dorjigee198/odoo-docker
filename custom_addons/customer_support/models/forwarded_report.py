# -*- coding: utf-8 -*-
from odoo import models, fields


class CustomerForwardedReport(models.Model):
    _name = "customer_support.forwarded.report"
    _description = "Forwarded Project Closure Report"
    _order = "forwarded_on desc"

    project_report_id = fields.Many2one(
        "customer_support.project.report",
        string="Closure Report",
        ondelete="cascade",
        required=True,
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Customer",
        required=True,
    )
    forwarded_by = fields.Many2one("res.users", string="Forwarded By")
    forwarded_on = fields.Datetime(string="Forwarded On", default=fields.Datetime.now)
    project_name = fields.Char(
        related="project_report_id.project_name",
        string="Project Name",
        store=True,
    )
    email_sent = fields.Boolean(string="Email Sent", default=False)
