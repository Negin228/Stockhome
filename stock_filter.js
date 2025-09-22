// stock_filter.js

document.addEventListener('DOMContentLoaded', function() {
  
  document.getElementById('rsi-slider').oninput = function() {
      document.getElementById('rsi-value').innerText = this.value;
      filterStocks();
  }

  document.getElementById('change-slider').oninput = function() {
    document.getElementById('change-value').innerText = this.value + "%";
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
    var change = parseFloat(document.getElementById('change-slider').value);

    var filtered = allStocks.filter(function(stock) {
        var changeOk = (change === 0) ? true : (typeof stock.pct_drop === "number" ? stock.pct_drop <= -change : false);
        return stock.rsi >= rsi && stock.pe >= pe && stock.market_cap >= cap && changeOk;
    });
    var div = document.getElementById('filtered-stocks');
    div.innerHTML = filtered.length ? "<ul>" + filtered.map(function(stock) {
        return `<li>${stock.ticker} (RSI=${stock.rsi_str}, P/E=${stock.pe_str}, Cap=${stock.market_cap_str}, Change=${(typeof stock.pct_drop === "number" ? stock.pct_drop.toFixed(1) + "%" : "N/A")})</li>`;
    }).join("") + "</ul>" : "<p>No stocks match.</p>";
}

function resetFilters() {
    document.getElementById('rsi-slider').value = 0;
    document.getElementById('pe-slider').value = 0;
    document.getElementById('cap-slider').value = 0;
    document.getElementById('rsi-value').innerText = 0;
    document.getElementById('pe-value').innerText = 0;
    document.getElementById('cap-value').innerText = 0;
    document.getElementById('change-slider').value = 0;
    document.getElementById('change-value').innerText = "0%";

    filterStocks();
}

