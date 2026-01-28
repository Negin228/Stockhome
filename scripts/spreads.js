(async function () {
  const tableBody = document.getElementById("spreads-body");

  function fmt(n, d = 1) {
    return (n == null || isNaN(n)) ? "N/A" : Number(n).toFixed(d);
  }

  try {
    // 1. FETCH TIMESTAMP
    fetch("../data/signals.json", { cache: "no-store" })
      .then(res => res.json())
      .then(data => {
        if (data.generated_at_pt) {
          const timestamp = data.generated_at_pt + " PT";
          const elements = ["last-updated", "Last-updated"];
          elements.forEach(id => {
            const el = document.getElementById(id);
            if (el) el.textContent = timestamp;
          });
        }
      })
      .catch(err => console.warn("Could not load timestamp", err));

    // 2. FETCH AND FILTER DATA
    const res = await fetch("../data/spreads.json", { cache: "no-store" });
    let signals = await res.json();

    if (!Array.isArray(signals) && signals.data) {
        signals = signals.data;
    }

    // Filter: Show only if NOT a squeeze (Volatility OK)
    const validSignals = signals.filter(s => !s.is_squeeze);

    // Sort by Market Cap
    validSignals.sort((a, b) => (b.mcap || 0) - (a.mcap || 0));

    if (validSignals.length > 0) {
      tableBody.innerHTML = validSignals.map(s => {
        // IMPROVED LOGIC: Check for "Bullish" keyword specifically
        const strategyText = s.strategy || "";
        const isBullish = strategyText.toLowerCase().includes("bullish");
        const badgeClass = isBullish ? "badge-bullish" : "badge-bearish";

        return `
        <tr>
          <td><strong>${s.ticker}</strong></td>
          <td>${fmt(s.mcap, 1)}B</td>
          <td>$${fmt(s.price, 2)}</td>
          <td>
            <span class="${badgeClass}">
              ${s.strategy}
            </span>
          </td>
          <td class="reasoning-cell" style="font-size: 0.85em; color: #666; text-align: left;">
            ${s.reasoning || "No detailed reasoning available."}
          </td>
        </tr>
      `;
      }).join("");
    } else {
      tableBody.innerHTML = `<tr><td colspan="7" style="text-align:center;">No candidates found with healthy volatility.</td></tr>`;
    }

  } catch (e) {
    console.error("Spread loading error:", e);
    if (tableBody) {
      tableBody.innerHTML = `<tr><td colspan="7">Error loading spread data.</td></tr>`;
    }
  }
})();
