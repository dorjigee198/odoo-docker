# models/project_report.py
from odoo import models, fields


class CustomerSupportProjectReport(models.Model):
    _name = "customer_support.project.report"
    _description = "Project Closure Report"
    _order = "generated_on desc"

    # ── Identity ────────────────────────────────────────────────
    project_name    = fields.Char(string="Project Name",  required=True)
    project_key     = fields.Char(string="Project Key")
    project_type    = fields.Char(string="Project Type")
    start_date      = fields.Date(string="Start Date")
    end_date        = fields.Date(string="End Date")
    generated_on    = fields.Datetime(string="Generated On", default=fields.Datetime.now)

    # ── Tech stack & goals ───────────────────────────────────────
    tech_languages  = fields.Char(string="Programming Languages")
    tech_frameworks = fields.Char(string="Frameworks")
    tech_databases  = fields.Char(string="Databases")
    project_goals   = fields.Text(string="Project Goals")
    compliance_flags = fields.Char(string="Compliance Requirements")  # comma-separated

    # ── Team ────────────────────────────────────────────────────
    focal_person    = fields.Char(string="Focal Person")
    team_members    = fields.Text(string="Team Members (JSON)")

    # ── Customers ───────────────────────────────────────────────
    customers       = fields.Text(string="Customers (JSON)")  # [{name, email}]

    # ── Ticket statistics ────────────────────────────────────────
    total_tickets       = fields.Integer(string="Total Tickets")
    resolved_tickets    = fields.Integer(string="Resolved Tickets")
    open_tickets        = fields.Integer(string="Open at Closure")
    avg_resolution_hrs  = fields.Float(string="Avg Resolution Hours", digits=(10, 1))

    # Priority breakdown
    priority_low        = fields.Integer(string="Low Priority")
    priority_medium     = fields.Integer(string="Medium Priority")
    priority_high       = fields.Integer(string="High Priority")
    priority_urgent     = fields.Integer(string="Urgent Priority")

    # State breakdown at closure (JSON: {new, assigned, in_progress, pending, resolved, closed})
    state_breakdown     = fields.Text(string="State Breakdown (JSON)")

    # Open tickets at closure (JSON: [{name, subject, priority, state}])
    open_ticket_details = fields.Text(string="Open Ticket Details (JSON)")

    # Full ticket register (JSON: [{ticket_id, subject, description, customer, raised_on,
    #                                resolved_on, solved_by, sla_status, priority, state}])
    all_ticket_details  = fields.Text(string="All Ticket Details (JSON)")

    # SLA
    sla_met             = fields.Integer(string="SLA Met")
    sla_breached        = fields.Integer(string="SLA Breached")

    # ── Task board summary ───────────────────────────────────────
    total_tasks         = fields.Integer(string="Total Tasks")
    completed_tasks     = fields.Integer(string="Completed Tasks")
