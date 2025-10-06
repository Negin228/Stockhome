function setupOverlayHandlers() {
  const buySignalsSection = document.getElementById('buy-signals');
  const filtersBtn = document.getElementById('filters-btn');
  const signalsBtn = document.getElementById('signals-btn');
  let originalBuySignalsHTML = buySignalsSection.innerHTML;
  setupSliderHandlers();


  function showFilters() {
      fetch('pages/filters.html')
          .then(response => response.text())
          .then(html => {
              buySignalsSection.innerHTML = html;
              filtersBtn.classList.add('active');
              signalsBtn.classList.remove('active');
          });
  }

  function showSignals() {
      buySignalsSection.innerHTML = originalBuySignalsHTML;
      signalsBtn.classList.add('active');
      filtersBtn.classList.remove('active');
  }

  filtersBtn.onclick = function(event) {
      event.preventDefault();
      window.location.hash = '#filters';
      showFilters();
  };

  signalsBtn.onclick = function(event) {
      event.preventDefault();
      window.location.hash = '#signals';
      showSignals();
  };

  if (window.location.hash === '#filters') {
      showFilters();
  } else {
      showSignals();
  }
}
