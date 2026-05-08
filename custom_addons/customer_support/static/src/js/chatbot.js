document.addEventListener('DOMContentLoaded', () => {

    // ── 1. SELECT ELEMENTS ───────────────────────────────────
    const chatBox = document.getElementById("chat-box");
    const userInput = document.getElementById("user-input");
    const sendBtn = document.getElementById("send-msg-btn");

    // ── 2. SAFETY GUARD ──────────────────────────────────────
    if (!chatBox || !userInput) {
        console.log("Chatbot elements not found — not on chatbot page");
        return;
    }

    // ── 3. HELPERS ───────────────────────────────────────────

    // Returns current time as "2:14 PM"
    function now() {
        return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }

    // Escape HTML to prevent XSS
    function escapeHTML(str) {
        return str
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    // ── 4. APPEND USER MESSAGE (right side, dark bubble) ─────
    function appendUserMessage(text) {
        const row = document.createElement("div");
        row.className = "message-row user-row";
        row.innerHTML = `
            <div class="message-content-wrap">
                <span class="msg-sender">You</span>
                <div class="message-bubble user-bubble">${escapeHTML(text)}</div>
                <span class="msg-timestamp">${now()}</span>
            </div>
        `;
        chatBox.appendChild(row);
        chatBox.scrollTop = chatBox.scrollHeight;

        // Add to sidebar history on first user message
        if (typeof window.addChatToHistory === 'function') {
            window.addChatToHistory(text);
        }
    }

    // ── 5. APPEND BOT MESSAGE (left side, white bubble + avatar) ──
    function appendBotMessage(text) {
        const logoHTML = window._logoSrc
            ? `<img src="${window._logoSrc}" alt="Dragon Coders"/>`
            : '🐉';

        const row = document.createElement("div");
        row.className = "message-row bot-row";
        row.innerHTML = `
            <div class="msg-avatar">${logoHTML}</div>
            <div class="message-content-wrap">
                <span class="msg-sender">Dragon Chat</span>
                <div class="message-bubble bot-bubble">${escapeHTML(text)}</div>
                <span class="msg-timestamp">${now()}</span>
            </div>
        `;
        chatBox.appendChild(row);
        chatBox.scrollTop = chatBox.scrollHeight;
    }

    // ── 6. TYPING INDICATOR ──────────────────────────────────
    function showTyping() {
        if (document.getElementById("typing-indicator")) return;

        const logoHTML = window._logoSrc
            ? `<img src="${window._logoSrc}" alt="Dragon Coders"/>`
            : '🐉';

        const row = document.createElement("div");
        row.className = "typing-row";
        row.id = "typing-indicator";
        row.innerHTML = `
            <div class="msg-avatar">${logoHTML}</div>
            <div class="typing-bubble">
                <span class="typing-dot"></span>
                <span class="typing-dot"></span>
                <span class="typing-dot"></span>
            </div>
        `;
        chatBox.appendChild(row);
        chatBox.scrollTop = chatBox.scrollHeight;
    }

    function hideTyping() {
        const indicator = document.getElementById("typing-indicator");
        if (indicator) indicator.remove();
    }

    // ── 7. SEND MESSAGE ──────────────────────────────────────
    async function sendMessage(manualMsg = null) {
        const message = manualMsg || userInput.value.trim();
        if (!message) return;

        appendUserMessage(message);
        if (!manualMsg) userInput.value = "";

        showTyping();

        // Use the public endpoint — works for guests and logged-in users alike
        const chatEndpoint = "/dragon-chat/message";

        try {
            const res = await fetch(chatEndpoint, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    jsonrpc: "2.0",
                    method: "call",
                    params: { message: message }
                })
            });

            hideTyping();
            const data = await res.json();

            if (data.result) {
                if (data.result.reply) {
                    appendBotMessage(data.result.reply);
                } else if (data.result.error) {
                    appendBotMessage("Sorry, something went wrong: " + data.result.error);
                } else {
                    appendBotMessage("Sorry, I received an unexpected response.");
                }
            } else if (data.error) {
                appendBotMessage("Error: " + data.error.message);
            } else {
                appendBotMessage("Sorry, I couldn't get a response. Please try again.");
            }

        } catch (err) {
            hideTyping();
            appendBotMessage("Connection error: " + err.message);
            console.error("Chat error:", err);
        }
    }

    // ── 8. RESET (called by New Chat button in XML) ──────────
    window.resetChat = function () {
        chatBox.innerHTML = "";
        appendBotMessage("Hello! I'm Dragon Chat. How can I assist you today?");
    };

    // ── 9. EVENT LISTENERS ───────────────────────────────────

    // Send button
    if (sendBtn) {
        sendBtn.addEventListener("click", () => sendMessage());
    }

    // Enter key
    userInput.addEventListener("keypress", (e) => {
        if (e.key === "Enter") {
            e.preventDefault();
            sendMessage();
        }
    });

    // Quick reply buttons
    document.querySelectorAll(".quick-reply-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            sendMessage(btn.getAttribute("data-msg"));
        });
    });

    // ── 10. WELCOME MESSAGE ──────────────────────────────────
    appendBotMessage("Hello! I'm Dragon Chat. How can I assist you today?");

});