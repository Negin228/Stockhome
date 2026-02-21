/**
 * rsi_bb_filter.js
 */

(function () {
  "use strict";

  let currentView = "rsi";
  let allSignals  = [];

  let btnRsi, btnRsiBb, appList, bbList, sectionTitle, infobar;

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

  function setInfobar(view) {
    // Force display via inline style — overrides the CSS `display:none` default
    // regardless of whether the .visible class has been processed yet
    infobar.style.display = "block";

    if (view === "rsi") {
      infobar.innerHTML = '<strong style="color:#2196F3;">RSI criteria:</strong> RSI &lt; 30 &nbsp;·&nbsp; Oversold condition based on 14-day Relative Strength Index';
      infobar.style.borderLeftColor = "#2196F3";
      infobar.style.background      = "#e8f4fd";
      infobar.style.color           = "#1a3a5c";
    } else {
      infobar.innerHTML = '<strong style="color:#7B2FBE;">RSI &amp; BB criteria:</strong> Price &gt; $100 &nbsp;·&nbsp; Price ≤ Bollinger Lower Band &nbsp;·&nbsp; RSI &lt; 30 &nbsp;·&nbsp; No BB/KC Squeeze';
      infobar.style.borderLeftColor = "#7B2FBE";
      infobar.style.background      = "#f3eeff";
      infobar.style.color           = "#4a3570";
    }
  }

  function showRsiView() {
    currentView = "rsi";
    btnRsi.classList.add("active");
    btnRsiBb.classList.remove("active");

    appList.style.display = "";
    bbList.style.display  = "none";
    sectionTitle.textContent = "Put Options to Sell";

    setInfobar("rsi");

    if (typeof applyFilters === "function") applyFilters();
  }

  function showRsiBbView() {
    currentView = "rsi_bb";
    btnRsiBb.classList.add("active");
    btnRsi.classList.remove("active");

    appList.style.display = "none";
    bbList.style.display  = "";

    const candidates = allSignals.filter(r => r.rsi_bb_signal === true);
    sectionTitle.textContent = `RSI & BB Signals (${candidates.length} found)`;

    bbList.innerHTML = candidates.length === 0
      ? `<li class="signal-card">No stocks currently meet the RSI &lt; 30 + Price ≤ BB Lower + No Squeeze criteria.</li>`
      : candidates.map(buildBbCard).join("");

    setInfobar("rsi_bb");

    if (typeof applyFilters === "function") applyFilters();
  }

  function init() {
    btnRsi       = document.getElementById("rsi-view-btn");
    btnRsiBb     = document.getElementById("rsi-bb-view-btn");
    appList      = document.getElementById("buy-list");
    sectionTitle = document.querySelector("#buy-signals h2");
    infobar      = document.getElementById("rsi-bb-infobar");

    if (!btnRsi || !btnRsiBb || !appList || !infobar) return;

    bbList = document.createElement("ul");
    bbList.id = "bb-list";
    bbList.className = appList.className;
    bbList.style.display = "none";
    appList.parentNode.insertBefore(bbList, appList.nextSibling);

    btnRsi.addEventListener("click",   showRsiView);
    btnRsiBb.addEventListener("click", showRsiBbView);

    fetch("data/signals.json")
      .then(r => r.json())
      .then(data => { allSignals = data.buys || []; })
      .catch(() => {});

    // Show RSI infobar immediately on load
    setInfobar("rsi");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

})();
