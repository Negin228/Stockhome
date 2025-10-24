function setupOverlayHandlers() {
  const filtersBtn = document.getElementById('filters-btn');
  const signalsBtn = document.getElementById('signals-btn');

  if (!filtersBtn || !signalsBtn) {
    console.error("filtersBtn or signalsBtn is missing from DOM!");
    return;
  }

  console.log("Overlay initialized with:", {
    filtersBtn,
    signalsBtn,
    filtersContainer: document.getElementById('filters-container')
  });

  function showFilters() {
    const buySignalsSection = document.getElementById('buy-signals');
    const sellSignalsSection = document.getElementById('sell-signals');
    const filtersContainer = document.getElementById('filters-container');

    fetch('/pages/filters.html')
      .then(response => response.text())
      .then(html => {
        // Load filters
        filtersContainer.innerHTML = html;
        filtersContainer.style.display = 'block';
        if (buySignalsSection) buySignalsSection.style.display = 'none';
        if (sellSignalsSection) sellSignalsSection.style.display = 'none';

        // Update button states
        filtersBtn.classList.add('active');
        signalsBtn.classList.remove('active');

        // Create “View Today’s Signals” button dynamically
        if (!document.getElementById('signals-btn-temp')) {
          filtersContainer.insertAdjacentHTML('beforebegin', `
            <a class="btn" id="signals-btn-temp" href="#signals">View Today's Signals</a>
          `);

          const newSignalsBtn = document.getElementById('signals-btn-temp');
          newSignalsBtn.addEventListener('click', e => {
            e.preventDefault();
            window.location.hash = '#signals';
            showSignals();
          });
        }

        // Initialize slider handlers once filters are loaded
        if (typeof setupSliderHandlers === 'function') setupSliderHandlers();
      })
      .catch(err => console.error('Failed to load filters:', err));
  }

  function showSignals() {
    const buySignalsSection = document.getElementById('buy-signals');
    const sellSignalsSection = document.getElementById('sell-signals');
    const filtersContainer = document.getElementById('filters-container');

    if (!buySignalsSection || !sellSignalsSection) {
      console.error("buySignalsSection or sellSignalsSection missing");
      return;
    }

    // Hide filters when viewing signals
    filtersContainer.style.display = 'none';
    const tempBtn = document.getElementById('signals-btn-temp');
    if (tempBtn) tempBtn.remove();

    buySignalsSection.style.display = 'block';
    sellSignalsSection.style.display = 'block';

    // Update button states
    signalsBtn.classList.add('active');
    filtersBtn.classList.remove('active');

    // Create signal containers
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

    fetch('/data/signals.json', { cache: 'no-store' })
      .then(res => res.json())
      .then(data => {
        const buys = data.buys || [];
        const sells = data.sells || [];
        buyList.innerHTML = buys.length
          ? buys.map(renderBuyCard).join('')
          : '<li>No buy signals</li>';
        sellList.innerHTML = sells.length
          ? sells.map(renderSellCards).join('')
          : '<li>No sell signals</li>';
      })
      .catch(err => console.error('Failed to reload signals:', err));
  }

  // Button event listeners
  filtersBtn.addEventListener('click', e => {
    e.preventDefault();
    window.location.hash = '#filters';
    showFilters();
  });

  signalsBtn.addEventListener('click', e => {
    e.preventDefault();
    window.location.hash = '#signals';
    showSignals();
  });

  // Initial view
  if (window.location.hash === '#filters') showFilters();
  else showSignals();

  // Listen for hash changes
  window.addEventListener('hashchange', () => {
    if (window.location.hash === '#filters') showFilters();
    else showSignals();
  });
}
