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
        if (sellSignalsSection) sellSignalsSection.style.display = 'none';
        filtersBtn.classList.add('active');
        signalsBtn.classList.remove('active');

        setupSliderHandlers();

        // Re-acquire and bind the "View Today's Signals" button
        const newSignalsBtn = document.getElementById('signals-btn');
        if (newSignalsBtn) {
          newSignalsBtn.addEventListener('click', (e) => {
            e.preventDefault();
            window.location.hash = '#signals';
            showSignals();
          });
        }
      })
      .catch(err => console.error('Failed to load filters:', err));
  }

  function showSignals() {
    // always re-query DOM elements freshly
    const buySignalsSection = document.getElementById('buy-signals');
    const sellSignalsSection = document.getElementById('sell-signals');

    fetch('/data/signals.json')
      .then(res => res.json())
      .then(data => {
        const buys = data.buys;
        const buyList = buys.map(renderBuyCard).join('');
        const sellList = data.sells ? data.sells.map(renderSellCards).join('') : '';
        buySignalsSection.innerHTML = `<ul class="signal-list">${buyList}</ul>`;
        if (sellSignalsSection) {
          sellSignalsSection.innerHTML = `<ul class="signal-list">${sellList}</ul>`;
          sellSignalsSection.style.display = '';
        }
        signalsBtn.classList.add('active');
        filtersBtn.classList.remove('active');
      })
      .catch(err => console.error('Failed to reload signals:', err));
  }

  filtersBtn.addEventListener('click', (e) => {
    e.preventDefault();
    window.location.hash = '#filters';
    showFilters();
  });

  signalsBtn.addEventListener('click', (e) => {
    e.preventDefault();
    window.location.hash = '#signals';
    showSignals();
  });

  // On initial load
  if (window.location.hash === '#filters') {
    showFilters();
  } else {
    showSignals();
  }

  // Handle browser back/forward
  window.addEventListener('hashchange', () => {
    if (window.location.hash === '#filters') {
      showFilters();
    } else {
      showSignals();
    }
  });
}
