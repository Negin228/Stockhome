/**
 * Formatting helper for numbers
 */
function fmt(n, d = 1) {
    return (n == null || isNaN(n)) ? "N/A" : Number(n).toFixed(d);
}

/**
 * Renders a Buy Signal Card
 * Matches classes to CSS: .trend-strong, .trend-weak, .trend-up, .trend-down
 */
function renderBuyCard(b) {
    const put = b.put || {};
    const weeklyAvailable = (put.weekly_available !== false);
    const monthlyTag = (!weeklyAvailable) ? ' <span class="monthly">(Monthly)</span>' : '';

    // 1. Determine Strength Class
    // Checks if the rationale contains the word "Strong"
    const strengthClass = b.adx > 25
        ? 'trend-strong' 
        : 'trend-weak';

    // 2. Map Trend Direction Class
    // Maps Python "bullish"/"bearish" to CSS "trend-up"/"trend-down"
    const dirClass = b.trend_dir === 'bullish' ? 'trend-up' : 'trend-down';

    return `
    <li class="signal-card buy-card">
      <div class="main-info">
        <div class="ticker-block">
          <span class="ticker-alert">
            <a href="pages/filters.html?ticker=${b.ticker}" style="color: inherit; text-decoration: none;">
              ${b.ticker}
            </a>
          </span>
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
        <br>
        Sell a $${fmt(put.strike, 1)} put option expiring ${put.expiration || "N/A"}${monthlyTag} for $${fmt(put.premium, 2)}
        <br>[𝚫 ${fmt(put.delta_percent, 1)}% + 💎 ${fmt(put.premium_percent, 1)}%] = ${fmt(put.metric_sum, 1)}%
      </p>
      ${renderNews(b.news_summary, b.news)}
    </li>`;
}

/**
 * Renders a Sell Signal Card
 */
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

/**
 * Helper to render News section
 */
function renderNews(summary, items) {
    const safeSummary = summary ? `<p class="news-summary">${summary}..</p>` : "";
    if (!items || !items.length) return safeSummary;

    const list = items.slice(0, 4).map(n => {
        return `<li><a href="${n.url}" target="_blank" rel="noopener">${n.headline}</a></li>`;
    }).join("");

    return `${safeSummary}<ul class="news-list">${list}</ul>`;
}

/**
 * Main Initialization
 */
(async function () {
    const yearEl = document.getElementById("year");
    if (yearEl) yearEl.textContent = new Date().getFullYear();

    const buyList = document.getElementById("buy-list");
    const sellList = document.getElementById("sell-list");
    const lastUpdated = document.getElementById("last-updated");

    try {
        const res = await fetch("../data/signals.json", { cache: "no-store" });
        if (!res.ok) throw new Error(`signals.json fetch failed (${res.status})`);
        
        const data = await res.json();
        
        // Sorting by Market Cap
        if (data.buys) data.buys.sort((a, b) => (b.market_cap || 0) - (a.market_cap || 0));
        if (data.sells) data.sells.sort((a, b) => (b.market_cap || 0) - (a.market_cap || 0));

        if (lastUpdated) lastUpdated.textContent = data.generated_at_pt || "—";

        // Populate Buy List
        if (buyList) {
            buyList.innerHTML = (data.buys && data.buys.length)
                ? data.buys.map(renderBuyCard).join("")
                : `<li class="signal-card">No signals.</li>`;
        }

        // Populate Sell List
        if (sellList) {
            sellList.innerHTML = (data.sells && data.sells.length)
                ? data.sells.map(renderSellCard).join("")
                : `<li class="signal-card">No sell signals.</li>`;
        }

    } catch (e) {
        console.error("❌ Failed to load or render signals:", e);
        if (buyList) buyList.innerHTML = `<li class="signal-card">⚠️ Could not load signals: ${e.message}</li>`;
    }
})();
