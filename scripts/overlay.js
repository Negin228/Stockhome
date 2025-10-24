function setupOverlayHandlers() {
  const filtersBtn = document.getElementById('filters-btn');
  const signalsBtn = document.getElementById('signals-btn');

  if (!filtersBtn || !signalsBtn) {
    console.error("filtersBtn or signalsBtn is missing from DOM!");
    return;
  }

function showFilters() {
  const buySignalsSection = document.getElementById('buy-signals');
  const sellSignalsSection = document.getElementById('sell-signals');
  const filtersContainer = document.getElementById('filters-container');

  fetch('pages/filters.html')
    .then(response => response.text())
    .then(html => {
      filtersContainer.innerHTML = html;
      filtersContainer.style.display = 'block';

      buySignalsSection.style.display = 'none';
      if (sellSignalsSection) sellSignalsSection.style.display = 'none';

      filtersBtn.classList.add('active');
      signalsBtn.classList.remove('active');
      setupSliderHandlers();

      const newSignalsBtn = document.getElementById('signals-btn');
      if (newSignalsBtn) {
        newSignalsBtn.addEventListener('click', (e) => {
          e.preventDefault();
          window.location.hash = '#signals';
          showSignals();
        });
      } else {
          console.warn("signals-btn missing after loading filters HTML");
    });
}


function showSignals() {
  const buySignalsSection = document.getElementById('buy-signals');
  const sellSignalsSection = document.getElementById('sell-signals');
  if (!buySignalsSection || !sellSignalsSection) {
    console.error("buySignalsSection or sellSignalsSection missing");
    return;
  }

  // Rebuild the signal list containers
  buySignalsSection.innerHTML = `
    <h2>Buy Signals</h2>
    <ul id="buy-list" class="signals-container"></ul>
  `;
  sellSignalsSection.innerHTML = `
    <h2>Sell Signals</h2>
    <ul id="sell-list" class="signals-container"></ul>
  `;

  const buyList = document.getElementById('buy-list');
  const sellList = document.getElementById('sell-list');
  if (!buyList || !sellList) {
    console.error("buy-list or sell-list missing after rebuild");
    return;
  }
  fetch('/data/signals.json', { cache: 'no-store' })
    .then(res => res.json())
    .then(data => {
      buyList.innerHTML = data.buys.map(renderBuyCard).join('');
      sellList.innerHTML = data.sells.map(renderSellCards).join('');
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
