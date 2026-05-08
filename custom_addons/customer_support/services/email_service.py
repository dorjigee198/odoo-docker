# -*- coding: utf-8 -*-
"""
Email Service
=============
Coordinator for all customer support email notifications.
Template rendering is delegated to the email_templates package.
"""
import logging
from odoo.http import request
from .email_templates import (
    render_welcome_customer,
    render_welcome_agent,
    render_assignment_agent,
    render_assignment_customer,
    render_status_change,
)

_logger = logging.getLogger(__name__)


class EmailService:
    """Handles sending all customer support emails."""

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _get_default_email_from():
        try:
            mail_server = request.env["ir.mail_server"].sudo().search([], limit=1)
            if mail_server and mail_server.smtp_user:
                return mail_server.smtp_user
            default_from = (
                request.env["ir.config_parameter"].sudo().get_param("mail.default.from")
            )
            if default_from:
                return default_from
            return request.env.user.email or "noreply@example.com"
        except Exception as e:
            _logger.warning(f"Could not get default email: {e}, using fallback")
            return "noreply@example.com"

    @staticmethod
    def _get_base_url():
        base = request.env["ir.config_parameter"].sudo().get_param("web.base.url")
        return base.rstrip(
            "/"
        )  # ← FIXED: removes trailing slash to prevent double // in URLs

    @staticmethod
    def _send(subject, body_html, email_to, force_send=False):
        """Queue an email in Odoo and optionally trigger immediate send."""
        try:
            mail_vals = {
                "subject": subject,
                "body_html": body_html,
                "email_to": email_to,
                "email_from": EmailService._get_default_email_from(),
                "auto_delete": False,
            }
            mail = request.env["mail.mail"].sudo().create(mail_vals)
            if force_send:
                mail.send()
            _logger.info("Email queued for %s: %s", email_to, subject)
            return True
        except Exception:
            _logger.exception("Email send failed for %s: %s", email_to, subject)
            return False

    # ── Public send methods ───────────────────────────────────────────────────

    @staticmethod
    def send_welcome_email(user_email, user_name, password):
        """Send welcome email to a newly created customer."""
        try:
            login_url = f"{EmailService._get_base_url()}/customer_support/login?force_login=1"
            body = render_welcome_customer(user_name, user_email, password, login_url)
            EmailService._send("Welcome to Customer Support Portal", body, user_email, force_send=True)
            _logger.info(f"✓ Welcome email sent to {user_email}")
            return True
        except Exception as e:
            _logger.error(f"✗ Welcome email failed for {user_email}: {e}")
            return False

    @staticmethod
    def send_welcome_email_focal_person(user_email, user_name, password):
        """Send welcome email to a newly created support agent."""
        try:
            login_url = f"{EmailService._get_base_url()}/customer_support/login?force_login=1"
            body = render_welcome_agent(user_name, user_email, password, login_url)
            EmailService._send(
                "Welcome to Customer Support Portal - Support Agent Account",
                body,
                user_email,
                force_send=True,
            )
            _logger.info(f"✓ Agent welcome email sent to {user_email}")
            return True
        except Exception as e:
            _logger.error(f"✗ Agent welcome email failed for {user_email}: {e}")
            return False

    @staticmethod
    def send_assignment_email(ticket, assigned_user):
        """Notify a support agent that a ticket was assigned to them."""
        try:
            agent_email = assigned_user.email or assigned_user.login
            if not agent_email:
                _logger.warning(f"✗ No email for user {assigned_user.name}")
                return False

            ticket_url = (
                f"{EmailService._get_base_url()}/customer_support/ticket/{ticket.id}"
            )
            body = render_assignment_agent(ticket, assigned_user, ticket_url)
            EmailService._send(
                f"New Ticket Assigned: {ticket.name} - {ticket.subject}",
                body,
                agent_email,
            )
            _logger.info(f"✓ Assignment email queued for {agent_email} ({ticket.name})")
            return True
        except Exception as e:
            _logger.error(f"✗ Assignment email failed for {ticket.name}: {e}")
            return False

    @staticmethod
    def send_assignment_notification_to_customer(ticket, assigned_user):
        """Notify the customer that their ticket has been assigned."""
        try:
            customer_email = ticket.customer_id.email
            if not customer_email:
                _logger.warning(f"✗ No email for customer {ticket.customer_id.name}")
                return False

            ticket_url = (
                f"{EmailService._get_base_url()}/customer_support/ticket/{ticket.id}?force_login=1"
            )
            body = render_assignment_customer(ticket, assigned_user, ticket_url)
            EmailService._send(
                f"Your Ticket Has Been Assigned: {ticket.name}",
                body,
                customer_email,
            )
            _logger.info(f"✓ Customer assignment notification queued for {customer_email}")
            return True
        except Exception as e:
            _logger.error(
                f"✗ Customer assignment notification failed for {ticket.name}: {e}"
            )
            return False

    @staticmethod
    def send_status_change_email(ticket, old_status, new_status):
        """Notify the customer of a ticket status change."""
        try:
            if new_status in ["new", "pending"]:
                return True
            if new_status not in ["assigned", "in_progress", "resolved", "closed"]:
                return True

            customer_email = ticket.customer_id.email
            if not customer_email:
                _logger.warning(f"✗ No email for customer {ticket.customer_id.name}")
                return False

            ticket_url = (
                f"{EmailService._get_base_url()}/customer_support/ticket/{ticket.id}?force_login=1"
            )
            body = render_status_change(ticket, old_status, new_status, ticket_url)
            EmailService._send(
                f"Ticket Status Updated: {ticket.name} - {new_status.replace('_', ' ').title()}",
                body,
                customer_email,
            )
            _logger.info(
                f"✓ Status email queued for {customer_email} ({old_status} → {new_status})"
            )
            return True
        except Exception as e:
            _logger.error(f"✗ Status email failed for {ticket.name}: {e}")
            return False

    @staticmethod
    def send_board_invite(member_name, member_email, ticket, board_url):
        """Send board access link to a team member."""
        try:
            if not member_email:
                _logger.warning(f"✗ No email for member {member_name}")
                return False

            project_name = ticket.project_id.name if ticket.project_id else "Your Project"
            subject = f"Board Access: {ticket.name} — {project_name}"

            body = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8"/>
  <style>
    body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #f0f4f8; margin: 0; padding: 0; }}
    .wrap {{ max-width: 560px; margin: 40px auto; background: #fff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 20px rgba(0,0,0,.1); }}
    .header {{ background: #1e5a8e; padding: 32px 36px; }}
    .header h1 {{ color: #fff; margin: 0; font-size: 20px; font-weight: 700; }}
    .header p {{ color: rgba(255,255,255,.75); margin: 6px 0 0; font-size: 13px; }}
    .body {{ padding: 32px 36px; }}
    .body p {{ color: #374151; font-size: 14px; line-height: 1.65; margin: 0 0 16px; }}
    .ticket-box {{ background: #f0f4f8; border-radius: 8px; border-left: 4px solid #1e5a8e; padding: 14px 18px; margin: 20px 0; }}
    .ticket-box .label {{ font-size: 11px; font-weight: 700; color: #6b7280; text-transform: uppercase; letter-spacing: .05em; }}
    .ticket-box .value {{ font-size: 14px; font-weight: 600; color: #111827; margin-top: 4px; }}
    .btn {{ display: inline-block; background: #1e5a8e; color: #fff; text-decoration: none; padding: 13px 28px; border-radius: 8px; font-weight: 700; font-size: 14px; margin: 8px 0; }}
    .note {{ font-size: 12px; color: #9ca3af; margin-top: 20px; border-top: 1px solid #e5e7eb; padding-top: 16px; }}
    .footer {{ background: #f9fafb; padding: 18px 36px; font-size: 12px; color: #9ca3af; border-top: 1px solid #e5e7eb; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="header">
      <h1>You've been added to a project board</h1>
      <p>Customer Support Portal</p>
    </div>
    <div class="body">
      <p>Hi <strong>{member_name}</strong>,</p>
      <p>You have been added as a team member on the following ticket. Use the link below to access the project board — no login required.</p>
      <div class="ticket-box">
        <div class="label">Ticket</div>
        <div class="value">{ticket.name} — {ticket.subject}</div>
        <div class="label" style="margin-top:10px">Project</div>
        <div class="value">{project_name}</div>
      </div>
      <p>Click the button below to open your board:</p>
      <a href="{board_url}" class="btn">Open Project Board</a>
      <p class="note">
        This link gives direct access to the board without requiring a login.
        Please keep it private. If you believe this was sent in error, you can ignore this email.
      </p>
    </div>
    <div class="footer">Customer Support Portal — automated notification</div>
  </div>
</body>
</html>"""

            EmailService._send(subject, body, member_email, force_send=True)
            _logger.info(f"✓ Board invite sent to {member_email} ({ticket.name})")
            return True
        except Exception as e:
            _logger.error(f"✗ Board invite failed for {member_email}: {e}")
            return False

    @staticmethod
    def send_task_assignment(ticket, member, task):
        """Notify a project member that a board task was assigned to them.

        `member` is a `customer_support.project.member` record (may or may not
        be linked to a `res.users` record). `task` is a
        `customer_support.ticket.task` record.
        """
        try:
            recipient_email = member.user_id.email if member.user_id else (member.member_email or None)
            recipient_name = member.user_id.name if member.user_id else (member.member_name or "")
            if not recipient_email:
                _logger.warning(f"✗ No email for member {recipient_name}")
                return False

            base = EmailService._get_base_url()
            if member.user_id:
                # Internal Odoo user — can log in and use the focal board directly
                task_url = f"{base}/customer_support/ticket/{ticket.id}/board"
            else:
                # External member — use token link so no login is required
                task_url = (
                    f"{base}/board/{ticket.board_token}"
                    if ticket.board_token
                    else f"{base}/customer_support/ticket/{ticket.id}/board"
                )

            due = task.due_date.strftime("%b %d, %Y") if task.due_date else "No due date"
            priority = task.task_priority or "none"
            safe_description = (
                task.description or ""
            ).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")

            subject = f"Task Assigned: {task.name} — {ticket.name}"

            body = f"""
<!DOCTYPE html>
<html><head><meta charset="UTF-8"/>
<style>body{{font-family:'Segoe UI',Arial,sans-serif;background:#f0f4f8;margin:0;padding:0}}.wrap{{max-width:560px;margin:32px auto;background:#fff;border-radius:10px;overflow:hidden;border:1px solid #e6eef8}}</style>
</head><body>
<div class="wrap">
    <div style="background:#1e5a8e;padding:20px;color:#fff"><h2 style="margin:0">New Task Assigned</h2></div>
    <div style="padding:20px;color:#111">
        <p>Hi <strong>{recipient_name}</strong>,</p>
        <p>You have been assigned a task on the ticket <strong>{ticket.name}</strong>:</p>
        <div style="background:#f8fafc;border-left:4px solid #1e5a8e;padding:12px;margin:12px 0;border-radius:6px;">
            <div style="font-weight:700">{task.name}</div>
            <div style="margin-top:8px;color:#475569">{safe_description}</div>
            <div style="margin-top:10px;font-size:13px;color:#64748b">Due: {due} · Priority: {priority}</div>
        </div>
        <p><a href="{task_url}" style="display:inline-block;background:#1e5a8e;color:#fff;padding:10px 18px;border-radius:8px;text-decoration:none">Open Board</a></p>
        <p style="color:#94a3b8;font-size:13px;margin-top:12px">This is an automated notification from Customer Support.</p>
    </div>
</div>
</body></html>
"""

            EmailService._send(subject, body, recipient_email, force_send=True)
            _logger.info(f"✓ Task assignment email queued for {recipient_email} (task={task.name})")
            return True
        except Exception as e:
            _logger.error(f"✗ Task assignment email failed for task {task.name}: {e}")
            return False

    @staticmethod
    def send_customer_reply(ticket, message, sender_name):
        """Send a reply message from the focal/team to the customer."""
        try:
            customer_email = ticket.customer_id.email if ticket.customer_id else None
            if not customer_email:
                return False

            ticket_url = f"{EmailService._get_base_url()}/customer_support/ticket/{ticket.id}?force_login=1"
            subject = f"Update on your ticket: {ticket.name}"
            safe_message = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

            body = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"/>
<style>
  body{{font-family:'Segoe UI',Arial,sans-serif;background:#f0f4f8;margin:0;padding:0;}}
  .wrap{{max-width:560px;margin:40px auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,.1);}}
  .header{{background:#1e5a8e;padding:28px 36px;}}
  .header h1{{color:#fff;margin:0;font-size:18px;font-weight:700;}}
  .header p{{color:rgba(255,255,255,.75);margin:4px 0 0;font-size:13px;}}
  .body{{padding:28px 36px;}}
  .body p{{color:#374151;font-size:14px;line-height:1.65;margin:0 0 14px;}}
  .msg-box{{background:#f8fafc;border-left:4px solid #1e5a8e;border-radius:6px;padding:16px 20px;margin:18px 0;color:#1e293b;font-size:14px;line-height:1.7;white-space:pre-wrap;}}
  .btn{{display:inline-block;background:#1e5a8e;color:#fff;text-decoration:none;padding:12px 26px;border-radius:8px;font-weight:700;font-size:14px;margin-top:8px;}}
  .footer{{background:#f9fafb;padding:16px 36px;font-size:12px;color:#9ca3af;border-top:1px solid #e5e7eb;}}
</style></head>
<body><div class="wrap">
  <div class="header"><h1>Message from the support team</h1><p>{ticket.name} — {ticket.subject}</p></div>
  <div class="body">
    <p>Hi <strong>{ticket.customer_id.name if ticket.customer_id else 'there'}</strong>,</p>
    <p><strong>{sender_name}</strong> has sent you a message regarding your ticket:</p>
    <div class="msg-box">{safe_message}</div>
    <p>You can view your full ticket and reply at:</p>
    <a href="{ticket_url}" class="btn">View My Ticket</a>
  </div>
  <div class="footer">Customer Support Portal — automated notification</div>
</div></body></html>"""

            EmailService._send(subject, body, customer_email)
            _logger.info(f"✓ Customer reply queued for {customer_email} ({ticket.name})")
            return True
        except Exception as e:
            _logger.error(f"✗ Customer reply failed for {ticket.name}: {e}")
            return False

    @staticmethod
    def send_mention_notification(user_email, user_name, commenter_name, ticket, message):
        """Notify a user they were @mentioned in an internal note."""
        try:
            if not user_email:
                return False

            subject = f"You were mentioned in {ticket.name}"
            safe_message = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

            body = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"/>
<style>
  body{{font-family:'Segoe UI',Arial,sans-serif;background:#f0f4f8;margin:0;padding:0;}}
  .wrap{{max-width:560px;margin:40px auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,.1);}}
  .header{{background:#1e5a8e;padding:28px 36px;}}
  .header h1{{color:#fff;margin:0;font-size:18px;font-weight:700;}}
  .header p{{color:rgba(255,255,255,.75);margin:4px 0 0;font-size:13px;}}
  .body{{padding:28px 36px;}}
  .body p{{color:#374151;font-size:14px;line-height:1.65;margin:0 0 14px;}}
  .note-box{{background:#f8fafc;border-left:4px solid #6366f1;border-radius:6px;padding:16px 20px;margin:18px 0;color:#1e293b;font-size:14px;line-height:1.7;white-space:pre-wrap;}}
  .mention{{background:rgba(99,102,241,.15);color:#6366f1;border-radius:3px;padding:1px 4px;font-weight:600;}}
  .footer{{background:#f9fafb;padding:16px 36px;font-size:12px;color:#9ca3af;border-top:1px solid #e5e7eb;}}
</style></head>
<body><div class="wrap">
  <div class="header"><h1>You were mentioned</h1><p>{ticket.name} — {ticket.subject}</p></div>
  <div class="body">
    <p>Hi <strong>{user_name}</strong>,</p>
    <p><strong>{commenter_name}</strong> mentioned you in an internal note:</p>
    <div class="note-box">{safe_message}</div>
  </div>
  <div class="footer">Customer Support Portal — automated notification</div>
</div></body></html>"""

            EmailService._send(subject, body, user_email, force_send=True)
            _logger.info(f"✓ Mention notification sent to {user_email}")
            return True
        except Exception as e:
            _logger.error(f"✗ Mention notification failed for {user_email}: {e}")
            return False
