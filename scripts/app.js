// scripts/app.js
function fmt(n, d=1){ return (n==null || isNaN(n)) ? "N/A" : Number(n).toFixed(d); }

function renderBuyCard(b){
  const put = b.put || {};
  return `
    <li class="signal-card buy-card">
      <div class="main-info">
        <span class="ticker-alert">${b.ticker}</span>
        <div class="price-details"><div class="current-price price-up">${fmt(b.price,2)}</div></div>
      </div>
      <p class="news-summary">
        RSI=${fmt(b.rsi,1)}&nbsp;&nbsp;P/E=${fmt(b.pe,1)}&nbsp;&nbsp;DMA 50=${fmt(b.dma50,1)}&nbsp;&nbsp;DMA 200=${fmt(b.dma200,1)}&nbsp;&nbsp;Market Cap=${b.mcap||"N/A"}
        <br>Sell a $${fmt(put.strike,1)} put option expiring ${put.expiration || "N/A"} for $${fmt(put.premium,2)}
        <br>[𝚫 ${fmt(put.delta_percent,1)}% + 💎 ${fmt(put.premium_percent,1)}%] = ${fmt(put.metric_sum,1)}%
      </p>
      ${renderNews(b.news_summary, b.news)}
    </li>`;
}

function renderSellCard(s){
  return `
    <li class="signal-card sell-card">
      <div class="main-info">
        <span class="ticker-alert">${s.ticker}</span>
        <div class="price-details"><div class="current-price price-down">${fmt(s.price,2)}</div></div>
      </div>
      <p class="news-summary">RSI=${fmt(s.rsi,1)}, P/E=${fmt(s.pe,1)}, Market Cap=${s.mcap||"N/A"}</p>
    </li>`;
}

function renderNews(summary, items){
  const safeSummary = summary ? `<p class="news-summary">${summary}</p>` : "";
  if (!items || !items.length) return safeSummary;
  const list = items.slice(0,4).map(n=>{
    const emoji = (n.sentiment>0.2) ? "🟢" : (n.sentiment<-0.2) ? "🔴" : "⚪";
    return `<li><a href="${n.url}" target="_blank" rel="noopener">${n.headline}</a> - ${emoji} ${fmt(n.sentiment,1)}</li>`;
  }).join("");
  return `${safeSummary}<ul class="news-list">${list}</ul>`;
}

(async function(){
  document.getElementById("year").textContent = new Date().getFullYear();

  try{
    const res = await fetch("/data/signals.json", {cache:"no-store"});
    if(!res.ok) throw new Error("signals.json fetch failed");
    const data = await res.json();
    document.getElementById("last-updated").textContent = data.generated_at_pt || "—";

    const buyList = document.getElementById("buy-list");
    const sellList = document.getElementById("sell-list");

    buyList.innerHTML = (data.buys && data.buys.length)
      ? data.buys.map(renderBuyCard).join("")
      : `<li class="signal-card">No buy signals.</li>`;

    sellList.innerHTML = (data.sells && data.sells.length)
      ? data.sells.map(renderSellCard).join("")
      : `<li class="signal-card">No sell signals.</li>`;
  }catch(e){
    console.error(e);
    document.getElementById("buy-list").innerHTML = `<li class="signal-card">⚠️ Could not load signals.</li>`;
    document.getElementById("sell-list").innerHTML = "";
  }
})();
