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

  function showError(message) {
    if (tableBody) {
      tableBody.innerHTML = `<tr><td colspan="8" style="text-align:center; color: #d9534f; padding: 20px;">${message}</td></tr>`;
    }
    console.error(message);
  }

  try {
    console.log("Starting data fetch...");
    console.log("Current page location:", window.location.href);
    
    // Try different possible paths for your data files
    const possiblePaths = [
      "../data/signals.json",
      "./data/signals.json",
      "/data/signals.json",
      "data/signals.json"
    ];
    
    let signalData = null;
    let signalPath = null;
    
    // Try each path until one works
    for (const path of possiblePaths) {
      try {
        console.log(`Trying to fetch signals from: ${path}`);
        const testRes = await fetch(path + "?v=" + Date.now(), { cache: "no-store" });
        if (testRes.ok) {
          signalPath = path;
          const text = await testRes.text();
          signalData = JSON.parse(text);
          console.log(`✓ Successfully loaded signals from: ${path}`);
          break;
        }
      } catch (e) {
        console.log(`✗ Failed to load from ${path}:`, e.message);
      }
    }
    
    if (!signalData) {
      showError("Could not find signals.json. Please check that your data files are in the correct location.");
      return;
    }

    // Update timestamp
    if (signalData.generated_at_pt) {
      const timestamp = signalData.generated_at_pt + " PT";
      document.querySelectorAll(".last-updated").forEach(el => el.textContent = timestamp);
    }

    // 2. FETCH SPREADS DATA using the same base path
    const spreadsPath = signalPath.replace("signals.json", "spreads.json");
    console.log(`Fetching spreads from: ${spreadsPath}`);
    
    const res = await fetch(spreadsPath + "?v=" + Date.now(), { cache: "no-store" });
    
    if (!res.ok) {
      showError(`Failed to load spreads.json (HTTP ${res.status}). Check that the file exists at: ${spreadsPath}`);
      return;
    }
    
    let rawSpreads = await res.json();
    console.log("Raw spreads data:", rawSpreads);
    
    if (!Array.isArray(rawSpreads) && rawSpreads.data) rawSpreads = rawSpreads.data;
    
    if (!Array.isArray(rawSpreads)) {
      showError("Spreads data is not in expected format. Expected an array.");
      console.log("Spreads data structure:", rawSpreads);
      return;
    }

    // Enrich spreads with fundamental info
    const signals = rawSpreads.map(spread => {
      const masterInfo = (signalData.all || []).find(s => s.ticker === spread.ticker);
      return masterInfo ? { ...spread, ...masterInfo } : spread;
    });

    const validSignals = signals.filter(s => !s.is_squeeze);
    validSignals.sort((a, b) => {
      if (a.is_new && !b.is_new) return -1;
      if (!a.is_new && b.is_new) return 1;
      return 0;
    });

    console.log(`Found ${validSignals.length} valid spread candidates`);

    // 3. RENDER FUNCTION
    function render(filterValue) {
      const filtered = filterValue === 'all' 
        ? validSignals 
        : validSignals.filter(s => {
            const strategyLower = (s.strategy || "").toLowerCase();
            const filterLower = filterValue.toLowerCase();
      
        // Match both "bull call" and "bullish call" or "call debit"
            if (filterLower === 'bull call') {
              return strategyLower.includes('bull') && strategyLower.includes('call') && strategyLower.includes('debit');
            }
            if (filterLower === 'bear call') {
              return strategyLower.includes('bear') && strategyLower.includes('call') && strategyLower.includes('credit');
            }
            if (filterLower === 'bear put') {
              return strategyLower.includes('bear') && strategyLower.includes('put') && strategyLower.includes('debit');
            }
            if (filterLower === 'bull put') {
              return strategyLower.includes('bull') && strategyLower.includes('put') && strategyLower.includes('credit');
            }
      
            return strategyLower.includes(filterLower);
          });

      console.log(`Rendering ${filtered.length} spreads for filter: ${filterValue}`);

    

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
    // Handle Card Clicks
    cards.forEach(card => {
      card.addEventListener('click', () => {
        const strategy = card.getAttribute('data-strategy');
        const isCurrentlySelected = card.style.border === "2px solid rgb(0, 123, 255)";
    
        console.log(`Card clicked: ${strategy}`);
    
        if (isCurrentlySelected) {
      // Unclick - deselect and show all
          card.style.border = "1px solid #ddd";
          card.style.backgroundColor = "transparent";
          if (clearBtn) clearBtn.style.display = 'none';
          render("all");
        } else {
          // Click - select this card
          cards.forEach(c => {
            c.style.border = "1px solid #ddd";
            c.style.backgroundColor = "transparent";
          });
          card.style.border = "2px solid #007bff";
          card.style.backgroundColor = "#f0f7ff";
          if (clearBtn) clearBtn.style.display = 'inline-block';
          render(strategy);
        }
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

    // Keep dropdown working as a backup
    if (filterEl) {
      filterEl.addEventListener("change", (e) => render(e.target.value));
    }

    // Initial load
    console.log("Performing initial render...");
    render("all"); 

  } catch (e) {
    showError(`Error loading data: ${e.message}`);
    console.error("Full error details:", e);
  }
})();
