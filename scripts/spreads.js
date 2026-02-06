(async function () {
  const tableBody = document.getElementById("spreads-body");
  const filterEl = document.getElementById("strategy-filter");

  const getCheck = (isPass) => isPass 
    ? '<span style="color: #28a745; font-weight: bold;">✅</span>' 
    : '<span style="color: #6c757d;">-</span>';

  function fmt(n, d = 1) {
    return (n == null || isNaN(n)) ? "N/A" : Number(n).toFixed(d);
  }

  try {
    // 1. FETCH TIMESTAMP & MASTER DATA from signals.json
    const signalRes = await fetch("../data/signals.json", { cache: "no-store" });
    const signalData = await signalRes.json();
    
    if (signalData.generated_at_pt) {
      const el = document.getElementById("last-updated") || document.getElementById("Last-updated");
      if (el) el.textContent = signalData.generated_at_pt + " PT";
    }

    // 2. FETCH SPREADS DATA
    const res = await fetch("../data/spreads.json", { cache: "no-store" });
    let rawSpreads = await res.json();
    if (!Array.isArray(rawSpreads) && rawSpreads.data) rawSpreads = rawSpreads.data;

    // --- MINIMAL CHANGE: Enrich spreads with checks from signals.json ---
    const signals = rawSpreads.map(spread => {
      const masterInfo = (signalData.all || []).find(s => s.ticker === spread.ticker);
      return { ...spread, ...masterInfo }; // Combines strategy data with checkmark data
    });

    const validSignals = signals.filter(s => !s.is_squeeze);
    validSignals.sort((a, b) => (b.mcap || 0) - (a.mcap || 0));

    // 3. RENDER FUNCTION
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
              <td>$${fmt(s.price, 2)}</td>
              <td style="text-align:center;">${getCheck(s.pe_check)}</td>      
              <td style="text-align:center;">${getCheck(s.growth_check)}</td>  
              <td style="text-align:center;">${getCheck(s.debt_check)}</td>
              <td>${fmt(s.mcap, 1)}B</td>
              <td><span class="badge ${badgeClass}">${s.strategy}</span></td>
              <td class="reasoning-cell" style="font-size: 0.85em; color: #666; text-align: left;">
                ${s.reasoning || "No detailed reasoning available."}
              </td>
            </tr>`;
        }).join("");
      } else {
        tableBody.innerHTML = `<tr><td colspan="8" style="text-align:center;">No candidates found for this filter.</td></tr>`;
      }
    }

    // 4. EVENTS
    if (filterEl) {
        filterEl.addEventListener("change", (e) => render(e.target.value));
    }
    render("all"); 

  } catch (e) {
    console.error("Spread loading error:", e);
    if (tableBody) tableBody.innerHTML = `<tr><td colspan="8" style="text-align:center;">Error loading data.</td></tr>`;
  }
})();
