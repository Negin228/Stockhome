(async function () {
  const tableBody = document.getElementById("spreads-body");
  const filterEl = document.getElementById("strategy-filter");

  const getCheck = (isPass) => isPass 
  ? `<span class="check-circle">
      <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
        <circle cx="12" cy="12" r="10" fill="#28a745"/>
        <path d="M8 12L11 15L16 9" stroke="white" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
     </span>` 
  : '<span style="color: #ccc;">-</span>';

  function fmt(n, d = 1) {
    return (n == null || isNaN(n)) ? "N/A" : Number(n).toFixed(d);
  }

  try {
    // 1. FETCH TIMESTAMP & MASTER DATA from signals.json
    // Adding a cache-buster (?v=) ensures you always see the freshest time from GitHub
    const signalRes = await fetch("../data/signals.json?v=" + Date.now(), { cache: "no-store" });
    console.log("signals.json fetch status:", signalRes.status, signalRes.url);

    const signalText = await signalRes.text();
    console.log("signals.json raw text (first 300):", signalText.slice(0, 300));


    const signalData = JSON.parse(signalText);
    console.log("signals.json payload:", signalData);
    console.log("generated_at_pt:", signalData.generated_at_pt);
    console.log("found .last-updated elements:", document.querySelectorAll(".last-updated").length);
    
    if (signalData.generated_at_pt) {
      const timestamp = signalData.generated_at_pt + " PT";
      document.querySelectorAll(".last-updated").forEach(el => el.textContent = timestamp);
    } else {
      console.warn("No generated_at_pt found in signals.json");
    }
    

    // 2. FETCH SPREADS DATA
    const res = await fetch("../data/spreads.json?v=" + Date.now(), { cache: "no-store" });
    let rawSpreads = await res.json();
    if (!Array.isArray(rawSpreads) && rawSpreads.data) rawSpreads = rawSpreads.data;

    // Enrich spreads with fundamental info (Value, Growth, Health) from signals.json
    const signals = rawSpreads.map(spread => {
      const masterInfo = (signalData.all || []).find(s => s.ticker === spread.ticker);
    // Merge but don't require masterInfo - spread already has all needed fields
      return masterInfo ? { ...spread, ...masterInfo } : spread; });

    const validSignals = signals.filter(s => !s.is_squeeze);
    validSignals.sort((a, b) => {
      if (a.is_new && !b.is_new) return -1;
      if (!a.is_new && b.is_new) return 1;
      
      return 0;
    });

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

          const company = (s.company || "").trim();
          const isMonthlyOnly = (s.monthly_available === true && s.weekly_available === false);
          const newBadge = s.is_new ? '<span style="background-color: #28a745; color: white; padding: 2px 5px; border-radius: 4px; font-size: 0.7em; margin-left: 5px; vertical-align: middle;">NEW</span>' : '';

          return `
            <tr>
              <td>
                <strong>${s.ticker}</strong> ${newBadge}
                <div style="font-size:0.85em; color:#666; margin-top:2px;">
                  ${company || "—"}
                </div>
              </td>

              <td>
                $${fmt(s.price, 0)}
                ${isMonthlyOnly ? '<sup title="Monthly options only" style="font-size:0.75em; color: red; margin-left:0px;">m</sup>' : ''}
              </td>

              <td style="text-align:center;">${getCheck(s.pe_check)}</td>
              <td style="text-align:center;">${getCheck(s.growth_check)}</td>
              <td style="text-align:center;">${getCheck((s.health ?? 999) < 100)}</td>
              <td style="text-align:center;">${s.market_cap_str}</td>

              <td style="text-align:center;"><span class="badge ${badgeClass}">${s.strategy}</span></td>

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
    const cards = document.querySelectorAll('.filter-card');
    const clearBtn = document.getElementById('clear-filter');

    // Handle Card Clicks
    cards.forEach(card => {
      card.addEventListener('click', () => {
        const strategy = card.getAttribute('data-strategy');
        
        // Visual toggle: highlight selected card
        cards.forEach(c => {
            c.style.border = "1px solid #ddd";
            c.style.backgroundColor = "transparent";
        });
        card.style.border = "2px solid #007bff";
        card.style.backgroundColor = "#f0f7ff";

        // Show the clear button
        if (clearBtn) clearBtn.style.display = 'inline-block';
        
        render(strategy); 
      });
    });

    // Handle Clear Button
    if (clearBtn) {
      clearBtn.addEventListener('click', () => {
        cards.forEach(c => {
            c.style.border = "1px solid #ddd";
            c.style.backgroundColor = "transparent";
        });
        clearBtn.style.display = 'none';
        render("all");
      });
    }

    // Keep dropdown working as a backup (Optional)
    if (filterEl) {
      filterEl.addEventListener("change", (e) => render(e.target.value));
    }

    // Initial load
    render("all"); 

  } catch (e) {
    console.error("Spread loading error:", e);
    if (tableBody) tableBody.innerHTML = `<tr><td colspan="8" style="text-align:center;">Error loading data.</td></tr>`;
  }
})(); // End of Async Function
