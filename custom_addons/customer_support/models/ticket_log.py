# -*- coding: utf-8 -*-
"""
Customer Support Ticket Log
============================
A lightweight, unified activity log for the ticket detail timeline.
Captures: status changes, assignment changes, SLA events, ticket creation.

Written to automatically by:
  - CustomerSupport.create()     → 'created' event
  - CustomerSupport.write()      → 'status' and 'assign' events
  - _cron_check_sla_breaches()   → 'sla' events
"""

from odoo import models, fields


class CustomerSupportTicketLog(models.Model):
    _name = "customer.support.ticket.log"
    _description = "Ticket Activity Log"
    _order = "timestamp desc"

    ticket_id = fields.Many2one(
        "customer.support",
        string="Ticket",
        required=True,
        ondelete="cascade",
        index=True,
    )

    event_type = fields.Selection(
        [
            # Ticket-level events
            ("created",  "Ticket Created"),
            ("status",   "Status Changed"),
            ("assign",   "Assignment Changed"),
            ("sla",      "SLA Event"),
            # Board events
            ("board_col_add",      "Column Added"),
            ("board_col_rename",   "Column Renamed"),
            ("board_col_delete",   "Column Deleted"),
            ("board_task_add",     "Task Added"),
            ("board_task_done",    "Task Completed"),
            ("board_task_undone",  "Task Reopened"),
            ("board_task_move",    "Task Moved"),
            ("board_task_assign",  "Task Assigned"),
            ("board_task_edit",    "Task Edited"),
            ("board_task_delete",  "Task Deleted"),
            ("board_checklist_add",  "Checklist Item Added"),
            ("board_checklist_done", "Checklist Item Done"),
            ("board_comment",      "Internal Note Posted"),
            ("board_reply",        "Reply Sent to Customer"),
            ("board_invite",       "Member Invited"),
        ],
        string="Event Type",
        required=True,
        index=True,
    )

    # Who triggered it
    actor_id = fields.Many2one(
        "res.users",
        string="Triggered By",
        default=lambda self: self.env.user,
    )

    # Human-readable summary shown in the timeline title
    summary = fields.Char(string="Summary", required=True)

    # Optional detail text shown in the timeline body
    detail = fields.Text(string="Detail")

    # For status changes: store old and new values
    old_value = fields.Char(string="Previous Value")
    new_value = fields.Char(string="New Value")

    timestamp = fields.Datetime(
        string="Timestamp",
        required=True,
        default=fields.Datetime.now,
        index=True,
    )
