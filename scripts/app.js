scripts/app.js

function fmt(n, d = 1) {
  return (n == null || isNaN(n)) ? "N/A" : Number(n).toFixed(d);
}
function renderBuyCard(b) {
  const put = b.put || {};

  // If missing, treat weekly as available (default), so we DON'T mark monthly by accident
  const weeklyAvailable = (put.weekly_available !== false);

  // Mark only when weekly is NOT available (monthly-only)
  const monthlyTag = (!weeklyAvailable)
    ? ' <span class="monthly">(Monthly)</span>'
    : '';

  return `
    <li class="signal-card buy-card">
      <div class="main-info">
        <div class="ticker-block">
          <span class="ticker-alert">${b.ticker}</span>
          <span class="company-name">${b.company || ""}</span>
        </div>
        <div class="price-details">
          <div class="current-price price-up">${fmt(b.price, 2)}</div>
        </div>
      </div>
      <p class="news-summary">
        RSI=${fmt(b.rsi_str)}&nbsp;&nbsp;P/E=${fmt(b.pe_str)}&nbsp;&nbsp;
        DMA 50=${fmt(b.dma50_str)}&nbsp;&nbsp;DMA 200=${fmt(b.dma200_str)}&nbsp;&nbsp;Market Cap=$${b.market_cap_str || "N/A"}
        <br>
        Sell a $${fmt(put.strike, 1)} put option expiring ${put.expiration || "N/A"}${monthlyTag} for $${fmt(put.premium, 2)}
        <br>[𝚫 ${fmt(put.delta_percent, 1)}% + 💎 ${fmt(put.premium_percent, 1)}%] = ${fmt(put.metric_sum, 1)}%
      </p>
      ${renderNews(b.news_summary, b.news)}
    </li>`;
}


function renderSellCard(s) {
  return `
    <li class="signal-card sell-card">
      <div class="main-info">
        <span class="ticker-alert">${s.ticker}</span>
        <div class="price-details">
          <div class="current-price price-down">${fmt(s.price, 2)}</div>
        </div>
      </div>
      <p class="news-summary">
        RSI=${fmt(s.rsi, 1)}, P/E=${fmt(s.pe, 1)}, Market Cap=${s.market_cap_str || "N/A"}
      </p>
    </li>`;
}

function renderNews(summary, items) {
  const safeSummary = summary ? `<p class="news-summary">${summary}..</p>` : "";
  if (!items || !items.length) return safeSummary;

  const list = items.slice(0, 4).map(n => {
    return `<li><a href="${n.url}" target="_blank" rel="noopener">${n.headline}</a></li>`;
  }).join("");

  return `${safeSummary}<ul class="news-list">${list}</ul>`;
}

(async function () {
  const yearEl = document.getElementById("year");
  if (yearEl) yearEl.textContent = new Date().getFullYear();
  else console.warn("⚠️ #year element not found.");

  const buyList = document.getElementById("buy-list");
  const sellList = document.getElementById("sell-list");
  const lastUpdated = document.getElementById("last-updated");

  if (!buyList || !sellList) {
    console.warn("⚠️ Signal lists missing at load. app.js will wait for overlay.js to rebuild them.");
  }

  try {
    const res = await fetch("/data/signals.json", { cache: "no-store" });
    if (!res.ok) throw new Error(`signals.json fetch failed (${res.status})`);
    const data = await res.json();

    if (lastUpdated) lastUpdated.textContent = data.generated_at_pt || "—";
    else console.warn("⚠️ #last-updated element missing.");

    if (buyList) {
      buyList.innerHTML = (data.buys && data.buys.length)
        ? data.buys.map(renderBuyCard).join("")
        : `<li class="signal-card">No buy signals.</li>`;
    }
    if (sellList) {
      sellList.innerHTML = (data.sells && data.sells.length)
        ? data.sells.map(renderSellCard).join("")
        : `<li class="signal-card">No sell signals.</li>`;
    }
  } catch (e) {
    console.error("❌ Failed to load or render signals:", e);
    if (buyList) buyList.innerHTML = `<li class="signal-card">⚠️ Could not load signals.</li>`;
    if (sellList) sellList.innerHTML = "";
  }
})();
