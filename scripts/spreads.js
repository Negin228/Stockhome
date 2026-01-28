(async function () {
  const tableBody = document.getElementById("spreads-body");
  const lastUpdatedEl = document.getElementById("last-updated"); // NEW: Get the time element

  try {
    // 1. Fetch your spreads.json file
    const res = await fetch("../data/spreads.json", { cache: "no-store" });
    const payload = await res.json();

    // 2. Display the timestamp from JSON
    if (payload.generated_at_pt && lastUpdatedEl) {
        // This adds the time string and the " PT" suffix you see in your other pages
        lastUpdatedEl.textContent = payload.generated_at_pt + " PT";
    }

    // 3. Extract the signals array (check if it's wrapped or a direct list)
    let signals = Array.isArray(payload) ? payload : (payload.data || payload.all || []);
    
    // Sort and Render Table
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
      tableBody.innerHTML = `<tr><td colspan="7">Error loading data.</td></tr>`;
    }
  })();
