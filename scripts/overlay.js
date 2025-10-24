function setupOverlayHandlers() {
  const filtersBtn = document.getElementById('filters-btn');
  const signalsBtn = document.getElementById('signals-btn');

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
      }
    });
}


function showSignals() {
  const buyList = document.getElementById('buy-list');
  const sellList = document.getElementById('sell-list');
  const buySignalsSection = document.getElementById('buy-signals');
  const sellSignalsSection = document.getElementById('sell-signals');
  const filtersContainer = document.getElementById('filters-container');

  filtersContainer.style.display = 'none';
  buySignalsSection.style.display = '';
  if (sellSignalsSection) sellSignalsSection.style.display = '';

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
