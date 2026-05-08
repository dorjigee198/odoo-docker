# -*- coding: utf-8 -*-
"""
SLA Policy Model
================
Defines named SLA policies that admins create in Ticket Settings.
Each policy specifies a response time, the unit (hours/days/weeks),
and optionally which priority level it is designed for.

When a ticket is assigned, the admin selects a policy and the system
automatically calculates the SLA deadline on the ticket.
"""

from odoo import models, fields, api
from datetime import timedelta
import logging

_logger = logging.getLogger(__name__)


class CustomerSupportSLAPolicy(models.Model):
    _name = "customer.support.sla.policy"
    _description = "Customer Support SLA Policy"
    _order = "priority_level, response_time"

    name = fields.Char(
        string="Policy Name",
        required=True,
        help="e.g. 'Critical Response', 'Standard Support'",
    )

    description = fields.Text(
        string="Description",
        help="Optional notes about when to use this policy",
    )

    response_time = fields.Integer(
        string="Response Time",
        required=True,
        default=24,
        help="Number of time units within which the ticket must be resolved",
    )

    time_unit = fields.Selection(
        [
            ("hours", "Hours"),
            ("days", "Days"),
            ("weeks", "Weeks"),
        ],
        string="Time Unit",
        required=True,
        default="hours",
    )

    priority_level = fields.Selection(
        [
            ("low", "Low"),
            ("medium", "Medium"),
            ("high", "High"),
            ("urgent", "Urgent"),
            ("any", "Any Priority"),
        ],
        string="Applies To Priority",
        required=True,
        default="any",
        help="Which ticket priority this SLA is designed for",
    )

    active = fields.Boolean(
        string="Active",
        default=True,
    )

    # Computed display field for dropdowns
    display_name_full = fields.Char(
        string="Full Name",
        compute="_compute_display_name_full",
        store=True,
    )

    @api.depends("name", "response_time", "time_unit")
    def _compute_display_name_full(self):
        for record in self:
            record.display_name_full = (
                f"{record.name} ({record.response_time} {record.time_unit})"
            )

    def get_deadline_from_now(self):
        """
        Calculate the SLA deadline from the current datetime.
        Returns a datetime object.
        """
        self.ensure_one()
        now = fields.Datetime.now()

        if self.time_unit == "hours":
            return now + timedelta(hours=self.response_time)
        elif self.time_unit == "days":
            return now + timedelta(days=self.response_time)
        elif self.time_unit == "weeks":
            return now + timedelta(weeks=self.response_time)

        return now + timedelta(hours=self.response_time)
