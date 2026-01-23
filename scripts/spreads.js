(async function () {
  const tableBody = document.querySelector(".signals-table tbody");
  try {
    const res = await fetch("../data/spreads.json", { cache: "no-store" });
    const signals = await res.json();
    
    tableBody.innerHTML = signals.map(s => `
      <tr class="${s.type}">
        <td><strong>${s.ticker}</strong></td>
        <td>${s.mcap}</td>
        <td>$${s.price}</td>
        <td>${s.rsi}</td>
        <td>${s.adx}</td>
        <td><span class="badge ${s.strategy.includes('Debit') ? 'debit' : 'credit'}">${s.strategy}</span></td>
        <td>${s.is_squeeze ? '⚠️ Squeeze' : '✅ Vol OK'}</td>
      </tr>
    `).join("");
  } catch (e) {
    console.error("Failed to load spreads:", e);
  }
})();
