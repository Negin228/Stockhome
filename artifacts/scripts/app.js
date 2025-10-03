// scripts/app.js
(async function(){
  // set footer year
  document.getElementById('year').textContent = new Date().getFullYear();

  try {
    const res = await fetch('/data/signals.json', {cache: 'no-store'});
    if (!res.ok) throw new Error('Failed to load signals');
    const data = await res.json();

    // Insert timestamp
    document.getElementById('last-updated').textContent = data.generated_at_pt || '—';

    // Insert cards
    const buy = document.getElementById('buy-list');
    const sell = document.getElementById('sell-list');
    buy.innerHTML = (data.buys_html || []).join('') || '<li class="signal-card">No buy signals.</li>';
    sell.innerHTML = (data.sells_html || []).join('') || '<li class="signal-card">No sell signals.</li>';
  } catch (e) {
    console.error(e);
    document.getElementById('buy-list').innerHTML = '<li class="signal-card">Could not load signals.</li>';
    document.getElementById('sell-list').innerHTML = '';
  }
})();
