/**
 * rsi_bb_filter.js
 * Handles two view modes:
 *   "rsi"    — the existing Put Options to Sell cards (default, driven by app.js)
 *   "rsi_bb" — cards filtered to rsi_bb_signal === true
 */

(function () {
  "use strict";

  let currentView = "rsi";
  let allSignals  = [];
  let activeEarningsFilter  = false;
  let activeMarketCapFilter = false;

  // Snapshot of app.js-rendered HTML — saved before we ever touch buyList
  let rsiSnapshot = null;

  let btnRsi, btnRsiBb, btnEarnings, btnMarketCap;
  let buyList, sectionTitle, infobar;

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

  function formatDate(ds) {
    try {
      const d = new Date(ds + "T00:00:00");
      return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
    } catch { return ds; }
  }

  // ── Card builder for RSI & BB view — styled to match app.js cards ──────────
  function buildCard(r) {
    const put = r.put || {};

    const trendText  = r.trend_rationale || "";
    const trendClass = (r.trend_dir === "bearish") ? "bearish-trend" : "bullish-trend";

    const earningsHtml = r.earnings_date
      ? `<p><em>Earnings: ${formatDate(r.earnings_date)}</em></p>`
      : "";

    let putHtml = "";
    if (put.strike && put.expiration && put.premium) {
      putHtml = `<p>Sell a $${put.strike.toFixed(1)} put option expiring ${put.expiration} for $${put.premium.toFixed(2)}</p>`;
    }

    let metricHtml = "";
    if (put.delta_percent != null && put.premium_percent != null) {
      metricHtml = `<p>[Δ ${put.delta_percent.toFixed(1)}% + 💎 ${put.premium_percent.toFixed(1)}%] = ${(put.delta_percent + put.premium_percent).toFixed(1)}%</p>`;
    }

    return `
      <li class="signal-card">
        <div class="card-header">
          <div class="card-left">
            <span class="ticker">${r.ticker}</span>
            <span class="bb-badge" style="
              display:inline-block;
              margin-left:8px;
              padding:2px 8px;
              background:#7B2FBE;
              color:#fff;
              font-size:11px;
              font-weight:700;
              border-radius:4px;
              vertical-align:middle;
              letter-spacing:0.03em;
            ">BB Signal</span>
            <br><span class="company">${r.company || ""}</span>
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

  // ── Render RSI & BB view ───────────────────────────────────────────────────
  function renderRsiBbView() {
    // Save app.js snapshot before overwriting for the first time
    if (rsiSnapshot === null) {
      rsiSnapshot = buyList.innerHTML;
    }

    const candidates = allSignals.filter(r => r.rsi_bb_signal === true);
    const filtered   = applyFilters(candidates);

    sectionTitle.textContent = `RSI & BB Signals (${filtered.length} found)`;

    if (filtered.length === 0) {
      buyList.innerHTML = `<li class="no-signals">No stocks currently meet the RSI &lt; 30 + Price ≤ BB Lower + No Squeeze criteria.</li>`;
      return;
    }

    buyList.innerHTML = filtered.map(buildCard).join("");
  }

  // ── Render RSI view (restore app.js cards) ─────────────────────────────────
  function renderRsiView() {
    // Restore original app.js HTML if we have it
    if (rsiSnapshot !== null) {
      buyList.innerHTML = rsiSnapshot;
    }

    sectionTitle.textContent = "Put Options to Sell";

    // Apply filters on top of restored cards
    if (activeEarningsFilter || activeMarketCapFilter) {
      const sixWeeks = Date.now() + 42 * 24 * 60 * 60 * 1000;
      buyList.querySelectorAll("li.signal-card").forEach(card => {
        const ticker = card.querySelector(".ticker")?.textContent?.trim();
        const sig = allSignals.find(s => s.ticker === ticker);
        if (!sig) { card.style.display = ""; return; }

        let show = true;
        if (activeEarningsFilter) {
          if (!sig.earnings_date) {
            show = false;
          } else {
            const d = new Date(sig.earnings_date).getTime();
            show = show && (d > Date.now() && d <= sixWeeks);
          }
        }
        if (activeMarketCapFilter) {
          show = show && (sig.market_cap || 0) >= 100e9;
        }
        card.style.display = show ? "" : "none";
      });
    }
  }

  function render() {
    if (!buyList) return;
    if (currentView === "rsi") {
      renderRsiView();
    } else {
      renderRsiBbView();
    }
  }

  // ── Load signals.json ──────────────────────────────────────────────────────
  function loadSignals() {
    fetch("data/signals.json")
      .then(r => r.json())
      .then(data => {
        allSignals = (data.buys || []);
      })
      .catch(() => {});
  }

  // ── View switcher ──────────────────────────────────────────────────────────
  function switchView(view) {
    currentView = view;
    setActive(btnRsi,   view === "rsi");
    setActive(btnRsiBb, view === "rsi_bb");
    infobar.classList.toggle("visible", view === "rsi_bb");

    if (view === "rsi") {
      renderRsiView();
    } else {
      renderRsiBbView();
    }
  }

  // ── Init ───────────────────────────────────────────────────────────────────
  function init() {
    btnRsi       = document.getElementById("rsi-view-btn");
    btnRsiBb     = document.getElementById("rsi-bb-view-btn");
    btnEarnings  = document.getElementById("earnings-filter-btn");
    btnMarketCap = document.getElementById("marketcap-filter-btn");
    buyList      = document.getElementById("buy-list");
    sectionTitle = document.querySelector("#buy-signals h2");
    infobar      = document.getElementById("rsi-bb-infobar");

    if (!btnRsiBb || !buyList) return;

    setActive(btnRsi, true);
    setActive(btnRsiBb, false);
    infobar.classList.remove("visible");

    btnRsi.addEventListener("click",   () => switchView("rsi"));
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

    // Watch for app.js finishing its render — capture snapshot once it populates
    const observer = new MutationObserver(() => {
      if (currentView === "rsi" && buyList.children.length > 0 && rsiSnapshot === null) {
        rsiSnapshot = buyList.innerHTML;
      }
    });
    observer.observe(buyList, { childList: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

})();
