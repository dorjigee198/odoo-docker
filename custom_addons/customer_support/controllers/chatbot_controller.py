import base64
import json
import logging

from odoo import http
from odoo.http import request
from ..services.rag_chatbot import ChatBotBackend, GeneralChatBackend

_logger = logging.getLogger(__name__)

# Global bot instances (one per Odoo worker)
support_bot = ChatBotBackend()
general_bot = GeneralChatBackend()


class CustomerSupportChatbot(http.Controller):

    # ── SUPPORT CHATBOT (Dragon Coders company-specific with RAG) ─────────────

    @http.route("/customer_support/chatbot", type="http", auth="user", website=True)
    def chatbot_page(self, **kw):
        """Render the Dragon Coders support chatbot page"""
        return request.render("customer_support.chatbot_page")

    @http.route("/customer_support/chatbot/message", type="jsonrpc", auth="user")
    def chatbot_message(self, message, **kw):
        if not message or not message.strip():
            return {"intent": "error", "reply": "Please enter a message."}

        user = request.env.user
        user_id = user.id

        try:
            intent, content = support_bot.send_message(
                user_id=user_id,
                user_message=message.strip(),
                odoo_env=request.env,
            )

            if intent == "technical":
                ticket = self._create_ticket(
                    user=user,
                    summary=content,
                    original_message=message,
                )
                return {
                    "intent": "technical",
                    "reply": (
                        f"🔧 Looks like a technical issue! I've automatically "
                        f"created a support ticket for you.<br><br>"
                        f"<strong>Ticket #{ticket.id} — {ticket.name}</strong><br><br>"
                        f"Our team will get back to you shortly. Track it in "
                        f"<a href='/customer_support/tickets'>My Tickets</a>."
                    ),
                    "ticket_id": ticket.id,
                }

            return {"intent": intent, "reply": content}

        except Exception as e:
            _logger.error("Support chatbot error: %s", e)
            return {
                "intent": "error",
                "reply": "Sorry, something went wrong. Please try again.",
            }

    @http.route("/customer_support/chatbot/clear", type="jsonrpc", auth="user")
    def chatbot_clear(self, **kw):
        support_bot.clear_history(request.env.user.id)
        return {"success": True}

    @http.route("/customer_support/chatbot/status", type="jsonrpc", auth="user")
    def chatbot_status(self, **kw):
        online = support_bot.is_online()
        doc_count = (
            request.env["dc.knowledge.document"]
            .sudo()
            .search_count([("state", "=", "ready")])
        )
        return {
            "online": online,
            "doc_count": doc_count,
        }

    # ── GENERAL / FAQ CHATBOT (uses your existing landing_chat interface) ─────

    @http.route("/dragon-chat", type="http", auth="public")
    def faq_chat_page(self, **kw):
        """Public general / FAQ chat page – loads your landing_chat template"""
        return request.render("customer_support.landing_chat")

    @http.route("/dragon-chat/message", type="jsonrpc", auth="public", website=True, csrf=False)
    def faq_chat_message(self, message, **kw):
        if not message or not message.strip():
            return {"reply": "Please type a question."}

        user_id = request.env.user.id if not request.env.user._is_public() else "guest"

        try:
            intent, reply = general_bot.send_message(
                user_id=user_id,
                user_message=message.strip(),
                odoo_env=request.env,
            )
            return {"reply": reply}
        except Exception as e:
            _logger.error("General/FAQ chatbot error: %s", e)
            return {"reply": "Sorry, something went wrong. Try again later."}

    # ── KNOWLEDGE BASE ROUTES (unchanged) ─────────────────────────────────────

    @http.route("/customer_support/knowledge", type="http", auth="user", website=True)
    def knowledge_page(self, **kw):
        if not request.env.user.has_group("base.group_user"):
            return request.redirect("/customer_support/dashboard")

        docs = (
            request.env["dc.knowledge.document"]
            .sudo()
            .search([], order="create_date desc")
        )

        return request.render(
            "customer_support.knowledge_page",
            {
                "documents": docs,
                "categories": [
                    ("company", "Company Info"),
                    ("services", "Services & Products"),
                    ("projects", "Projects"),
                    ("pricing", "Pricing"),
                    ("technical", "Technical Docs"),
                    ("faq", "FAQ"),
                    ("other", "Other"),
                ],
            },
        )

    @http.route(
        "/customer_support/knowledge/upload",
        type="http",
        auth="user",
        methods=["POST"],
        website=True,
        csrf=True,
    )
    def knowledge_upload(self, **kw):
        import json as _json

        def _redirect_with_param(path, param):
            sep = "&" if "?" in path else "?"
            return request.redirect(f"{path}{sep}{param}")

        def _json_response(data, status=200):
            return request.make_response(
                _json.dumps(data),
                headers=[("Content-Type", "application/json")],
                status=status,
            )

        # ajax=1 means the caller wants JSON back instead of a redirect
        is_ajax = kw.get("ajax") == "1"

        if not request.env.user.has_group("base.group_user"):
            if is_ajax:
                return _json_response({"error": "Access denied"}, 403)
            return request.redirect("/customer_support/dashboard")

        uploaded_file = kw.get("file")
        name = kw.get("name", "").strip()
        category = kw.get("category", "other")
        description = kw.get("description", "").strip()
        project_id_raw = kw.get("project_id", "")
        redirect_to = kw.get("redirect_to", "/customer_support/knowledge")

        if not uploaded_file or not name:
            if is_ajax:
                return _json_response({"error": "Please fill all required fields"})
            return _redirect_with_param(redirect_to, "error=Please+fill+all+required+fields")

        filename = uploaded_file.filename
        allowed = (".pdf", ".docx", ".txt", ".xlsx")

        if not any(filename.lower().endswith(ext) for ext in allowed):
            if is_ajax:
                return _json_response({"error": "Invalid file type. Allowed: PDF, DOCX, TXT, XLSX"})
            return _redirect_with_param(
                redirect_to,
                "error=Invalid+file+type.+Allowed:+PDF,+DOCX,+TXT,+XLSX",
            )

        try:
            file_data = uploaded_file.read()

            vals = {
                "name": name,
                "description": description,
                "file": base64.b64encode(file_data),
                "filename": filename,
                "category": category,
            }
            if project_id_raw:
                try:
                    vals["project_id"] = int(project_id_raw)
                except (ValueError, TypeError):
                    pass

            doc = request.env["dc.knowledge.document"].sudo().create(vals)

            # Extract text and create chunks immediately so the doc is usable
            # right away. Ollama embedding runs later via cron (slow/optional).
            try:
                text = doc._extract_text()
                if text and text.strip():
                    doc.sudo().write({"extracted_text": text})
                    doc._create_chunks(text)
                doc.sudo().write({"state": "ready"})
            except Exception as proc_err:
                _logger.warning("Immediate doc processing failed: %s", proc_err)
                doc.sudo().write({"state": "ready"})

            if is_ajax:
                return _json_response({
                    "success": True,
                    "doc": {
                        "id": doc.id,
                        "name": doc.name,
                        "filename": doc.filename or "",
                        "file_type": doc.file_type or "other",
                        "category": doc.category or "other",
                        "state": doc.state,
                        "created": doc.create_date.strftime("%b %d, %Y") if doc.create_date else "",
                    }
                })

            return _redirect_with_param(redirect_to, "success=queued")

        except Exception as e:
            if is_ajax:
                return _json_response({"error": str(e)[:200]})
            return _redirect_with_param(redirect_to, f"error={str(e)[:100]}")

    @http.route(
        "/customer_support/knowledge/delete/<int:doc_id>",
        type="http",
        auth="user",
        methods=["POST"],
        website=True,
        csrf=True,
    )
    def knowledge_delete(self, doc_id, **kw):
        if not request.env.user.has_group("base.group_user"):
            return request.redirect("/customer_support/dashboard")

        doc = request.env["dc.knowledge.document"].sudo().browse(doc_id)

        if doc.exists():
            doc.action_delete()

        return request.redirect("/customer_support/knowledge?deleted=1")

    @http.route(
        "/customer_support/knowledge/list", type="http", auth="user", website=True
    )
    def knowledge_list(self, **kw):
        """Return all knowledge docs as JSON — used by admin dashboard modal"""
        if not request.env.user.has_group("base.group_user"):
            return request.make_response(
                '{"documents":[]}', headers=[("Content-Type", "application/json")]
            )

        docs = (
            request.env["dc.knowledge.document"]
            .sudo()
            .search([], order="create_date desc")
        )

        doc_list = []
        for d in docs:
            doc_list.append(
                {
                    "id": d.id,
                    "name": d.name,
                    "description": d.description or "",
                    "filename": d.filename or "",
                    "file_type": d.file_type or "txt",
                    "category": d.category or "other",
                    "state": d.state,
                    "error_msg": d.error_msg or "",
                    "chunk_count": d.chunk_count,
                    "project_id": d.project_id.id if d.project_id else False,
                    "project_name": d.project_id.name if d.project_id else "",
                    "create_date": (
                        d.create_date.strftime("%b %d, %Y") if d.create_date else ""
                    ),
                }
            )

        return request.make_response(
            json.dumps({"documents": doc_list}),
            headers=[
                ("Content-Type", "application/json"),
                ("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0"),
                ("Pragma", "no-cache"),
                ("Expires", "0"),
            ],
        )

    # ── PRIVATE METHODS ───────────────────────────────────────────────────────

    def _create_ticket(self, user, summary, original_message):
        Ticket = request.env["customer.support"].sudo()

        return Ticket.create(
            {
                "subject": f"[AI] {summary[:120]}",
                "description": (
                    f"Auto-created by Dragon Coders AI Chatbot\n\n"
                    f"Customer: {user.name} ({user.email or 'No email'})\n"
                    f"Original Message: {original_message}\n\n"
                    f"AI Summary: {summary}"
                ),
                "customer_id": user.partner_id.id if user.partner_id else False,
                "priority": "medium",
                "state": "new",
            }
        )
