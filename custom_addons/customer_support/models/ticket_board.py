# -*- coding: utf-8 -*-
"""
Ticket Board Models
====================
Provides a Trello-like board per ticket for focal persons.

  - CustomerSupportTicketColumn  → named columns (stages) on the board
  - CustomerSupportTicketTask    → tasks within a column, with member assignments
"""

from odoo import models, fields, api


class CustomerSupportTicketColumn(models.Model):
    _name = "customer_support.ticket.column"
    _description = "Ticket Board Column"
    _order = "sequence, id"

    ticket_id = fields.Many2one(
        "customer.support",
        string="Ticket",
        required=True,
        ondelete="cascade",
        index=True,
    )

    name = fields.Char(string="Column Name", required=True)

    sequence = fields.Integer(string="Order", default=10)

    color = fields.Char(
        string="Color",
        default="#e2e8f0",
        help="Hex color for the column header",
    )

    task_ids = fields.One2many(
        "customer_support.ticket.task",
        "column_id",
        string="Tasks",
    )

    task_count = fields.Integer(
        string="Total Tasks",
        compute="_compute_task_counts",
    )

    done_count = fields.Integer(
        string="Done Tasks",
        compute="_compute_task_counts",
    )

    @api.depends("task_ids", "task_ids.is_done")
    def _compute_task_counts(self):
        for col in self:
            col.task_count = len(col.task_ids)
            col.done_count = len(col.task_ids.filtered("is_done"))


class CustomerSupportTicketTask(models.Model):
    _name = "customer_support.ticket.task"
    _description = "Ticket Board Task"
    _order = "sequence, id"

    column_id = fields.Many2one(
        "customer_support.ticket.column",
        string="Column",
        required=True,
        ondelete="cascade",
        index=True,
    )

    ticket_id = fields.Many2one(
        "customer.support",
        string="Ticket",
        related="column_id.ticket_id",
        store=True,
        index=True,
    )

    name = fields.Char(string="Task Title", required=True)

    description = fields.Text(string="Description")

    project_member_ids = fields.Many2many(
        "customer_support.project.member",
        "cs_ticket_task_project_member_rel",
        "task_id",
        "member_id",
        string="Assigned Project Members",
    )

    member_ids = fields.Many2many(
        "res.users",
        "cs_ticket_task_member_rel",
        "task_id",
        "user_id",
        string="Assigned Members",
    )

    is_done = fields.Boolean(string="Done", default=False)

    sequence = fields.Integer(string="Order", default=10)

    due_date = fields.Date(string="Due Date")

    task_priority = fields.Selection(
        [
            ("none", "None"),
            ("low", "Low"),
            ("medium", "Medium"),
            ("high", "High"),
            ("urgent", "Urgent"),
        ],
        string="Priority",
        default="none",
    )

    checklist_ids = fields.One2many(
        "customer_support.task.checklist",
        "task_id",
        string="Checklist",
    )

    note_ids = fields.One2many(
        "customer_support.task.note",
        "task_id",
        string="Task Notes",
    )


class CustomerSupportTaskChecklist(models.Model):
    _name = "customer_support.task.checklist"
    _description = "Task Checklist Item"
    _order = "sequence, id"

    task_id = fields.Many2one(
        "customer_support.ticket.task",
        string="Task",
        required=True,
        ondelete="cascade",
        index=True,
    )
    name = fields.Char(string="Item", required=True)
    is_done = fields.Boolean(string="Done", default=False)
    sequence = fields.Integer(string="Order", default=10)


class CustomerSupportTaskNote(models.Model):
    _name = "customer_support.task.note"
    _description = "Task Resolving Note"
    _order = "create_date asc"

    task_id = fields.Many2one(
        "customer_support.ticket.task",
        string="Task",
        required=True,
        ondelete="cascade",
        index=True,
    )
    user_id = fields.Many2one(
        "res.users",
        string="Author",
        ondelete="set null",
    )
    author_name = fields.Char(string="Author Name")
    message = fields.Text(string="Note", required=True)
    create_date = fields.Datetime(string="Posted At", readonly=True)


class CustomerSupportTicketComment(models.Model):
    _name = "customer_support.ticket.comment"
    _description = "Ticket Internal Comment"
    _order = "create_date asc"

    ticket_id = fields.Many2one(
        "customer.support",
        string="Ticket",
        required=True,
        ondelete="cascade",
        index=True,
    )
    user_id = fields.Many2one(
        "res.users",
        string="Author",
        required=True,
        default=lambda self: self.env.user,
    )
    author_name = fields.Char(string="Author Display Name")
    message = fields.Text(string="Message", required=True)
    create_date = fields.Datetime(string="Posted At", readonly=True)


class CustomerSupportBoardProgress(models.Model):
    """Extend customer.support to expose board task-completion progress."""

    _inherit = "customer.support"

    column_ids = fields.One2many(
        "customer_support.ticket.column",
        "ticket_id",
        string="Board Columns",
    )

    board_task_total = fields.Integer(
        string="Total Board Tasks",
        compute="_compute_board_progress",
    )
    board_task_done = fields.Integer(
        string="Done Board Tasks",
        compute="_compute_board_progress",
    )
    board_progress = fields.Integer(
        string="Board Progress (%)",
        compute="_compute_board_progress",
        help="Percentage of board tasks marked as done",
    )

    @api.depends("column_ids", "column_ids.task_ids", "column_ids.task_ids.is_done")
    def _compute_board_progress(self):
        for ticket in self:
            all_tasks = ticket.column_ids.mapped("task_ids")
            total = len(all_tasks)
            done = len(all_tasks.filtered("is_done"))
            ticket.board_task_total = total
            ticket.board_task_done = done
            ticket.board_progress = int(done / total * 100) if total > 0 else 0
