# -*- coding: utf-8 -*-
"""
Customer Notification Model
============================
Stores persistent bell notifications for portal customers.

Triggered by:
  - Ticket status change  (type: status_change)
  - Ticket assigned       (type: assigned)
  - SLA breached          (type: sla_breach)

Persists until the customer clicks "Mark all read".
"""

from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class CustomerSupportNotification(models.Model):
    _name = "customer.support.notification"
    _description = "Customer Support Notification"
    _order = "create_date desc"

    ticket_id = fields.Many2one(
        "customer.support",
        string="Ticket",
        required=True,
        ondelete="cascade",
    )
    ticket_name = fields.Char(string="Ticket Name", required=True)
    customer_id = fields.Many2one(
        "res.partner",
        string="Customer",
        required=True,
    )
    notification_type = fields.Selection(
        [
            ("status_change", "Status Changed"),
            ("assigned", "Ticket Assigned"),
            ("sla_breach", "SLA Breached"),
        ],
        string="Type",
        required=True,
        default="status_change",
    )
    message = fields.Char(string="Message", required=True)
    is_read = fields.Boolean(string="Read", default=False)
    create_date = fields.Datetime(string="Created", readonly=True)

    @api.model
    def create_notification(self, ticket, notif_type, message):
        """
        Helper to safely create a notification for the ticket's customer.
        Skips if the ticket has no customer.
        """
        if not ticket.customer_id:
            return
        try:
            self.sudo().create(
                {
                    "ticket_id": ticket.id,
                    "ticket_name": ticket.name,
                    "customer_id": ticket.customer_id.id,
                    "notification_type": notif_type,
                    "message": message,
                }
            )
            _logger.info(
                f"Notification created for {ticket.customer_id.name} "
                f"— {ticket.name}: {message}"
            )
        except Exception as e:
            _logger.error(f"Failed to create notification for {ticket.name}: {e}")
