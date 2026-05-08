# -*- coding: utf-8 -*-
"""
Project Member Model
====================
Stores team members assigned to a project with their roles.

Two kinds of members:
  - Focal Person: always an Odoo internal user (user_id set, role='focal_person')
  - Team Member: name + email entered manually, no Odoo account required
                 (user_id empty, member_name / member_email set)
"""

from odoo import models, fields, api


ROLE_LABELS = {
    "focal_person": "Focal Person",
    "frontend_dev": "Frontend Developer",
    "backend_dev": "Backend Developer",
    "network_manager": "Network Manager",
    "designer": "UI/UX Designer",
    "qa_engineer": "QA Engineer",
    "other": "Other",
}


class CustomerSupportProjectMember(models.Model):
    _name = "customer_support.project.member"
    _description = "Project Team Member"
    _order = "role, id"

    project_id = fields.Many2one(
        "customer_support.project",
        string="Project",
        required=True,
        ondelete="cascade",
        index=True,
    )

    # Set for focal persons (Odoo internal users); empty for manual team members
    user_id = fields.Many2one(
        "res.users",
        string="User",
        domain="[('active', '=', True)]",
    )

    # Used for manually-entered team members (non-Odoo-user)
    member_name = fields.Char(string="Name")
    member_email = fields.Char(string="Email")

    role = fields.Selection(
        [
            ("focal_person", "Focal Person"),
            ("frontend_dev", "Frontend Developer"),
            ("backend_dev", "Backend Developer"),
            ("network_manager", "Network Manager"),
            ("designer", "UI/UX Designer"),
            ("qa_engineer", "QA Engineer"),
            ("other", "Other"),
        ],
        string="Role",
        required=True,
        default="other",
    )

    role_label = fields.Char(
        string="Role Label",
        compute="_compute_role_label",
        store=True,
    )

    display_name_computed = fields.Char(
        string="Member Display Name",
        compute="_compute_display_name_field",
        store=True,
    )

    display_email = fields.Char(
        string="Display Email",
        compute="_compute_display_email",
        store=True,
    )

    @api.depends("role")
    def _compute_role_label(self):
        for rec in self:
            rec.role_label = ROLE_LABELS.get(rec.role, rec.role)

    @api.depends("user_id", "member_name")
    def _compute_display_name_field(self):
        for rec in self:
            rec.display_name_computed = rec.user_id.name if rec.user_id else (rec.member_name or "")

    @api.depends("user_id", "member_email")
    def _compute_display_email(self):
        for rec in self:
            rec.display_email = rec.user_id.email if rec.user_id else (rec.member_email or "")
