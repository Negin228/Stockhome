function setupOverlayHandlers() {
  const buySignalsSection = document.getElementById('buy-signals');
  const sellSignalsSection = document.getElementById('sell-signals');
  const filtersBtn = document.getElementById('filters-btn');
  const signalsBtn = document.getElementById('signals-btn');
  let originalBuySignalsHTML = buySignalsSection.innerHTML;

function showFilters() {
  fetch('pages/filters.html')
    .then(response => response.text())
    .then(html => {
      buySignalsSection.innerHTML = html;
      filtersBtn.classList.add('active');
      signalsBtn.classList.remove('active');
      if (sellSignalsSection) sellSignalsSection.style.display = 'none';
      setupSliderHandlers(); // Only called after filters HTML is injected

      // IMPORTANT: Re-acquire "view today's signals" button from DOM!
      const newSignalsBtn = document.getElementById('signals-btn');
      if (newSignalsBtn) {
        newSignalsBtn.onclick = function(event) {
          event.preventDefault();
          window.location.hash = 'signals';
          showSignals();
        };
      }
    });
}


  function showSignals() {
  // Reload data dynamically, not from originalBuySignalsHTML
  fetch('artifacts/data/signals.json')
    .then(r => r.json())
    .then(data => {
      const buys = data.buys || [];
      const html = buys.map(renderBuyCard).join('');
      buySignalsSection.innerHTML = `<ul class="signal-list">${html}</ul>`;
      signalsBtn.classList.add('active');
      filtersBtn.classList.remove('active');
      if (sellSignalsSection) sellSignalsSection.style.display = '';
    })
    .catch(err => console.error("Failed to reload signals:", err));
}


  filtersBtn.onclick = function(event) {
    event.preventDefault();
    window.location.hash = 'filters';
    showFilters();
  };

  signalsBtn.onclick = function(event) {
    event.preventDefault();
    window.location.hash = 'signals';
    showSignals();
  };

  // Handle initial view based on URL hash
  if (window.location.hash === '#filters') {
    showFilters();
  } else {
    showSignals();
  }
}
