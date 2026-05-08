document.addEventListener('DOMContentLoaded', () => {
    // 1. SELECT ELEMENTS
    const chatBox = document.getElementById("chat-box");
    const userInput = document.getElementById("user-input");
    const sendBtn = document.getElementById("send-msg-btn");
    const clearBtn = document.getElementById("clear-chat-btn");

    // 2. THE SAFETY GUARD (Prevents the Login Crash)
    if (!chatBox || !userInput) {
        console.log("Chatbot elements not found - probably not on chatbot page");
        return; // Exit quietly if elements aren't on this page
    }

    // 3. INTERNAL FUNCTIONS
    function appendMessage(text, className) {
        const msg = document.createElement("div");
        msg.className = "message " + className;
        msg.innerText = text;
        chatBox.appendChild(msg);
        chatBox.scrollTop = chatBox.scrollHeight;
    }

    function showLoading() {
        if (document.getElementById("loading-indicator")) return;
        const loader = document.createElement("div");
        loader.className = "message bot loading";
        loader.innerHTML = '<span class="dot"></span><span class="dot"></span><span class="dot"></span>';
        loader.id = "loading-indicator";
        chatBox.appendChild(loader);
        chatBox.scrollTop = chatBox.scrollHeight;
    }

    function hideLoading() {
        const loader = document.getElementById("loading-indicator");
        if (loader) loader.remove();
    }

    async function sendMessage(manualMsg = null) {
        const message = manualMsg || userInput.value.trim();
        if (!message) return;

        appendMessage(message, "user");
        if (!manualMsg) userInput.value = ""; // Only clear input if user typed it
        showLoading();

        try {
            const res = await fetch("/customer_support/chatbot/message", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    jsonrpc: "2.0",
                    method: "call",
                    params: { message: message }
                })
            });

            hideLoading();
            const data = await res.json();

            if (data.result) {
                if (data.result.reply) {
                    appendMessage(data.result.reply, "bot");
                } else if (data.result.error) {
                    appendMessage("Error: " + data.result.error, "err");
                } else {
                    appendMessage("Error: Unexpected response format", "err");
                }
            } else if (data.error) {
                appendMessage("Error: " + data.error.message, "err");
            } else {
                appendMessage("Error: Could not get response", "err");
            }
        } catch (err) {
            hideLoading();
            appendMessage("Error: " + err.message, "err");
            console.error("Chat error:", err);
        }
    }

    // 4. ATTACH LISTENERS (Instead of using onclick="" in XML)
    if (sendBtn) {
        sendBtn.addEventListener("click", () => sendMessage());
    }

    if (userInput) {
        userInput.addEventListener("keypress", (e) => {
            if (e.key === "Enter") {
                e.preventDefault();
                sendMessage();
            }
        });
    }

    if (clearBtn) {
        clearBtn.addEventListener("click", () => {
            if (confirm("Clear chat history?")) {
                chatBox.innerHTML = "";
                appendMessage("Chat cleared. How can I help you?", "bot");
            }
        });
    }

    // Delegate Quick Replies
    document.querySelectorAll(".quick-reply").forEach(btn => {
        btn.addEventListener("click", () => {
            sendMessage(btn.getAttribute('data-msg'));
        });
    });

    // 5. WELCOME MESSAGE
    appendMessage("Hello! I'm Dragon Chat. How can I assist you today?", "bot");
});