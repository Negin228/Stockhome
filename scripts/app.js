/**
 * Formatting helper for numbers
 */
function fmt(n, d = 1) {
    return (n == null || isNaN(n)) ? "N/A" : Number(n).toFixed(d);
}

function formatEarningsDate(dateStr) {
    if (!dateStr) return "TBA";
    try {
        const date = new Date(dateStr);
        return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    } catch (e) { return "TBA"; }
}

function daysUntilEarnings(dateStr) {
    if (!dateStr) return null;
    try {
        const earningsDate = new Date(dateStr);
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        earningsDate.setHours(0, 0, 0, 0);
        return Math.ceil((earningsDate - today) / (1000 * 60 * 60 * 24));
    } catch (e) { return null; }
}

function isEarningsWithin6Weeks(dateStr) {
    const days = daysUntilEarnings(dateStr);
    return days !== null && days >= 0 && days <= 42;
}

function isMarketCapAbove100B(marketCap) {
    return !!marketCap && marketCap >= 100_000_000_000;
}

function renderBuyCard(b) {
    const put = b.put || {};
    const weeklyAvailable = (put.weekly_available !== false);
    const monthlyTag = weeklyAvailable ? '' : ' <span class="monthly">(Monthly)</span>';
    const strengthClass = b.adx > 25 ? 'trend-strong' : 'trend-weak';
    const dirClass = b.trend_dir === 'bullish' ? 'trend-up' : 'trend-down';
    const earningsDateFormatted = formatEarningsDate(b.earnings_date);

    return `
    <li class="signal-card buy-card"
        data-ticker="${b.ticker}"
        data-earnings-within-6weeks="${isEarningsWithin6Weeks(b.earnings_date)}"
        data-market-cap-above-100b="${isMarketCapAbove100B(b.market_cap)}"
        data-rsi-bb="${b.rsi_bb_signal === true}">
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
        <br><strong>Earnings:</strong> ${earningsDateFormatted}
        <br>Sell a $${fmt(put.strike, 1)} put option expiring ${put.expiration || "N/A"}${monthlyTag} for $${fmt(put.premium, 2)}
        <br>[𝚫 ${fmt(put.delta_percent, 1)}% + 💎 ${fmt(put.premium_percent, 1)}%] = ${fmt(put.metric_sum, 1)}%
      </p>
      ${renderNews(b.news_summary, b.news)}
    </li>`;
}

function renderSellCard(s) {
    const earningsDateFormatted = formatEarningsDate(s.earnings_date);
    return `
    <li class="signal-card sell-card"
        data-ticker="${s.ticker}"
        data-earnings-within-6weeks="${isEarningsWithin6Weeks(s.earnings_date)}"
        data-market-cap-above-100b="${isMarketCapAbove100B(s.market_cap)}"
        data-rsi-bb="false">
      <div class="main-info">
        <span class="ticker-alert">${s.ticker}</span>
        <div class="price-details">
          <div class="current-price price-down">${fmt(s.price, 2)}</div>
        </div>
      </div>
      <p class="news-summary">
        RSI=${fmt(s.rsi, 1)}, P/E=${fmt(s.pe, 1)}, Market Cap=${s.market_cap_str || "N/A"}
        <br><strong>Earnings:</strong> ${earningsDateFormatted}
      </p>
    </li>`;
}

function renderNews(summary, items) {
    const safeSummary = summary ? `<p class="news-summary">${summary}..</p>` : "";
    if (!items || !items.length) return safeSummary;
    const list = items.slice(0, 4).map(n =>
        `<li><a href="${n.url}" target="_blank" rel="noopener">${n.headline}</a></li>`
    ).join("");
    return `${safeSummary}<ul class="news-list">${list}</ul>`;
}

/**
 * Stamp purple BB badges on any rendered card with data-rsi-bb="true"
 * Called after innerHTML is set so DOM elements exist
 */
function stampBbBadges() {
    document.querySelectorAll('.signal-card[data-rsi-bb="true"]').forEach(card => {
        if (card.querySelector('.bb-badge')) return; // already stamped
        const tickerEl = card.querySelector('.ticker-alert');
        if (!tickerEl) return;
        const badge = document.createElement('span');
        badge.className = 'bb-badge';
        badge.textContent = 'BB';
        badge.style.cssText = 'display:inline-block;margin-left:8px;padding:2px 7px;' +
            'background:#7B2FBE;color:#fff;font-size:11px;font-weight:700;' +
            'border-radius:4px;vertical-align:middle;letter-spacing:0.03em;';
        tickerEl.insertAdjacentElement('afterend', badge);
    });
}

function applyFilters() {
    const earningsActive  = document.getElementById('earnings-filter-btn')?.classList.contains('active');
    const marketCapActive = document.getElementById('marketcap-filter-btn')?.classList.contains('active');
    const bbActive        = document.getElementById('bb-filter-btn')?.classList.contains('active');

    document.querySelectorAll('.signal-card').forEach(card => {
        let show = true;
        if (earningsActive  && card.getAttribute('data-earnings-within-6weeks') !== 'true') show = false;
        if (marketCapActive && card.getAttribute('data-market-cap-above-100b')   !== 'true') show = false;
        if (bbActive        && card.getAttribute('data-rsi-bb')                  !== 'true') show = false;
        card.style.display = show ? '' : 'none';
    });
}

function toggleEarningsFilter() {
    const btn = document.getElementById('earnings-filter-btn');
    if (!btn) return;
    btn.classList.toggle('active');
    btn.textContent = btn.classList.contains('active') ? 'Show All Earnings' : 'Earnings in 6 Weeks';
    applyFilters();
}

function toggleMarketCapFilter() {
    const btn = document.getElementById('marketcap-filter-btn');
    if (!btn) return;
    btn.classList.toggle('active');
    btn.textContent = btn.classList.contains('active') ? 'Show All Market Caps' : 'Market Cap > $100B';
    applyFilters();
}

function toggleBbFilter() {
    const btn = document.getElementById('bb-filter-btn');
    if (!btn) return;
    btn.classList.toggle('active');
    btn.textContent = btn.classList.contains('active') ? 'Show All Signals' : 'Price < Lower BB';
    applyFilters();
}

/**
 * Main Initialization
 */
(async function () {
    const yearEl = document.getElementById("year");
    if (yearEl) yearEl.textContent = new Date().getFullYear();

    const buyList     = document.getElementById("buy-list");
    const sellList    = document.getElementById("sell-list");
    const lastUpdated = document.getElementById("last-updated");

    try {
        const res = await fetch("../data/signals.json", { cache: "no-store" });
        if (!res.ok) throw new Error(`signals.json fetch failed (${res.status})`);
        const data = await res.json();

        // Log first buy so we can verify rsi_bb_signal field exists in your data
        if (data.buys && data.buys.length) {
            console.log('[app.js] Sample buy signal:', JSON.stringify({
                ticker: data.buys[0].ticker,
                rsi_bb_signal: data.buys[0].rsi_bb_signal
            }));
            const bbCount = data.buys.filter(b => b.rsi_bb_signal === true).length;
            console.log(`[app.js] ${bbCount} of ${data.buys.length} signals have rsi_bb_signal=true`);
        }

        if (data.buys)  data.buys.sort((a, b)  => (b.market_cap || 0) - (a.market_cap || 0));
        if (data.sells) data.sells.sort((a, b) => (b.market_cap || 0) - (a.market_cap || 0));

        if (lastUpdated) lastUpdated.textContent = data.generated_at_pt || "—";

        if (buyList) {
            buyList.innerHTML = (data.buys && data.buys.length)
                ? data.buys.map(renderBuyCard).join("")
                : `<li class="signal-card">No signals.</li>`;
            stampBbBadges(); // stamp badges immediately after render
        }

        if (sellList) {
            sellList.innerHTML = (data.sells && data.sells.length)
                ? data.sells.map(renderSellCard).join("")
                : `<li class="signal-card">No sell signals.</li>`;
        }

        document.getElementById('earnings-filter-btn') ?.addEventListener('click', toggleEarningsFilter);
        document.getElementById('marketcap-filter-btn')?.addEventListener('click', toggleMarketCapFilter);
        document.getElementById('bb-filter-btn')       ?.addEventListener('click', toggleBbFilter);

    } catch (e) {
        console.error("❌ Failed to load or render signals:", e);
        if (buyList) buyList.innerHTML = `<li class="signal-card">⚠️ Could not load signals: ${e.message}</li>`;
    }
})();
