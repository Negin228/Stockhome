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
      });
  }

  function showSignals() {
    buySignalsSection.innerHTML = originalBuySignalsHTML;
    signalsBtn.classList.add('active');
    filtersBtn.classList.remove('active');
    if (sellSignalsSection) sellSignalsSection.style.display = '';
    // Do NOT call setupSliderHandlers here,
    // as sliders exist only in filters view.
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
