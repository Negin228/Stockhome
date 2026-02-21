/**
 * rsi_bb_filter.js
 *
 * Two view modes toggled by #rsi-view-btn / #rsi-bb-view-btn.
 *
 * KEY DESIGN:
 *  - app.js owns #buy-list and the two filter buttons — we NEVER touch any of that.
 *  - We inject a sibling <ul id="bb-list"> and toggle display between the two lists.
 *  - BB cards carry the same data-* attributes app.js uses so its applyFilters()
 *    works correctly in both views automatically.
 */

(function () {
  "use strict";

  let currentView = "rsi";
  let allSignals  = [];

  let btnRsi, btnRsiBb, appList, bbList, sectionTitle, infobar;

  // ── Helpers copied from app.js so BB cards behave identically ──────────────
  function isEarningsWithin6Weeks(dateStr) {
    if (!dateStr) return false;
    try {
      const d     = new Date(dateStr);
      const today = new Date();
      today.setHours(0, 0, 0, 0);
      d.setHours(0, 0, 0, 0);
      const days = Math.ceil((d - today) / 86400000);
      return days >= 0 && days <= 42;
    } catch { return false; }
  }

  function isMarketCapAbove100B(mc) {
    return !!mc && mc >= 100_000_000_000;
  }

  function fmt(n, d = 1) {
    return (n == null || isNaN(n)) ? "N/A" : Number(n).toFixed(d);
  }

  function formatDate(ds) {
    if (!ds) return "TBA";
    try {
      return new Date(ds).toLocaleDateString("en-US",
        { month: "short", day: "numeric", year: "numeric" });
    } catch { return "TBA"; }
  }

  // ── BB card builder — same structure as app.js renderBuyCard ──────────────
  function buildBbCard(b) {
    const put = b.put || {};
    const weeklyAvailable = put.weekly_available !== false;
    const monthlyTag = weeklyAvailable ? "" : ' <span class="monthly">(Monthly)</span>';
    const strengthClass = b.adx > 25 ? "trend-strong" : "trend-weak";
    const dirClass      = b.trend_dir === "bullish" ? "trend-up" : "trend-down";

    return `
      <li class="signal-card buy-card"
          data-earnings-within-6weeks="${isEarningsWithin6Weeks(b.earnings_date)}"
          data-market-cap-above-100b="${isMarketCapAbove100B(b.market_cap)}">
        <div class="main-info">
          <div class="ticker-block">
            <span class="ticker-alert">
              <a href="pages/filters.html?ticker=${b.ticker}" style="color:inherit;text-decoration:none;">
                ${b.ticker}
              </a>
            </span>
            <span style="display:inline-block;margin-left:8px;padding:2px 7px;background:#7B2FBE;color:#fff;font-size:11px;font-weight:700;border-radius:4px;vertical-align:middle;">BB</span>
            <span class="company-name">${b.company || ""}</span>
          </div>
          <div class="price-details">
            <div class="current-price price-up">${fmt(b.price, 2)}</div>
          </div>
        </div>
        <div class="trend-badge ${strengthClass} ${dirClass}">
          ${b.trend_rationale || "Calculating..."}
        </div>
        <p class="news-summary">
          RSI=${fmt(b.rsi, 1)}&nbsp;&nbsp;P/E=${fmt(b.pe, 1)}&nbsp;&nbsp;
          DMA 50=${fmt(b.dma50, 1)}&nbsp;&nbsp;DMA 200=${fmt(b.dma200, 1)}&nbsp;&nbsp;Market Cap=$${b.market_cap_str || "N/A"}
          <br><strong>Earnings:</strong> ${formatDate(b.earnings_date)}
          <br>Sell a $${fmt(put.strike, 1)} put option expiring ${put.expiration || "N/A"}${monthlyTag} for $${fmt(put.premium, 2)}
          <br>[𝚫 ${fmt(put.delta_percent, 1)}% + 💎 ${fmt(put.premium_percent, 1)}%] = ${fmt(put.metric_sum, 1)}%
        </p>
      </li>`;
  }

  // ── Switch views ───────────────────────────────────────────────────────────
  function showRsiView() {
    currentView = "rsi";
    btnRsi.classList.add("active");
    btnRsiBb.classList.remove("active");
    infobar.classList.remove("visible");

    appList.style.display = "";   // show app.js list
    bbList.style.display  = "none"; // hide our list
    sectionTitle.textContent = "Put Options to Sell";

    // Re-run app.js's own filter logic so filter buttons stay correct
    if (typeof applyFilters === "function") applyFilters();
  }

  function showRsiBbView() {
    currentView = "rsi_bb";
    btnRsiBb.classList.add("active");
    btnRsi.classList.remove("active");
    infobar.classList.add("visible");

    appList.style.display = "none"; // hide app.js list
    bbList.style.display  = "";     // show our list

    const candidates = allSignals.filter(r => r.rsi_bb_signal === true);
    sectionTitle.textContent = `RSI & BB Signals (${candidates.length} found)`;

    bbList.innerHTML = candidates.length === 0
      ? `<li class="signal-card">No stocks currently meet the RSI &lt; 30 + Price ≤ BB Lower + No Squeeze criteria.</li>`
      : candidates.map(buildBbCard).join("");

    // Let app.js applyFilters() handle visibility of our cards too —
    // they have the right data-* attributes so it works automatically
    if (typeof applyFilters === "function") applyFilters();
  }

  // ── Load signals & init ────────────────────────────────────────────────────
  function init() {
    btnRsi       = document.getElementById("rsi-view-btn");
    btnRsiBb     = document.getElementById("rsi-bb-view-btn");
    appList      = document.getElementById("buy-list");
    sectionTitle = document.querySelector("#buy-signals h2");
    infobar      = document.getElementById("rsi-bb-infobar");

    if (!btnRsi || !btnRsiBb || !appList) return;

    // Inject our BB list as a sibling of the app.js list — hidden by default
    bbList = document.createElement("ul");
    bbList.id = "bb-list";
    bbList.className = appList.className; // inherit same CSS classes
    bbList.style.display = "none";
    appList.parentNode.insertBefore(bbList, appList.nextSibling);

    // Wire our toggle buttons only — do NOT touch the filter buttons
    btnRsi.addEventListener("click",   showRsiView);
    btnRsiBb.addEventListener("click", showRsiBbView);

    // Fetch signals.json (same file app.js uses)
    fetch("data/signals.json")
      .then(r => r.json())
      .then(data => { allSignals = data.buys || []; })
      .catch(() => {});
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

})();
