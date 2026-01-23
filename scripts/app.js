function fmt(n, d = 1) {
  return (n == null || isNaN(n)) ? "N/A" : Number(n).toFixed(d);
}

function renderBuyCard(b) {
  const put = b.put || {};

  // If missing, treat weekly as available (default)
  const weeklyAvailable = (put.weekly_available !== false);

  // Mark only when weekly is NOT available (monthly-only)
  const monthlyTag = (!weeklyAvailable)
    ? ' <span class="monthly">(Monthly)</span>'
    : '';

  return `
    <li class="signal-card buy-card">
      <div class="main-info">
        <div class="ticker-block">
          <span class="ticker-alert">
            <a href="pages/filters.html?ticker=${b.ticker}" style="color: inherit; text-decoration: none; border-bottom: 1px dashed opacity: 0.5;">
              ${b.ticker}
            </a>
          </span>
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

  const buyList = document.getElementById("buy-list");
  const sellList = document.getElementById("sell-list");
  const lastUpdated = document.getElementById("last-updated");

  try {
    const res = await fetch("../data/signals.json", { cache: "no-store" });
    if (!res.ok) throw new Error(`signals.json fetch failed (${res.status})`);
    const data = await res.json();
    if (data.buys) data.buys.sort((a, b) => (b.market_cap || 0) - (a.market_cap || 0));
    if (data.sells) data.sells.sort((a, b) => (b.market_cap || 0) - (a.market_cap || 0));

    if (lastUpdated) lastUpdated.textContent = data.generated_at_pt || "—";

    // Populate Buy List (Critical)
    if (buyList) {
      buyList.innerHTML = (data.buys && data.buys.length)
        ? data.buys.map(renderBuyCard).join("")
        : `<li class="signal-card">No buy signals.</li>`;
    }

    // Populate Sell List (Only if element exists in HTML)
    if (sellList) {
      sellList.innerHTML = (data.sells && data.sells.length)
        ? data.sells.map(renderSellCard).join("")
        : `<li class="signal-card">No sell signals.</li>`;
    }

  } catch (e) {
    console.error("❌ Failed to load or render signals:", e);
    // Print the specific error to the screen so you know why it failed
    if (buyList) buyList.innerHTML = `<li class="signal-card">⚠️ Could not load signals: ${e.message}</li>`;
  }
})();


##############
from config import TICKERS  # Import the list from your config file
@app.route('/spreads')
def spreads():
    ticker_objects = yf.Tickers(" ".join(TICKERS))
    results = []

    for ticker in TICKERS:
        try:
            # Fetch Market Cap and Technical Data
            mcap = ticker_objects.tickers[ticker].info.get('marketCap', 0)
            df = yf.download(ticker, period="60d", interval="1d", progress=False, auto_adjust=True)
            if df.empty: continue
            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)

            # Technical Analysis
            df.ta.bbands(length=20, std=2, append=True)
            df.ta.kc(length=20, scalar=2, append=True)
            df.ta.rsi(length=14, append=True)
            df.ta.adx(length=14, append=True)

            # Map Columns (Handling pandas_ta dynamic naming)
            cols = {
                'bbl': [c for c in df.columns if 'BBL' in c][0],
                'bbu': [c for c in df.columns if 'BBU' in c][0],
                'kcl': [c for c in df.columns if 'KCL' in c][0],
                'kcu': [c for c in df.columns if 'KCU' in c][0],
                'rsi': [c for c in df.columns if 'RSI' in c][0],
                'adx': [c for c in df.columns if 'ADX' in c][0]
            }

            curr = df.iloc[-1]
            p, r, a = curr['Close'], curr[cols['rsi']], curr[cols['adx']]
            bl, bu, kl, ku = curr[cols['bbl']], curr[cols['bbu']], curr[cols['kcl']], curr[cols['kcu']]

            # Rationale & Strategy Selection
            if p <= bl and r < 40 and a < 35 and bl < kl:
                strat = "Bull Call (Debit)" if r < 30 else "Bull Put (Credit)"
                results.append({
                    'ticker': ticker,
                    'mcap': round(mcap / 1e9, 2),
                    'strategy': strat,
                    'price': round(p, 2),
                    'rsi': round(r, 1),
                    'adx': round(a, 1),
                    'type': 'bullish'
                })
            elif p >= bu and r > 60 and a < 35 and bu > ku:
                strat = "Bear Put (Debit)" if r > 70 else "Bear Call (Credit)"
                results.append({
                    'ticker': ticker,
                    'mcap': round(mcap / 1e9, 2),
                    'strategy': strat,
                    'price': round(p, 2),
                    'rsi': round(r, 1),
                    'adx': round(a, 1),
                    'type': 'bearish'
                })
        except Exception as e:
            print(f"Error scanning {ticker}: {e}")

    # Sort by Market Cap (Highest first)
    sorted_results = sorted(results, key=lambda x: x['mcap'], reverse=True)
    
    return render_template('spreads.html', signals=sorted_results)
