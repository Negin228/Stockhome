function setupOverlayHandlers() {
  const filtersBtn = document.getElementById('filters-btn');
  const signalsBtn = document.getElementById('signals-btn');

  function showFilters() {
    const buySignalsSection = document.getElementById('buy-signals');
    const sellSignalsSection = document.getElementById('sell-signals');
    fetch('pages/filters.html')
      .then(response => response.text())
      .then(html => {
        buySignalsSection.innerHTML = html;
        filtersBtn.classList.add('active');
        signalsBtn.classList.remove('active');
        if (sellSignalsSection) sellSignalsSection.style.display = 'none';

        setupSliderHandlers();

        const newSignalsBtn = document.getElementById('signals-btn');
        if (newSignalsBtn) {
          newSignalsBtn.onclick = function (event) {
            event.preventDefault();
            window.location.hash = 'signals';
            showSignals();
          };
        }
      })
      .catch(err => console.error('Failed to load filters:', err));
  }

  function showSignals() {
    const buySignalsSection = document.getElementById('buy-signals');
    const sellSignalsSection = document.getElementById('sell-signals');
    fetch('artifacts/data/signals.json')
      .then(r => r.json())
      .then(data => {
        const buys = data.buys;
        const html = buys.map(renderBuyCard).join('');
        buySignalsSection.innerHTML = `<ul class="signal-list">${html}</ul>`;
        signalsBtn.classList.add('active');
        filtersBtn.classList.remove('active');
        if (sellSignalsSection) sellSignalsSection.style.display = '';
      })
      .catch(err => console.error('Failed to reload signals:', err));
  }

  filtersBtn.onclick = function (event) {
    event.preventDefault();
    window.location.hash = 'filters';
    showFilters();
  };

  signalsBtn.onclick = function (event) {
    event.preventDefault();
    window.location.hash = 'signals';
    showSignals();
  };

  if (window.location.hash === '#filters') {
    showFilters();
  } else {
    showSignals();
  }

  window.addEventListener('hashchange', () => {
    if (window.location.hash === '#filters') {
      showFilters();
    } else if (window.location.hash === '#signals' || window.location.hash === '') {
      showSignals();
    }
  });
}
