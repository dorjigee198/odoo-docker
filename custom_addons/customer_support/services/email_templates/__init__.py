# -*- coding: utf-8 -*-
import os
import re
import logging

_logger = logging.getLogger(__name__)
_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "html")

def _load(filename):
    path = os.path.join(_TEMPLATE_DIR, filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        _logger.error(f"Email template not found: {path}")
        return f"<p>Email template missing: {filename}</p>"

def _render(template, **kwargs):
    """Safe render - replaces {{placeholder}} in HTML without breaking CSS curly braces"""
    for key, value in kwargs.items():
        template = template.replace("{{" + key + "}}", str(value) if value else "")
    return template

def render_welcome_customer(user_name, user_email, password, login_url):
    return _render(_load("welcome_customer.html"),
        user_name=user_name, user_email=user_email, password=password, login_url=login_url)

def render_welcome_agent(user_name, user_email, password, login_url):
    return _render(_load("welcome_agent.html"),
        user_name=user_name, user_email=user_email, password=password, login_url=login_url)

def render_assignment_agent(ticket, assigned_user, ticket_url):
    priority_colors = {"low": "#10b981", "medium": "#f59e0b", "high": "#ef4444", "urgent": "#7f1d1d"}
    return _render(_load("assignment_agent.html"),
        ticket_name=ticket.name, ticket_subject=ticket.subject,
        ticket_description=ticket.description, ticket_priority=ticket.priority,
        priority_color=priority_colors.get(ticket.priority, "#6b7280"),
        customer_name=ticket.customer_id.name, agent_name=assigned_user.name, ticket_url=ticket_url)

def render_assignment_customer(ticket, assigned_user, ticket_url):
    return _render(_load("assignment_customer.html"),
        ticket_name=ticket.name, ticket_subject=ticket.subject,
        customer_name=ticket.customer_id.name, agent_name=assigned_user.name, ticket_url=ticket_url)

def render_status_change(ticket, old_status, new_status, ticket_url):
    status_colors = {"assigned": "#1e5a8e", "in_progress": "#f59e0b", "resolved": "#10b981", "closed": "#6b7280"}
    status_messages = {
        "assigned": f"Your ticket has been assigned to {ticket.assigned_to.name if ticket.assigned_to else 'our support team'} and will be reviewed shortly.",
        "in_progress": "Our team is actively working on your issue. We will keep you updated on progress.",
        "resolved": "Your ticket has been resolved. Please review the solution and let us know if you need further help.",
        "closed": "Your ticket has been closed. Thank you for using our support portal.",
    }
    color = status_colors.get(new_status, "#1e5a8e")
    message = status_messages.get(new_status, f"Your ticket status has been updated to {new_status.replace('_', ' ').title()}.")
    return _render(_load("status_change.html"),
        ticket_name=ticket.name, ticket_subject=ticket.subject,
        customer_name=ticket.customer_id.name,
        old_status=old_status.replace("_", " ").title(),
        new_status=new_status.replace("_", " ").title(),
        new_status_raw=new_status, status_color=color,
        status_message=message, ticket_url=ticket_url)
