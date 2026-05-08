# models/project_config.py
from odoo import models, fields, api


class CustomerSupportProjectConfig(models.Model):
    _name = "customer_support.project.config"
    _description = "Project Configuration"

    # Link to the main project table
    project_id = fields.Many2one(
        "customer_support.project", string="Project", required=True, ondelete="cascade"
    )

    # Project Details
    project_type = fields.Selection(
        [
            ("web_app", "Web Application"),
            ("mobile", "Mobile Application"),
            ("machine_learning", "Machine Learning"),
            ("iot", "IoT Platform"),
            ("api", "API / Backend Service"),
            ("other", "Other"),
        ],
        string="Project Type",
        required=True,
    )

    start_date = fields.Date(string="Start Date", required=True)
    end_date = fields.Date(string="Target End Date")

    # Technology Stack
    programming_languages = fields.Char(string="Programming Languages")
    frameworks = fields.Char(string="Frameworks")
    databases = fields.Char(string="Databases")

    # Project Goals
    project_goals = fields.Text(string="Project Goals & Objectives")

    # Compliance Requirements
    compliance_gdpr = fields.Boolean(string="GDPR")
    compliance_hipaa = fields.Boolean(string="HIPAA")
    compliance_pci_dss = fields.Boolean(string="PCI DSS")
    compliance_iso27001 = fields.Boolean(string="ISO 27001")

    # Optional: track create and write dates automatically
    create_date = fields.Datetime(string="Created On", readonly=True)
    write_date = fields.Datetime(string="Last Updated", readonly=True)

    _unique_project_config = models.Constraint(
        'unique(project_id)',
        'Each project can have only one configuration.',
    )
