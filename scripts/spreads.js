(async function () {
  const tableBody = document.getElementById("spreads-body");
  const lastUpdatedEl = document.getElementById("last-updated");

  // Helper to format numbers safely
  function fmt(n, d = 1) {
    return (n == null || isNaN(n)) ? "N/A" : Number(n).toFixed(d);
  }

  try {
    // 1. FETCH TIMESTAMP from signals.json (where the date lives)
    fetch("../data/signals.json", { cache: "no-store" })
      .then(res => res.json())
      .then(data => {
        if (data.generated_at_pt && lastUpdatedEl) {
          lastUpdatedEl.textContent = data.generated_at_pt + " PT";
        }
      })
      .catch(err => console.warn("Could not load timestamp from signals.json", err));

    // 2. FETCH SPREAD DATA from spreads.json
    const res = await fetch("../data/spreads.json", { cache: "no-store" });
    let signals = await res.json();

    console.log("Spreads loaded:", signals);

    // Ensure signals is an array (handling potential object wrappers)
    if (!Array.isArray(signals) && signals.data) {
        signals = signals.data;
    }

    // Sort by Market Cap (Highest first) as per your original logic
    signals.sort((a, b) => (b.mcap || 0) - (a.mcap || 0));

    if (signals && signals.length > 0) {
      tableBody.innerHTML = signals.map(s => `
        <tr class="${s.type}">
          <td><strong>${s.ticker}</strong></td>
          <td>${fmt(s.mcap, 1)}B</td>
          <td>$${fmt(s.price, 2)}</td>
          <td>${fmt(s.rsi, 1)}</td>
          <td>${fmt(s.adx, 1)}</td>
          <td>
            <span class="badge ${s.strategy.includes('Debit') ? 'debit' : 'credit'}">
              ${s.strategy}
            </span>
          </td>
          <td>
            ${s.is_squeeze 
              ? '<span class="text-warning">⚠️ Squeeze (Avoid)</span>' 
              : '<span class="text-success">✅ Volatility OK</span>'}
          </td>
          <td class="reasoning-cell" style="font-size: 0.85em; color: #666; text-align: left;">
            ${s.reasoning || "No detailed reasoning available."}
          </td>
        </tr>
      `).join("");
    } else {
      tableBody.innerHTML = `<tr><td colspan="8">No spread candidates found. (Coiling markets are being ignored).</td></tr>`;
    }

  } catch (e) {
    console.error("Spread loading error:", e);
    if (tableBody) {
      tableBody.innerHTML = `<tr><td colspan="8">Error loading spread data. Check console for details.</td></tr>`;
    }
  }
})();
