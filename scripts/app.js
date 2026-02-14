/**
 * Formatting helper for numbers
 */
function fmt(n, d = 1) {
    return (n == null || isNaN(n)) ? "N/A" : Number(n).toFixed(d);
}

/**
 * Format earnings date to human-readable format
 * @param {string} dateStr - Date string in YYYY-MM-DD format
 * @returns {string} Formatted date or "TBA" if not available
 */
function formatEarningsDate(dateStr) {
    if (!dateStr) return "TBA";
    try {
        const date = new Date(dateStr);
        const options = { month: 'short', day: 'numeric', year: 'numeric' };
        return date.toLocaleDateString('en-US', options);
    } catch (e) {
        return "TBA";
    }
}

/**
 * Calculate days until earnings date
 * @param {string} dateStr - Date string in YYYY-MM-DD format
 * @returns {number|null} Number of days until earnings, or null if not available
 */
function daysUntilEarnings(dateStr) {
    if (!dateStr) return null;
    try {
        const earningsDate = new Date(dateStr);
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        earningsDate.setHours(0, 0, 0, 0);
        const diffTime = earningsDate - today;
        const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
        return diffDays;
    } catch (e) {
        return null;
    }
}

/**
 * Check if earnings is within 6 weeks (42 days)
 * @param {string} dateStr - Date string in YYYY-MM-DD format
 * @returns {boolean} True if earnings within 6 weeks
 */
function isEarningsWithin6Weeks(dateStr) {
    const days = daysUntilEarnings(dateStr);
    if (days === null) return false;
    return days >= 0 && days <= 42; // 6 weeks = 42 days
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
    const strengthClass = b.adx > 25 ? 'trend-strong' : 'trend-weak';

    // 2. Map Trend Direction Class
    const dirClass = b.trend_dir === 'bullish' ? 'trend-up' : 'trend-down';

    // 3. Format earnings date
    const earningsDateFormatted = formatEarningsDate(b.earnings_date);

    return `
    <li class="signal-card buy-card" data-earnings-within-6weeks="${isEarningsWithin6Weeks(b.earnings_date)}">
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
        <strong>Earnings:</strong> ${earningsDateFormatted}
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
    const earningsDateFormatted = formatEarningsDate(s.earnings_date);

    return `
    <li class="signal-card sell-card" data-earnings-within-6weeks="${isEarningsWithin6Weeks(s.earnings_date)}">
      <div class="main-info">
        <span class="ticker-alert">${s.ticker}</span>
        <div class="price-details">
          <div class="current-price price-down">${fmt(s.price, 2)}</div>
        </div>
      </div>
      <p class="news-summary">
        RSI=${fmt(s.rsi, 1)}, P/E=${fmt(s.pe, 1)}, Market Cap=${s.market_cap_str || "N/A"}
        <br>
        <strong>Earnings:</strong> ${earningsDateFormatted}
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
 * Apply filters to signal cards
 */
function applyFilters() {
    const earningsFilter = document.getElementById('earnings-filter');
    if (!earningsFilter) return;

    const filterValue = earningsFilter.value;
    const cards = document.querySelectorAll('.signal-card');

    cards.forEach(card => {
        const hasEarningsWithin6Weeks = card.getAttribute('data-earnings-within-6weeks') === 'true';
        
        if (filterValue === 'all') {
            card.style.display = '';
        } else if (filterValue === 'yes' && hasEarningsWithin6Weeks) {
            card.style.display = '';
        } else if (filterValue === 'no' && !hasEarningsWithin6Weeks) {
            card.style.display = '';
        } else {
            card.style.display = 'none';
        }
    });
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

        // Set up filter event listener
        const earningsFilter = document.getElementById('earnings-filter');
        if (earningsFilter) {
            earningsFilter.addEventListener('change', applyFilters);
        }

    } catch (e) {
        console.error("❌ Failed to load or render signals:", e);
        if (buyList) buyList.innerHTML = `<li class="signal-card">⚠️ Could not load signals: ${e.message}</li>`;
    }
})();
