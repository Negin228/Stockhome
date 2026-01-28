(async function () {
  const tableBody = document.getElementById("spreads-body");
  const lastUpdatedEl = document.getElementById("last-updated");

  function fmt(n, d = 1) {
    return (n == null || isNaN(n)) ? "N/A" : Number(n).toFixed(d);
  }

  try {
    const res = await fetch("../data/spreads.json", { cache: "no-store" });
    const payload = await res.json();

    // MATCHING THE FILTERS.HTML LOGIC
    if (payload.generated_at_pt && lastUpdatedEl) {
        // Appending " PT" manually to match your other pages
        lastUpdatedEl.textContent = payload.generated_at_pt + " PT";
    }

    let signals = Array.isArray(payload) ? payload : (payload.data || payload.all || []);
    
    signals.sort((a, b) => (b.mcap || 0) - (a.mcap || 0));

    if (signals.length === 0) {
      tableBody.innerHTML = `<tr><td colspan="7" style="text-align:center;">No candidates found.</td></tr>`;
      return;
    }

    tableBody.innerHTML = signals.map(s => {
      const sentimentClass = s.type === 'bullish' ? 'badge-bullish' : 'badge-bearish';
      return `
        <tr class="${s.type}">
          <td><strong>${s.ticker}</strong></td>
          <td>${fmt(s.mcap, 1)}B</td>
          <td>$${fmt(s.price, 2)}</td>
          <td>${fmt(s.rsi, 1)}</td>
          <td>${fmt(s.adx, 1)}</td>
          <td><span class="${sentimentClass}">${s.strategy}</span></td>
          <td class="reasoning-cell" style="font-size: 0.85em; color: #666; text-align: left;">
            ${s.reasoning || "No detailed reasoning available."}
          </td>
        </tr>
      `;
    }).join("");

  } catch (e) {
      console.error("Failed to load spreads:", e);
      if (tableBody) {
          tableBody.innerHTML = `<tr><td colspan="7" style="text-align:center;">Error loading data.</td></tr>`;
      }
    }
})();
