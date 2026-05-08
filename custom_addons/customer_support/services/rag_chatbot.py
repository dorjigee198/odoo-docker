import hashlib
import requests
import json
import logging
import time

_logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
OLLAMA_BASE_URL = "https://ai.dcpl.bt/ollama"
MODEL = "qwen2.5:3b"
EMBED_MODEL = "nomic-embed-text"

SIMILARITY_THRESHOLD = 0.20
MAX_HISTORY = 4
MAX_TOKENS = 250

# ── Shared instant responses ──────────────────────────────────────────────────
GREETINGS = {
    "hi",
    "hello",
    "hey",
    "hii",
    "helo",
    "hi there",
    "hello there",
    "hey there",
    "good morning",
    "good afternoon",
    "good evening",
    "howdy",
    "greetings",
    "sup",
    "what's up",
    "whats up",
}

SMALL_TALK = {
    "how are you": "I'm doing great, thanks for asking! How can I help you today?",
    "how are you doing": "I'm doing great! How can I help you today?",
    "who are you": "I'm the Dragon Coders AI assistant. Ask me anything about our company, services, or products!",
    "what are you": "I'm the Dragon Coders AI assistant. Ask me anything about our company, services, or products!",
    "what can you do": "I can answer questions about Dragon Coders services, pricing, projects, location, and more!",
    "what can you help with": "I can help with questions about Dragon Coders services, pricing, projects, and support.",
    "thank you": "You're welcome! Is there anything else I can help you with?",
    "thanks": "You're welcome! Is there anything else I can help you with?",
    "thank you so much": "Happy to help! Let me know if you need anything else.",
    "ok thanks": "You're welcome! Feel free to ask anytime.",
    "ok thank you": "You're welcome! Feel free to ask anytime.",
    "bye": "Goodbye! Have a great day! 👋",
    "goodbye": "Goodbye! Have a great day! 👋",
    "see you": "See you! Have a great day! 👋",
    "ok": "Got it! Is there anything else I can help you with?",
    "okay": "Got it! Is there anything else I can help you with?",
}

# ── System prompts ────────────────────────────────────────────────────────────

DRAGON_CHAT_PROMPT = """
You are the official public-facing AI assistant for Dragon Coders Private Limited.

YOUR PURPOSE:
Help visitors learn about Dragon Coders — who we are, what we do, our services,
products, pricing, location, office hours, and team.

STRICT RULES:
1. Answer ONLY using the provided CONTEXT.
2. NEVER guess or invent any information.
3. ONLY discuss Dragon Coders company info, services, products, pricing, location, team.
4. If the question is about a bug, error, crash, or technical issue with a product
   → classify as "technical".
5. If the question is completely unrelated to Dragon Coders
   → classify as "offtopic".
6. If the CONTEXT does not contain the answer
   → classify as "no_context".
7. Be warm, friendly, and promotional in tone — like a helpful salesperson.
8. Keep answers concise and clear.

IMPORTANT intent rules:
- "technical" ONLY for: software bugs, errors, crashes, login issues, system failures.
- "general" for: services, pricing, location, office hours, team, company info.
- "offtopic" for: anything unrelated to Dragon Coders.
- "no_context" when the answer is not in the CONTEXT.

RESPONSE FORMAT — return ONLY valid JSON, no extra text:
- General answer:  {"intent": "general",    "reply": "..."}
- Technical issue: {"intent": "technical",  "summary": "One-sentence issue summary"}
- Off-topic:       {"intent": "offtopic",   "reply": "I can only help with Dragon Coders questions."}
- No info:         {"intent": "no_context", "reply": "no_context"}
"""

SUPPORT_BOT_PROMPT = """
You are the official AI support assistant for Dragon Coders Private Limited.

YOUR PURPOSE:
Help logged-in customers with any questions about Dragon Coders — company info,
services, products, pricing, location, office hours, technical issues, and bugs.

STRICT RULES:
1. Answer ONLY using the provided CONTEXT.
2. NEVER guess or invent any information.
3. ONLY discuss Dragon Coders company, services, products, and support topics.
4. If the question is about a bug, error, crash, or technical issue with a product
   → classify as "technical".
5. If the question is completely unrelated to Dragon Coders
   → classify as "offtopic".
6. If the CONTEXT does not contain the answer
   → classify as "no_context".
7. Be professional, friendly, and solution-focused in tone.
8. Keep answers concise and clear.

IMPORTANT intent rules:
- "technical" ONLY for: software bugs, errors, crashes, login issues, data loss,
  system failures, performance problems in a DC product.
- "general" for: services, pricing, location, office hours, team, company info,
  product features, how-to questions.
- "offtopic" for: anything completely unrelated to Dragon Coders.
- "no_context" when the answer is not in the CONTEXT.

RESPONSE FORMAT — return ONLY valid JSON, no extra text:
- General answer:  {"intent": "general",    "reply": "..."}
- Technical issue: {"intent": "technical",  "summary": "One-sentence issue summary"}
- Off-topic:       {"intent": "offtopic",   "reply": "I can only help with Dragon Coders questions."}
- No info:         {"intent": "no_context", "reply": "no_context"}
"""


# ── SUPPORT BOT (logged in customer portal) ───────────────────────────────────
class ChatBotBackend:
    def __init__(self, base_url=OLLAMA_BASE_URL, model=MODEL):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.histories = {}
        self._query_cache = {}

    def send_message(self, user_id, user_message, odoo_env=None):
        start_total = time.time()
        normalized = user_message.strip().lower()

        # 1. Cache check
        cache_key = self._hash(normalized)
        if user_id in self._query_cache and cache_key in self._query_cache[user_id]:
            _logger.info(f"Cache hit for user {user_id}")
            return self._query_cache[user_id][cache_key]

        # 2. Greeting → instant reply
        if normalized in GREETINGS:
            return self._cache_and_return(
                user_id,
                cache_key,
                "general",
                "Hello! 👋 Welcome to Dragon Coders support. "
                "How can I help you today?",
            )

        # 3. Small talk → instant reply
        if normalized in SMALL_TALK:
            return self._cache_and_return(
                user_id, cache_key, "general", SMALL_TALK[normalized]
            )

        # 4. Retrieve context via pgvector
        t1 = time.time()
        context, has_context = self._retrieve_context(user_message, odoo_env)
        t_retrieve = time.time() - t1

        # 5. No relevant context → I don't know
        if not has_context:
            return self._cache_and_return(
                user_id,
                cache_key,
                "no_context",
                "I'm sorry, I don't have that information. "
                "Please create a New Ticket and our support team will be happy to help!",
            )

        # 6. Build messages and call LLM
        t2 = time.time()
        messages = self._build_messages(
            user_id, user_message, context, SUPPORT_BOT_PROMPT
        )
        t_build = time.time() - t2

        t3 = time.time()
        try:
            raw = self._call_ollama(messages)
            parsed = self._parse_response(raw)
        except requests.exceptions.ConnectionError:
            return "error", "⚠️ AI service offline. Please create a New Ticket for help."
        except requests.exceptions.Timeout:
            return "error", "⚠️ AI timed out. Please try again."
        except Exception as e:
            _logger.error("Support bot error: %s", e)
            return "error", "Something went wrong. Please try again."
        t_llm = time.time() - t3

        # 7. Route by intent
        intent, reply = self._route_support(user_id, user_message, parsed)

        total_time = time.time() - start_total
        _logger.info(
            f"Support bot timings - user {user_id}: "
            f"retrieve: {t_retrieve:.2f}s | build: {t_build:.2f}s | "
            f"llm: {t_llm:.2f}s | total: {total_time:.2f}s"
        )

        return self._cache_and_return(user_id, cache_key, intent, reply)

    def _route_support(self, user_id, user_message, parsed):
        intent = parsed.get("intent", "no_context")

        if intent == "general":
            reply = parsed.get("reply", "")
            self._append_history(user_id, "assistant", reply)
            return intent, reply

        elif intent == "technical":
            summary = parsed.get("summary", user_message)
            self.clear_history(user_id)
            reply = (
                f"🔧 It looks like you're experiencing a technical issue: "
                f"{summary}\n\n"
                f"Please create a New Ticket and our support team "
                f"will get back to you shortly."
            )
            return intent, reply

        elif intent == "offtopic":
            return intent, "I can only help with Dragon Coders related questions."

        else:  # no_context
            return "no_context", (
                "I'm sorry, I don't have that information. "
                "Please create a New Ticket and our support team will be happy to help!"
            )

    def clear_history(self, user_id):
        self.histories.pop(user_id, None)
        self._query_cache.pop(user_id, None)

    def is_online(self):
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def _retrieve_context(self, query, odoo_env):
        if not odoo_env:
            return "", False
        try:
            Chunk = odoo_env["dc.knowledge.chunk"].sudo()
            chunks = Chunk.get_relevant_chunks(
                query, limit=3, threshold=SIMILARITY_THRESHOLD
            )
            if not chunks:
                return "", False
            parts = []
            for chunk in chunks:
                doc_name = chunk.document_id.name
                category = chunk.document_id.category or "general"
                parts.append(f"[Source: {doc_name} | {category}]\n{chunk.content}")
            return "\n\n---\n\n".join(parts), True
        except Exception as e:
            _logger.warning("Context retrieval failed: %s", e)
            return "", False

    def _build_messages(self, user_id, user_message, context, system_prompt):
        if user_id not in self.histories:
            self.histories[user_id] = []
        user_content = (
            f"CONTEXT (answer ONLY from this):\n"
            f"{'='*50}\n{context}\n{'='*50}\n\n"
            f"QUESTION: {user_message}"
        )
        history_slice = self.histories[user_id][-MAX_HISTORY:]
        messages = (
            [{"role": "system", "content": system_prompt}]
            + history_slice
            + [{"role": "user", "content": user_content}]
        )
        self._append_history(user_id, "user", user_message)
        return messages

    def _append_history(self, user_id, role, content):
        if user_id not in self.histories:
            self.histories[user_id] = []
        self.histories[user_id].append({"role": role, "content": content})

    def _call_ollama(self, messages):
        response = requests.post(
            f"{self.base_url}/api/chat",
            json={
                "model": self.model,
                "messages": messages,
                "stream": False,
                "format": "json",
                "keep_alive": -1,
                "options": {
                    "temperature": 0.1,
                    "num_predict": MAX_TOKENS,
                },
            },
            timeout=60,
        )
        response.raise_for_status()
        return response.json()["message"]["content"]

    def _parse_response(self, raw):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start != -1 and end > start:
                try:
                    return json.loads(raw[start:end])
                except Exception:
                    _logger.warning("LLM response fallback JSON fragment parse failed; returning raw reply.")
            return {"intent": "general", "reply": raw.strip()}

    def _hash(self, text):
        return hashlib.md5(text.encode(), usedforsecurity=False).hexdigest()

    def _cache_and_return(self, user_id, cache_key, intent, reply):
        if user_id not in self._query_cache:
            self._query_cache[user_id] = {}
        self._query_cache[user_id][cache_key] = (intent, reply)
        return intent, reply


# ── DRAGON CHAT (public landing page) ────────────────────────────────────────
class GeneralChatBackend:
    def __init__(self, base_url=OLLAMA_BASE_URL, model=MODEL):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._query_cache = {}

    def send_message(self, user_id, user_message, odoo_env=None):
        normalized = user_message.strip().lower()

        # 1. Cache check
        cache_key = hashlib.md5(normalized.encode(), usedforsecurity=False).hexdigest()
        if user_id in self._query_cache and cache_key in self._query_cache[user_id]:
            _logger.info(f"Dragon Chat cache hit for user {user_id}")
            return self._query_cache[user_id][cache_key]

        # 2. Greeting → instant reply
        if normalized in GREETINGS:
            return self._cache_and_return(
                user_id,
                cache_key,
                "general",
                "Hello! 👋 Welcome to Dragon Coders. "
                "How can I help you learn about us today?",
            )

        # 3. Small talk → instant reply
        if normalized in SMALL_TALK:
            return self._cache_and_return(
                user_id, cache_key, "general", SMALL_TALK[normalized]
            )

        # 4. Retrieve context via pgvector
        context, has_context = self._retrieve_context(user_message, odoo_env)

        # 5. No relevant context → I don't know
        if not has_context:
            return self._cache_and_return(
                user_id,
                cache_key,
                "no_context",
                "I'm sorry, I don't have that information. "
                "Please contact us at support@dragoncoders.com for more details.",
            )

        # 6. Call LLM
        messages = [
            {"role": "system", "content": DRAGON_CHAT_PROMPT},
            {
                "role": "user",
                "content": (
                    f"CONTEXT (answer ONLY from this):\n"
                    f"{'='*50}\n{context}\n{'='*50}\n\n"
                    f"QUESTION: {user_message}"
                ),
            },
        ]

        try:
            response = requests.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "format": "json",
                    "keep_alive": -1,
                    "options": {
                        "temperature": 0.2,
                        "num_predict": MAX_TOKENS,
                    },
                },
                timeout=60,
            )
            response.raise_for_status()
            raw = response.json()["message"]["content"]
            parsed = self._parse_response(raw)

        except requests.exceptions.ConnectionError:
            return "error", "⚠️ Service offline. Please contact support@dragoncoders.com"
        except requests.exceptions.Timeout:
            return "error", "⚠️ Request timed out. Please try again."
        except Exception as e:
            _logger.error("Dragon Chat error: %s", e)
            return "error", "Something went wrong. Please try again."

        # 7. Route by intent
        intent, reply = self._route_dragon_chat(parsed)
        return self._cache_and_return(user_id, cache_key, intent, reply)

    def _route_dragon_chat(self, parsed):
        intent = parsed.get("intent", "no_context")

        if intent == "general":
            return intent, parsed.get("reply", "")

        elif intent == "technical":
            return intent, (
                "It looks like you have a technical issue. "
                "Please login to our support portal where our "
                "support team can assist you further."
            )

        elif intent == "offtopic":
            return intent, "I can only help with Dragon Coders related questions."

        else:  # no_context
            return "no_context", (
                "I'm sorry, I don't have that information. "
                "Please contact us at support@dragoncoders.com for more details."
            )

    def _retrieve_context(self, query, odoo_env):
        if not odoo_env:
            return "", False
        try:
            Chunk = odoo_env["dc.knowledge.chunk"].sudo()
            chunks = Chunk.get_relevant_chunks(
                query, limit=3, threshold=SIMILARITY_THRESHOLD
            )
            if not chunks:
                return "", False
            parts = []
            for chunk in chunks:
                doc_name = chunk.document_id.name
                category = chunk.document_id.category or "general"
                parts.append(f"[Source: {doc_name} | {category}]\n{chunk.content}")
            return "\n\n---\n\n".join(parts), True
        except Exception as e:
            _logger.warning("Dragon Chat context retrieval failed: %s", e)
            return "", False

    def _parse_response(self, raw):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start != -1 and end > start:
                try:
                    return json.loads(raw[start:end])
                except Exception:
                    _logger.warning("LLM response fallback JSON fragment parse failed; returning raw reply.")
            return {"intent": "general", "reply": raw.strip()}

    def _cache_and_return(self, user_id, cache_key, intent, reply):
        if user_id not in self._query_cache:
            self._query_cache[user_id] = {}
        self._query_cache[user_id][cache_key] = (intent, reply)
        return intent, reply
