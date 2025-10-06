const buySignalsSection = document.getElementById('buy-signals');
const filtersBtn = document.getElementById('filters-btn');
const signalsBtn = document.getElementById('signals-btn');
let originalBuySignalsHTML = buySignalsSection.innerHTML;

filtersBtn.onclick = function(event) {
    event.preventDefault();
    fetch('pages/filters.html')
      .then(response => response.text())
      .then(html => {
          buySignalsSection.innerHTML = html;
          filtersBtn.classList.add('active');
          signalsBtn.classList.remove('active');
      });
};

signalsBtn.onclick = function(event) {
    event.preventDefault();
    buySignalsSection.innerHTML = originalBuySignalsHTML;
    signalsBtn.classList.add('active');
    filtersBtn.classList.remove('active');
    // Optionally reload signals here if needed
};
