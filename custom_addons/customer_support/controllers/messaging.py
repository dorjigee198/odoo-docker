# -*- coding: utf-8 -*-
"""
Messaging Controller
====================
Handles all ticket message operations:
- Post new messages to ticket communication thread
- Edit existing messages (author only)
- Delete messages (author or admin)
"""

import json
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class TicketMessaging(http.Controller):

    @http.route(
        "/customer_support/ticket/<int:ticket_id>/post_message",
        type="http",
        auth="user",
        methods=["POST"],
        website=True,
        csrf=True,
    )
    def post_ticket_message(self, ticket_id, **post):
        """
        Post Ticket Message - Handles posting messages to ticket communication
        Working: Creates new message in ticket's communication thread
        Access: Authenticated users (customers, support agents, admins)

        Three fallback strategies are attempted in order:
          1. message_post() with subtype
          2. message_post() without subtype
          3. Direct mail.message record creation
        """
        try:
            ticket = request.env["customer.support"].sudo().browse(ticket_id)

            if not ticket.exists():
                return request.redirect(
                    f"/customer_support/ticket/{ticket_id}?error=Ticket not found"
                )

            message = post.get("message", "").strip()
            if not message:
                return request.redirect(
                    f"/customer_support/ticket/{ticket_id}?error=Message cannot be empty"
                )

            _logger.info(f"Attempting to post message to ticket {ticket_id}: {message}")

            # Strategy 1: standard message_post with subtype
            try:
                msg = ticket.message_post(
                    body=message,
                    message_type="comment",
                    subtype_xmlid="mail.mt_comment",
                    author_id=request.env.user.partner_id.id,
                )
                _logger.info(
                    f"✓ Message posted successfully - ID: {msg.id if msg else 'N/A'}"
                )
                success_msg = "Message posted successfully"

            except Exception as e1:
                _logger.error(f"✗ message_post with subtype failed: {str(e1)}")

                # Strategy 2: message_post without subtype
                try:
                    msg = ticket.message_post(
                        body=message,
                        message_type="comment",
                        author_id=request.env.user.partner_id.id,
                    )
                    _logger.info(
                        f"✓ Message posted without subtype - ID: {msg.id if msg else 'N/A'}"
                    )
                    success_msg = "Message posted successfully"

                except Exception as e2:
                    _logger.error(f"✗ message_post without subtype failed: {str(e2)}")

                    # Strategy 3: create mail.message record directly
                    try:
                        msg = (
                            request.env["mail.message"]
                            .sudo()
                            .create(
                                {
                                    "model": "customer.support",
                                    "res_id": ticket_id,
                                    "body": message,
                                    "message_type": "comment",
                                    "author_id": request.env.user.partner_id.id,
                                }
                            )
                        )
                        _logger.info(f"✓ Message created directly - ID: {msg.id}")
                        success_msg = "Message posted successfully"

                    except Exception as e3:
                        _logger.error(f"✗ All strategies failed: {str(e3)}")
                        success_msg = f"Error posting message: {str(e3)}"

            return request.redirect(
                f"/customer_support/ticket/{ticket_id}?success={success_msg}"
            )

        except Exception as e:
            _logger.error(f"CRITICAL ERROR in post_message: {str(e)}")
            return request.redirect(
                f"/customer_support/ticket/{ticket_id}?error={str(e)}"
            )

    @http.route(
        "/customer_support/ticket/message/<int:message_id>/edit",
        type="http",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def edit_message(self, message_id, new_body=None, **kwargs):
        """
        Edit Message - AJAX endpoint for editing ticket messages
        Working: Updates message content in ticket's communication thread
        Access: Message author only (users can only edit their own messages)
        Returns: JSON response with success/error status and updated body
        """
        try:
            message = request.env["mail.message"].sudo().browse(message_id)

            if not message.exists():
                return request.make_response(
                    json.dumps({"success": False, "error": "Message not found"}),
                    headers=[("Content-Type", "application/json")],
                )

            # Only the author may edit their own message
            user = request.env.user
            is_author = message.author_id.id == user.partner_id.id

            if not is_author:
                return request.make_response(
                    json.dumps(
                        {
                            "success": False,
                            "error": "You can only edit your own messages",
                        }
                    ),
                    headers=[("Content-Type", "application/json")],
                )

            if not new_body or not new_body.strip():
                return request.make_response(
                    json.dumps({"success": False, "error": "Message cannot be empty"}),
                    headers=[("Content-Type", "application/json")],
                )

            message.write({"body": new_body.strip()})

            return request.make_response(
                json.dumps(
                    {
                        "success": True,
                        "message": "Message updated successfully",
                        "new_body": new_body.strip(),
                    }
                ),
                headers=[("Content-Type", "application/json")],
            )

        except Exception as e:
            _logger.error(f"Edit message error: {str(e)}")
            return request.make_response(
                json.dumps({"success": False, "error": str(e)}),
                headers=[("Content-Type", "application/json")],
            )

    @http.route(
        "/customer_support/ticket/message/<int:message_id>/delete",
        type="http",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def delete_message(self, message_id, **kwargs):
        """
        Delete Message - AJAX endpoint for deleting ticket messages
        Working: Deletes a message from ticket's communication thread
        Access: Message author or system administrators
        Returns: JSON response with success/error status
        """
        try:
            message = request.env["mail.message"].sudo().browse(message_id)

            if not message.exists():
                return request.make_response(
                    json.dumps({"success": False, "error": "Message not found"}),
                    headers=[("Content-Type", "application/json")],
                )

            # Only the message author or an admin may delete
            user = request.env.user
            is_admin = user.has_group("base.group_system")
            is_author = message.author_id.id == user.partner_id.id

            if not (is_admin or is_author):
                return request.make_response(
                    json.dumps(
                        {
                            "success": False,
                            "error": "You do not have permission to delete this message",
                        }
                    ),
                    headers=[("Content-Type", "application/json")],
                )

            ticket_id = message.res_id
            message.unlink()

            return request.make_response(
                json.dumps(
                    {
                        "success": True,
                        "message": "Message deleted successfully",
                        "ticket_id": ticket_id,
                    }
                ),
                headers=[("Content-Type", "application/json")],
            )

        except Exception as e:
            _logger.error(f"Delete message error: {str(e)}")
            return request.make_response(
                json.dumps({"success": False, "error": str(e)}),
                headers=[("Content-Type", "application/json")],
            )
