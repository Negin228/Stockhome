// stock_filter.js

document.addEventListener('DOMContentLoaded', function() {
  document.getElementById('rsi-slider').oninput = function() {
      document.getElementById('rsi-value').innerText = this.value;
      filterStocks();
  }
  document.getElementById('pe-slider').oninput = function() {
      document.getElementById('pe-value').innerText = this.value;
      filterStocks();
  }
  document.getElementById('cap-slider').oninput = function() {
      document.getElementById('cap-value').innerText = this.value;
      filterStocks();
  }
  filterStocks(); // initial load
});

function filterStocks() {
    var rsi = parseFloat(document.getElementById('rsi-slider').value);
    var pe = parseFloat(document.getElementById('pe-slider').value);
    var cap = parseFloat(document.getElementById('cap-slider').value) * 1e9;
    var filtered = allStocks.filter(function(stock) {
        return stock.rsi >= rsi && stock.pe >= pe && stock.market_cap >= cap;
    });
    var div = document.getElementById('filtered-stocks');
    div.innerHTML = filtered.length ? "<ul>" + filtered.map(function(stock) {
        return `<li>${stock.ticker} (RSI=${stock.rsi}, P/E=${stock.pe}, Cap=${stock.market_cap})</li>`;
    }).join("") + "</ul>" : "<p>No stocks match.</p>";
}
