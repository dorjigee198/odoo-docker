/**
 * Session Timeout — inactivity tracker for all dashboard pages.
 *
 * Timeline:
 *   25 min idle  → warning banner appears with countdown
 *   30 min idle  → auto logout
 *   Any activity → resets the clock, dismisses the banner
 */
(function () {
    'use strict';

    const WARN_AFTER_MS   = 25 * 60 * 1000;   // 25 minutes
    const LOGOUT_AFTER_MS = 30 * 60 * 1000;   // 30 minutes
    const TICK_MS         = 1000;

    let lastActivity = Date.now();
    let bannerEl     = null;
    let warnShown    = false;
    let countdownEl  = null;

    // ── Inject banner CSS once ────────────────────────────────
    const style = document.createElement('style');
    style.textContent = `
        #st-timeout-banner {
            position: fixed; bottom: 1.5rem; left: 50%; transform: translateX(-50%);
            z-index: 99999; min-width: 340px; max-width: 520px;
            background: #1e293b; border: 1px solid #f59e0b;
            border-radius: 12px; box-shadow: 0 8px 32px rgba(0,0,0,0.4);
            padding: 0.9rem 1.2rem;
            display: flex; align-items: center; gap: 0.85rem;
            animation: st-slide-up 0.3s ease;
            font-family: 'Inter','Segoe UI',sans-serif;
        }
        @keyframes st-slide-up {
            from { opacity:0; transform: translateX(-50%) translateY(16px); }
            to   { opacity:1; transform: translateX(-50%) translateY(0); }
        }
        #st-timeout-banner .st-icon {
            font-size: 1.4rem; color: #f59e0b; flex-shrink: 0;
        }
        #st-timeout-banner .st-text {
            flex: 1; font-size: 0.82rem; color: #cbd5e1; line-height: 1.4;
        }
        #st-timeout-banner .st-text strong {
            color: #f59e0b; font-size: 0.9rem;
        }
        #st-timeout-banner .st-stay {
            background: #f59e0b; color: #0f172a; border: none; border-radius: 7px;
            padding: 0.4rem 0.9rem; font-size: 0.78rem; font-weight: 700;
            cursor: pointer; white-space: nowrap; flex-shrink: 0;
            transition: background 0.15s;
        }
        #st-timeout-banner .st-stay:hover { background: #fbbf24; }
    `;
    document.head.appendChild(style);

    // ── Activity listeners ────────────────────────────────────
    ['mousemove', 'mousedown', 'keypress', 'touchstart', 'scroll', 'click'].forEach(evt => {
        document.addEventListener(evt, resetTimer, { passive: true });
    });

    function resetTimer() {
        lastActivity = Date.now();
        if (warnShown) dismissBanner();
    }

    function dismissBanner() {
        warnShown = false;
        if (bannerEl) { bannerEl.remove(); bannerEl = null; countdownEl = null; }
    }

    function showBanner(secondsLeft) {
        if (bannerEl) return;
        bannerEl = document.createElement('div');
        bannerEl.id = 'st-timeout-banner';
        bannerEl.innerHTML = `
            <span class="st-icon"><i class="bi bi-clock-history"></i></span>
            <span class="st-text">
                Session expiring in <strong id="st-countdown">${secondsLeft}s</strong> due to inactivity.
            </span>
            <button class="st-stay">Stay logged in</button>
        `;
        document.body.appendChild(bannerEl);
        bannerEl.querySelector('.st-stay').addEventListener('click', resetTimer);
        countdownEl = document.getElementById('st-countdown');
        warnShown = true;
    }

    // ── Tick loop ─────────────────────────────────────────────
    function tick() {
        const idle = Date.now() - lastActivity;

        if (idle >= LOGOUT_AFTER_MS) {
            window.location.replace('/customer_support/logout_manual');
            return;
        }

        if (idle >= WARN_AFTER_MS) {
            const secsLeft = Math.ceil((LOGOUT_AFTER_MS - idle) / 1000);
            if (!warnShown) {
                showBanner(secsLeft);
            } else if (countdownEl) {
                countdownEl.textContent = secsLeft + 's';
            }
        }

        setTimeout(tick, TICK_MS);
    }

    // Start ticking after initial WARN_AFTER_MS delay (no point checking sooner)
    setTimeout(tick, WARN_AFTER_MS);

})();
