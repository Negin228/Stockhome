(async function () {
  const tableBody = document.getElementById("spreads-body");
  const filterEl = document.getElementById("strategy-filter"); // Added

  function fmt(n, d = 1) {
    return (n == null || isNaN(n)) ? "N/A" : Number(n).toFixed(d);
  }

  try {
    // 1. FETCH TIMESTAMP (Unchanged)
    fetch("../data/signals.json", { cache: "no-store" })
      .then(res => res.json())
      .then(data => {
        if (data.generated_at_pt) {
          const timestamp = data.generated_at_pt + " PT";
          ["last-updated", "Last-updated"].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.textContent = timestamp;
          });
        }
      }).catch(err => console.warn("Could not load timestamp", err));

    // 2. FETCH AND PREPARE DATA
    const res = await fetch("../data/spreads.json", { cache: "no-store" });
    let signals = await res.json();
    if (!Array.isArray(signals) && signals.data) signals = signals.data;

    const validSignals = signals.filter(s => !s.is_squeeze);
    validSignals.sort((a, b) => (b.mcap || 0) - (a.mcap || 0));

    // 3. RENDER FUNCTION (Wrapped your existing map logic)
    function render(filterValue) {
      const filtered = filterValue === 'all' 
        ? validSignals 
        : validSignals.filter(s => s.strategy.toLowerCase().includes(filterValue));

      if (filtered.length > 0) {
        tableBody.innerHTML = filtered.map(s => {
          const strategyText = (s.strategy || "").toLowerCase();
          const isBullish = strategyText.includes("bullish") || strategyText.includes("bull");
          const badgeClass = isBullish ? "badge-bullish" : "badge-bearish";

          return `
            <tr>
              <td><strong>${s.ticker}</strong></td>
              <td>${fmt(s.mcap, 1)}B</td>
              <td>$${fmt(s.price, 2)}</td>
              <td><span class="badge ${badgeClass}">${s.strategy}</span></td>
              <td class="reasoning-cell" style="font-size: 0.85em; color: #666; text-align: left;">
                ${s.reasoning || "No detailed reasoning available."}
              </td>
            </tr>`;
        }).join("");
      } else {
        tableBody.innerHTML = `<tr><td colspan="5" style="text-align:center;">No candidates found for this filter.</td></tr>`;
      }
    }

    // 4. EVENTS
    filterEl.addEventListener("change", (e) => render(e.target.value));
    render("all"); // Initial run

  } catch (e) {
    console.error("Spread loading error:", e);
    if (tableBody) tableBody.innerHTML = `<tr><td colspan="5" style="text-align:center;">Error loading spread data.</td></tr>`;
  }
})();
