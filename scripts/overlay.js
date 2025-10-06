const buySignalsSection = document.getElementById('buy-signals');
let originalBuySignalsHTML = buySignalsSection.innerHTML;

document.getElementById('filters-btn').onclick = function(event) {
    event.preventDefault();
    fetch('pages/filters.html') // or filters-1.html, matching your file
        .then(response => response.text())
        .then(html => {
            buySignalsSection.innerHTML = html;
        });
};

document.getElementById('signals-btn').onclick = function(event) {
    event.preventDefault();
    buySignalsSection.innerHTML = originalBuySignalsHTML;
    // Optionally reload signals here if needed
};
