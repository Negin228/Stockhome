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

  /**
   * Format earnings date to human-readable format
   */
  function formatEarningsDate(dateStr) {
    if (!dateStr) return "TBA";
    try {
      const date = new Date(dateStr);
      const options = { month: 'short', day: 'numeric', year: 'numeric' };
      return date.toLocaleDateString('en-US', options);
    } catch (e) {
      return "TBA";
    }
  }

  /**
   * Calculate days until earnings date
   */
  function daysUntilEarnings(dateStr) {
    if (!dateStr) return null;
    try {
      const earningsDate = new Date(dateStr);
      const today = new Date();
      today.setHours(0, 0, 0, 0);
      earningsDate.setHours(0, 0, 0, 0);
      const diffTime = earningsDate - today;
      const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
      return diffDays;
    } catch (e) {
      return null;
    }
  }

  /**
   * Check if earnings is within 6 weeks (42 days)
   */
  function isEarningsWithin6Weeks(dateStr) {
    const days = daysUntilEarnings(dateStr);
    if (days === null) return false;
    return days >= 0 && days <= 42; // 6 weeks = 42 days
  }

  /**
   * Check if market cap is above $100B
   */
  function isMarketCapAbove100B(marketCap) {
    if (!marketCap || marketCap <= 0) return false;
    return marketCap >= 100_000_000_000; // 100 billion
  }

  function showError(message) {
    if (tableBody) {
      tableBody.innerHTML = `<tr><td colspan="9" style="text-align:center; color: #d9534f; padding: 20px;">${message}</td></tr>`;
    }
    console.error(message);
  }

  try {
    console.log("Starting data fetch...");
    
    const possiblePaths = [
      "../data/signals.json",
      "./data/signals.json",
      "/data/signals.json",
      "data/signals.json"
    ];
    
    let signalData = null;
    let signalPath = null;
    
    for (const path of possiblePaths) {
      try {
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

    if (signalData.generated_at_pt) {
      const timestamp = signalData.generated_at_pt + " PT";
      document.querySelectorAll(".last-updated").forEach(el => el.textContent = timestamp);
    }

    const spreadsPath = signalPath.replace("signals.json", "spreads.json");
    const res = await fetch(spreadsPath + "?v=" + Date.now(), { cache: "no-store" });
    
    if (!res.ok) {
      showError(`Failed to load spreads.json (HTTP ${res.status})`);
      return;
    }
    
    let rawSpreads = await res.json();
    if (!Array.isArray(rawSpreads) && rawSpreads.data) rawSpreads = rawSpreads.data;
    
    if (!Array.isArray(rawSpreads)) {
      showError("Spreads data is not in expected format.");
      return;
    }

    const signals = rawSpreads.map(spread => {
      const masterInfo = (signalData.all || []).find(s => s.ticker === spread.ticker);
      return masterInfo ? { ...spread, ...masterInfo } : spread;
    });

    const validSignals = signals.filter(s => !s.is_squeeze);
    validSignals.sort((a, b) => {
      if (a.is_new && !b.is_new) return -1;
      if (!a.is_new && b.is_new) return 1;
      return new Date(b.added_timestamp || 0) - new Date(a.added_timestamp || 0);
    });

    console.log(`Found ${validSignals.length} valid spread candidates`);

    // STATE for filters
    let currentStrategyFilter = 'all';
    let fundamentalsFilterActive = false;
    let sortByMarketCap = false;
    let earningsFilterActive = false;
    let marketCapFilterActive = false;

    // RENDER FUNCTION
    function render() {
      let filtered = validSignals;

      // Apply strategy filter
      if (currentStrategyFilter !== 'all') {
        filtered = filtered.filter(s => {
          const strategyLower = (s.strategy || "").toLowerCase();
          const filterLower = currentStrategyFilter.toLowerCase();
          
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
      }

      // Apply fundamentals filter (all 3 must pass)
      if (fundamentalsFilterActive) {
        filtered = filtered.filter(s => 
          s.pe_check === true && 
          s.growth_check === true && 
          (s.health ?? 999) < 100
        );
      }

      // Apply earnings filter
      if (earningsFilterActive) {
        filtered = filtered.filter(s => isEarningsWithin6Weeks(s.earnings_date));
      }

      // Apply market cap filter
      if (marketCapFilterActive) {
        filtered = filtered.filter(s => isMarketCapAbove100B(s.market_cap));
      }

      if (sortByMarketCap) {
        filtered = [...filtered].sort((a, b) => (b.market_cap || 0) - (a.market_cap || 0));
      }

      console.log(`Rendering ${filtered.length} spreads`);

      if (filtered.length > 0) {
        tableBody.innerHTML = filtered.map(s => {
          const strategyText = (s.strategy || "").toLowerCase();
          const isBullish = strategyText.includes("bullish") || strategyText.includes("bull");
          const badgeClass = isBullish ? "badge-bullish" : "badge-bearish";
          const company = (s.company || "").trim();
          const isMonthlyOnly = (s.monthly_available === true && s.weekly_available === false);
          const newBadge = s.is_new ? '<span style="background-color: #28a745; color: white; padding: 2px 5px; border-radius: 4px; font-size: 0.7em; margin-left: 5px; vertical-align: middle;">NEW</span>' : '';
          const earningsDateFormatted = formatEarningsDate(s.earnings_date);

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
              <td style="text-align:center; font-size:0.9em;">${earningsDateFormatted}</td>
              <td style="text-align:center;"><span class="badge ${badgeClass}">${s.strategy}</span></td>
              <td class="reasoning-cell" style="font-size: 0.85em; color: #666; text-align: left;">
                ${s.reasoning || "No detailed reasoning available."}
              </td>
            </tr>`;
        }).join("");
      } else {
        tableBody.innerHTML = `<tr><td colspan="9" style="text-align:center;">No candidates found for this filter.</td></tr>`;
      }
    }

    // STRATEGY CARDS
    const cards = document.querySelectorAll('.filter-card');
    cards.forEach(card => {
      card.addEventListener('click', () => {
        const strategy = card.getAttribute('data-strategy');
        const isCurrentlySelected = card.style.border === "2px solid rgb(0, 123, 255)";

        if (isCurrentlySelected) {
          card.style.border = "1px solid #ddd";
          card.style.backgroundColor = "transparent";
          currentStrategyFilter = 'all';
        } else {
          cards.forEach(c => {
            c.style.border = "1px solid #ddd";
            c.style.backgroundColor = "transparent";
          });
          card.style.border = "2px solid #007bff";
          card.style.backgroundColor = "#f0f7ff";
          currentStrategyFilter = strategy;
        }
        render();
      });
    });

    // FUNDAMENTALS FILTER BUTTON
    const fundamentalsBtn = document.getElementById('fundamentals-filter-btn');
    if (fundamentalsBtn) {
      fundamentalsBtn.addEventListener('click', () => {
        fundamentalsFilterActive = !fundamentalsFilterActive;
        
        if (fundamentalsFilterActive) {
          fundamentalsBtn.style.backgroundColor = '#007bff';
          fundamentalsBtn.style.color = 'white';
          fundamentalsBtn.style.border = '2px solid #0056b3';
        } else {
          fundamentalsBtn.style.backgroundColor = 'transparent';
          fundamentalsBtn.style.color = '#007bff';
          fundamentalsBtn.style.border = '2px solid #007bff';
        }
        
        render();
      });
    }

    // EARNINGS FILTER BUTTON
    const earningsBtn = document.getElementById('earnings-filter-btn');
    if (earningsBtn) {
      earningsBtn.addEventListener('click', () => {
        earningsFilterActive = !earningsFilterActive;
        
        if (earningsFilterActive) {
          earningsBtn.classList.add('active');
          earningsBtn.textContent = 'Show All Earnings';
        } else {
          earningsBtn.classList.remove('active');
          earningsBtn.textContent = 'Earnings in 6 Weeks';
        }
        
        render();
      });
    }

    // MARKET CAP FILTER BUTTON
    const marketCapBtn = document.getElementById('marketcap-filter-btn');
    if (marketCapBtn) {
      marketCapBtn.addEventListener('click', () => {
        marketCapFilterActive = !marketCapFilterActive;
        
        if (marketCapFilterActive) {
          marketCapBtn.classList.add('active');
          marketCapBtn.textContent = 'Show All Market Caps';
        } else {
          marketCapBtn.classList.remove('active');
          marketCapBtn.textContent = 'Market Cap > $100B';
        }
        
        render();
      });
    }

    // MARKET CAP SORT
    const marketCapHeader = document.querySelector('th[data-sort="mcap"]');
    if (marketCapHeader) {
      marketCapHeader.addEventListener('click', () => {
        sortByMarketCap = !sortByMarketCap;
        const arrow = marketCapHeader.querySelector('.sort-arrow');
        if (arrow) {
          if (sortByMarketCap) {
            arrow.textContent = ' ▼';
            arrow.style.color = '#007bff';  // Blue when active
          } else {
            arrow.textContent = ' ▼';
            arrow.style.color = '#999';     // Gray when inactive
          }
        }
        render();
      });
    }

    render();

  } catch (e) {
    showError(`Error loading data: ${e.message}`);
    console.error("Full error details:", e);
  }
})();
