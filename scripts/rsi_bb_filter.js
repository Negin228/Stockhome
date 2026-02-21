/**
 * rsi_bb_filter.js
 * Handles two view modes:
 *   "rsi"    — the existing Put Options to Sell cards (default, driven by app.js)
 *   "rsi_bb" — cards filtered to rsi_bb_signal === true
 *
 * Also wires the Earnings and Market Cap filter buttons so they work in BOTH views.
 */

(function () {
  "use strict";

  // ── State ──────────────────────────────────────────────────────────────────
  let currentView = "rsi";          // "rsi" | "rsi_bb"
  let allSignals  = [];             // full buys array from signals.json
  let activeEarningsFilter  = false;
  let activeMarketCapFilter = false;

  // ── DOM refs (set after DOMContentLoaded) ──────────────────────────────────
  let btnRsi, btnRsiBb, btnEarnings, btnMarketCap;
  let buyList, sectionTitle;

  // ── Helpers ────────────────────────────────────────────────────────────────
  function setActive(btn, active) {
    btn.classList.toggle("active", active);
  }

  function applyFilters(rows) {
    let out = rows;
    if (activeEarningsFilter) {
      const sixWeeks = Date.now() + 42 * 24 * 60 * 60 * 1000;
      out = out.filter(r => {
        if (!r.earnings_date) return false;
        const d = new Date(r.earnings_date).getTime();
        return d > Date.now() && d <= sixWeeks;
      });
    }
    if (activeMarketCapFilter) {
      out = out.filter(r => (r.market_cap || 0) >= 100e9);
    }
    return out;
  }

  // ── Card builder — mirrors the exact style used by app.js ─────────────────
  function buildCard(r) {
    const put = r.put || {};

    // Trend badge
    const trendText  = r.trend_rationale || "";
    const trendClass = (r.trend_dir === "bearish") ? "bearish-trend" : "bullish-trend";

    // Earnings line
    const earningsHtml = r.earnings_date
      ? `<p><em>Earnings: ${formatDate(r.earnings_date)}</em></p>`
      : "";

    // Put suggestion line
    let putHtml = "";
    if (put.strike && put.expiration && put.premium) {
      putHtml = `<p>Sell a $${put.strike.toFixed(1)} put option expiring ${put.expiration} for $${put.premium.toFixed(2)}</p>`;
    }

    // Metric line
    let metricHtml = "";
    if (put.delta_percent != null && put.premium_percent != null) {
      metricHtml = `<p>[Δ ${put.delta_percent.toFixed(1)}% + 💎 ${put.premium_percent.toFixed(1)}%] = ${(put.delta_percent + put.premium_percent).toFixed(1)}%</p>`;
    }

    // BB badge for RSI & BB view
    const bbBadge = currentView === "rsi_bb"
      ? `<span class="bb-badge">BB Signal</span>`
      : "";

    return `
      <li class="signal-card">
        <div class="card-header">
          <div class="card-left">
            <span class="ticker">${r.ticker}</span>${bbBadge}
            <span class="company">${r.company || ""}</span>
          </div>
          <span class="price" style="color:#4CAF50; font-weight:700; font-size:1.3em">${r.price_str || r.price}</span>
        </div>
        <div class="trend-badge ${trendClass}">${trendText}</div>
        <div class="card-body">
          <p>RSI=${r.rsi_str || r.rsi}&nbsp; P/E=${r.pe_str || "N/A"}&nbsp; DMA 50=${r.dma50_str || ""}&nbsp; DMA 200=${r.dma200_str || ""}&nbsp; Market Cap=$${r.market_cap_str || ""}</p>
          ${earningsHtml}
          ${putHtml}
          ${metricHtml}
        </div>
      </li>`;
  }

  function formatDate(ds) {
    try {
      const d = new Date(ds + "T00:00:00");
      return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
    } catch { return ds; }
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  function render() {
    if (!buyList) return;

    if (currentView === "rsi") {
      // Let app.js own the RSI view — just show/hide its output and re-apply filters
      renderRsiView();
    } else {
      renderRsiBbView();
    }
  }

  function renderRsiView() {
    // Restore app.js cards and re-apply filters by toggling visibility
    const allCards = buyList.querySelectorAll("li.signal-card");
    if (allCards.length === 0 && allSignals.length > 0) {
      // app.js hasn't rendered yet — let it do its thing, we'll hook in later
      return;
    }

    // If we have app.js cards, hide/show based on active filters
    if (allCards.length > 0) {
      const sixWeeks = Date.now() + 42 * 24 * 60 * 60 * 1000;
      allCards.forEach(card => {
        const ticker = card.querySelector(".ticker")?.textContent?.trim();
        const sig = allSignals.find(s => s.ticker === ticker);
        if (!sig) { card.style.display = ""; return; }

        let show = true;
        if (activeEarningsFilter && sig.earnings_date) {
          const d = new Date(sig.earnings_date).getTime();
          show = show && (d > Date.now() && d <= sixWeeks);
        } else if (activeEarningsFilter) {
          show = false;
        }
        if (activeMarketCapFilter) {
          show = show && (sig.market_cap || 0) >= 100e9;
        }
        card.style.display = show ? "" : "none";
      });
      sectionTitle.textContent = "Put Options to Sell";
      return;
    }

    // Fallback: render from allSignals
    const filtered = applyFilters(allSignals);
    buyList.innerHTML = filtered.map(buildCard).join("");
    sectionTitle.textContent = "Put Options to Sell";
  }

  function renderRsiBbView() {
    const candidates = allSignals.filter(r => r.rsi_bb_signal === true);
    const filtered   = applyFilters(candidates);

    sectionTitle.textContent = `RSI & BB Signals (${filtered.length} found)`;

    if (filtered.length === 0) {
      buyList.innerHTML = `<li class="no-signals">No stocks currently meet the RSI &lt; 30 + Price ≤ BB Lower + No Squeeze criteria.</li>`;
      return;
    }

    buyList.innerHTML = filtered.map(buildCard).join("");
  }

  // ── Load signals.json ──────────────────────────────────────────────────────
  function loadSignals() {
    // Try to piggyback on whatever app.js already fetched
    fetch("data/signals.json")
      .then(r => r.json())
      .then(data => {
        allSignals = (data.buys || []);
        // Seed app.js cards into allSignals for filter support
        if (currentView === "rsi") renderRsiView();
      })
      .catch(() => {});
  }

  // ── Button wiring ──────────────────────────────────────────────────────────
  function switchView(view) {
    currentView = view;
    setActive(btnRsi,   view === "rsi");
    setActive(btnRsiBb, view === "rsi_bb");

    if (view === "rsi") {
      // Restore all app.js cards first
      buyList.querySelectorAll("li.signal-card").forEach(c => c.style.display = "");
      // Remove any RSI&BB-injected cards and let app.js cards show
      renderRsiView();
    } else {
      renderRsiBbView();
    }
  }

  // ── Init ───────────────────────────────────────────────────────────────────
  function init() {
    btnRsi      = document.getElementById("rsi-filter-btn");
    btnRsiBb    = document.getElementById("rsi-bb-filter-btn");
    btnEarnings = document.getElementById("earnings-filter-btn");
    btnMarketCap = document.getElementById("marketcap-filter-btn");
    buyList      = document.getElementById("buy-list");
    sectionTitle = document.querySelector("#buy-signals h2");

    if (!btnRsiBb) return; // guard if elements missing

    // Default state: RSI view active
    setActive(btnRsi, true);
    setActive(btnRsiBb, false);

    btnRsi.addEventListener("click", () => switchView("rsi"));
    btnRsiBb.addEventListener("click", () => switchView("rsi_bb"));

    btnEarnings.addEventListener("click", () => {
      activeEarningsFilter = !activeEarningsFilter;
      setActive(btnEarnings, activeEarningsFilter);
      render();
    });

    btnMarketCap.addEventListener("click", () => {
      activeMarketCapFilter = !activeMarketCapFilter;
      setActive(btnMarketCap, activeMarketCapFilter);
      render();
    });

    loadSignals();

    // Watch for app.js finishing its render so filter buttons work on its cards
    const observer = new MutationObserver(() => {
      if (currentView === "rsi") renderRsiView();
    });
    if (buyList) {
      observer.observe(buyList, { childList: true });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

})();
