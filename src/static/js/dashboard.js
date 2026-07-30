/**
 * BookzCart Scraper Dashboard — Client-side logic
 * 
 * Handles:
 *   - SSE connection + auto-reconnect
 *   - DOM updates for all counters, progress bars, status badges
 *   - Elapsed time ticker
 *   - Accordion toggle
 *   - Form submission via fetch POST
 *   - UI lock/unlock on job start/complete
 *   - Log panel auto-scroll
 */

(function () {
    "use strict";

    // ────────────────────────────────────────────
    //  DOM references
    // ────────────────────────────────────────────

    const $ = (sel) => document.querySelector(sel);
    const $$ = (sel) => document.querySelectorAll(sel);

    const dom = {
        globalBadge:      $("#global-status-badge"),
        globalElapsed:    $("#global-elapsed"),
        endpointLabel:    $("#progress-endpoint-label"),
        overallPct:       $("#overall-pct"),
        overallBar:       $("#overall-bar"),
        pubPagesDone:     $("#pub-pages-done"),
        pubPagesTotal:    $("#pub-pages-total"),
        pubPagesBar:      $("#pub-pages-bar"),
        listPagesDone:    $("#list-pages-done"),
        listPagesTotal:   $("#list-pages-total"),
        listPagesBar:     $("#list-pages-bar"),
        productUrlsTotal: $("#product-urls-total"),
        productsProcessed:$("#products-processed"),
        productsRemaining:$("#products-remaining"),
        productsFailed:   $("#products-failed"),
        currentProductUrl:$("#current-product-url"),
        currentProductSec:$("#current-product-section"),
        // Sub-task pipeline
        scrapingDone:     $("#scraping-done"),
        scrapingBar:      $("#scraping-bar"),
        aiDone:           $("#ai-done"),
        aiFailed:         $("#ai-failed"),
        aiBar:            $("#ai-bar"),
        imagesDone:       $("#images-done"),
        imagesFailed:     $("#images-failed"),
        imagesBar:        $("#images-bar"),
        // Log
        logPanel:         $("#log-panel"),
        logEmpty:         $("#log-empty"),
        logCount:         $("#log-count"),
    };

    // ────────────────────────────────────────────
    //  State
    // ────────────────────────────────────────────

    let isRunning = false;
    let startedAtMs = 0;
    let elapsedInterval = null;
    let lastLogLength = 0;

    // ────────────────────────────────────────────
    //  SSE Connection
    // ────────────────────────────────────────────

    let evtSource = null;

    function connectSSE() {
        if (evtSource) {
            evtSource.close();
        }

        evtSource = new EventSource("/dashboard/sse");

        evtSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                updateUI(data);
            } catch (e) {
                // Ignore parse errors (heartbeats are comments, not data)
            }
        };

        evtSource.onerror = () => {
            // Auto-reconnect is built into EventSource; just log it
            console.warn("[SSE] Connection lost, reconnecting...");
        };
    }

    // ────────────────────────────────────────────
    //  UI Update
    // ────────────────────────────────────────────

    function updateUI(data) {
        // Status badge
        updateBadge(data.status);

        // Endpoint label
        if (data.endpoint) {
            const nameMap = { publisher: "Publisher", reprocess_skipped: "Reprocess Skipped URLs" };
            dom.endpointLabel.textContent = nameMap[data.endpoint] || data.endpoint;
        } else {
            dom.endpointLabel.textContent = "—";
        }

        // Overall progress
        dom.overallPct.textContent = data.overall_progress + "%";
        dom.overallBar.style.width = data.overall_progress + "%";

        // Publisher pages
        dom.pubPagesDone.textContent = fmt(data.publisher_pages_done);
        dom.pubPagesTotal.textContent = fmt(data.publisher_pages_total);
        dom.pubPagesBar.style.width = pct(data.publisher_pages_done, data.publisher_pages_total);

        // List pages
        dom.listPagesDone.textContent = fmt(data.list_pages_done);
        dom.listPagesTotal.textContent = fmt(data.list_pages_total);
        dom.listPagesBar.style.width = pct(data.list_pages_done, data.list_pages_total);

        // Product counters
        dom.productUrlsTotal.textContent = fmtComma(data.product_urls_total);
        dom.productsProcessed.textContent = fmtComma(data.products_processed);
        dom.productsRemaining.textContent = fmtComma(data.products_remaining);
        dom.productsFailed.textContent = fmtComma(data.products_failed);

        // Sub-task pipeline
        const total = data.product_urls_total || 0;
        dom.scrapingDone.textContent = fmtComma(data.scraping_done);
        dom.scrapingBar.style.width = pct(data.scraping_done, total);

        dom.aiDone.textContent = fmtComma(data.ai_done);
        dom.aiFailed.textContent = fmtComma(data.ai_failed);
        dom.aiBar.style.width = pct(data.ai_done + data.ai_failed, total);

        dom.imagesDone.textContent = fmtComma(data.images_done);
        dom.imagesFailed.textContent = fmtComma(data.images_failed);
        dom.imagesBar.style.width = pct(data.images_done + data.images_failed, total);

        // Current product URL
        if (data.current_product_url) {
            dom.currentProductUrl.textContent = data.current_product_url;
            dom.currentProductUrl.classList.remove("current-product__url--idle");
        } else {
            dom.currentProductUrl.textContent = "—";
            dom.currentProductUrl.classList.add("current-product__url--idle");
        }

        // Elapsed time
        if (data.status === "running" && data.started_at) {
            if (!elapsedInterval) {
                startedAtMs = new Date(data.started_at).getTime();
                startElapsedTicker();
            }
        } else if (data.status === "completed" || data.status === "failed") {
            stopElapsedTicker();
            dom.globalElapsed.textContent = fmtElapsed(data.elapsed_seconds);
        } else if (data.status === "idle") {
            stopElapsedTicker();
            dom.globalElapsed.textContent = "00:00:00";
        }

        // Lock / unlock UI
        if (data.status === "running" && !isRunning) {
            lockUI();
        } else if (data.status !== "running" && isRunning) {
            unlockUI();
        }

        // Log entries
        updateLog(data.log_entries || []);
    }

    function updateBadge(status) {
        dom.globalBadge.className = "badge";
        switch (status) {
            case "running":
                dom.globalBadge.classList.add("badge--running");
                dom.globalBadge.textContent = "Running";
                break;
            case "completed":
                dom.globalBadge.classList.add("badge--completed");
                dom.globalBadge.textContent = "Completed";
                break;
            case "failed":
                dom.globalBadge.classList.add("badge--failed");
                dom.globalBadge.textContent = "Failed";
                break;
            default:
                dom.globalBadge.classList.add("badge--idle");
                dom.globalBadge.textContent = "Idle";
        }
    }

    // ────────────────────────────────────────────
    //  Log Panel
    // ────────────────────────────────────────────

    function updateLog(entries) {
        if (entries.length === 0) return;

        // Only render new entries
        if (entries.length > lastLogLength) {
            if (dom.logEmpty) {
                dom.logEmpty.style.display = "none";
            }

            const frag = document.createDocumentFragment();

            for (let i = lastLogLength; i < entries.length; i++) {
                const div = document.createElement("div");
                div.className = "log-entry";

                const raw = entries[i];

                // Highlight successes and failures
                if (raw.includes("✅") || raw.includes("done")) {
                    div.classList.add("log-entry--success");
                } else if (raw.includes("❌") || raw.includes("FAILED")) {
                    div.classList.add("log-entry--error");
                }

                // Split timestamp from message
                const match = raw.match(/^\[(.+?)\]\s(.+)$/);
                if (match) {
                    const timeSpan = document.createElement("span");
                    timeSpan.className = "log-entry__time";
                    timeSpan.textContent = match[1];
                    div.appendChild(timeSpan);
                    div.appendChild(document.createTextNode(match[2]));
                } else {
                    div.textContent = raw;
                }

                frag.appendChild(div);
            }

            dom.logPanel.appendChild(frag);
            lastLogLength = entries.length;

            // Auto-scroll
            dom.logPanel.scrollTop = dom.logPanel.scrollHeight;
        }

        dom.logCount.textContent = entries.length + " entries";
    }

    // ────────────────────────────────────────────
    //  Elapsed Time Ticker
    // ────────────────────────────────────────────

    function startElapsedTicker() {
        stopElapsedTicker();
        elapsedInterval = setInterval(() => {
            const sec = (Date.now() - startedAtMs) / 1000;
            dom.globalElapsed.textContent = fmtElapsed(sec);
        }, 500);
    }

    function stopElapsedTicker() {
        if (elapsedInterval) {
            clearInterval(elapsedInterval);
            elapsedInterval = null;
        }
    }

    // ────────────────────────────────────────────
    //  UI Lock / Unlock
    // ────────────────────────────────────────────

    function lockUI() {
        isRunning = true;
        $$(".form-input").forEach((el) => (el.disabled = true));
        $$(".btn--primary").forEach((el) => (el.disabled = true));
    }

    function unlockUI() {
        isRunning = false;
        $$(".form-input").forEach((el) => (el.disabled = false));
        $$(".btn--primary").forEach((el) => (el.disabled = false));
    }

    // ────────────────────────────────────────────
    //  Accordion
    // ────────────────────────────────────────────

    $$(".accordion__toggle").forEach((btn) => {
        btn.addEventListener("click", () => {
            const expanded = btn.getAttribute("aria-expanded") === "true";
            const content = btn.nextElementSibling;

            // Close all others
            $$(".accordion__toggle").forEach((otherBtn) => {
                otherBtn.setAttribute("aria-expanded", "false");
                otherBtn.nextElementSibling.classList.remove("accordion__content--open");
            });

            if (!expanded) {
                btn.setAttribute("aria-expanded", "true");
                content.classList.add("accordion__content--open");
            }
        });
    });

    // ────────────────────────────────────────────
    //  Form Submission
    // ────────────────────────────────────────────

    $$(".endpoint-form").forEach((form) => {
        form.addEventListener("submit", async (e) => {
            e.preventDefault();

            if (isRunning) return;

            // Reset log
            lastLogLength = 0;
            dom.logPanel.querySelectorAll(".log-entry").forEach((el) => el.remove());
            if (dom.logEmpty) dom.logEmpty.style.display = "block";
            dom.logCount.textContent = "0 entries";

            const formData = new FormData(form);

            try {
                const res = await fetch("/dashboard/start", {
                    method: "POST",
                    body: formData,
                });

                const data = await res.json();

                if (!res.ok) {
                    alert(data.error || "Failed to start job");
                    return;
                }

                // Lock will happen via SSE update
            } catch (err) {
                alert("Network error: " + err.message);
            }
        });
    });

    // ────────────────────────────────────────────
    //  Formatting helpers
    // ────────────────────────────────────────────

    function fmt(n) {
        return n == null ? "0" : String(n);
    }

    function fmtComma(n) {
        return n == null ? "0" : n.toLocaleString();
    }

    function pct(done, total) {
        if (!total) return "0%";
        return Math.min(100, Math.round((done / total) * 100)) + "%";
    }

    function fmtElapsed(seconds) {
        const s = Math.floor(seconds);
        const h = String(Math.floor(s / 3600)).padStart(2, "0");
        const m = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
        const sec = String(s % 60).padStart(2, "0");
        return `${h}:${m}:${sec}`;
    }

    // ────────────────────────────────────────────
    //  Init
    // ────────────────────────────────────────────

    connectSSE();
})();
