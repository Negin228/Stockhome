const buySignalsSection = document.getElementById('buy-signals');
const originalBuySignalsHTML = buySignalsSection.innerHTML;

document.getElementById('filters-btn').onclick = function(event) {
  event.preventDefault();
  fetch('pages/filters-1.html')
    .then(response => response.text())
    .then(html => {
      buySignalsSection.innerHTML = html;
    });
};

document.getElementById('signals-btn').onclick = function(event) {
  event.preventDefault();
  buySignalsSection.innerHTML = originalBuySignalsHTML;
  // (Optional) reinitialize your signals if dynamically loaded
  // Example: if (typeof loadSignals === 'function') loadSignals();
};
