// stock_filter.js

document.addEventListener('DOMContentLoaded', function() {
  document.getElementById('rsi-slider').oninput = function() {
      document.getElementById('rsi-value').innerText = this.value;
      filterStocks();}

  document.getElementById('drop-slider').oninput = function() {
    document.getElementById('drop-value').innerText = this.value + "%";
    filterStocks();}
  
  document.getElementById('pe-slider').oninput = function() {
      document.getElementById('pe-value').innerText = this.value;
      filterStocks();}
  document.getElementById('cap-slider').oninput = function() {
      document.getElementById('cap-value').innerText = this.value;
      filterStocks();}
  filterStocks(); // initial load});

function filterStocks() {
    var rsi = parseFloat(document.getElementById('rsi-slider').value);
    var pe = parseFloat(document.getElementById('pe-slider').value);
    var cap = parseFloat(document.getElementById('cap-slider').value) * 1e9;
    var drop = parseFloat(document.getElementById('drop-slider').value);
    var filtered = allStocks.filter(function(stock) {
        var dropOk = (drop === 0) ? true : (typeof stock.pct_drop === "number" ? stock.pct_drop >= drop : false);
        return stock.rsi <= rsi && stock.pe <= pe && stock.market_cap >= cap && dropOk;});
    var div = document.getElementById('filtered-stocks');
    div.innerHTML = filtered.length ? "<ul>" + filtered.map(function(stock) {
        return `<li>${stock.ticker} (RSI=${stock.rsi_str}, P/E=${stock.pe_str}, Cap=${stock.market_cap_str}, drop=${(typeof stock.pct_drop === "number" ? stock.pct_drop.toFixed(1) + "%" : "N/A")}, DMA200=${stock.dma200_str}, DMA50=${stock.dma50_str})</li>`;
    }).join("") + "</ul>" : "<p>No stocks match.</p>";}
function resetFilters() {
    document.getElementById('cap-slider').value = 0;     // Minimum market cap
    document.getElementById('drop-slider').value = 0;
    document.getElementById('rsi-slider').value = 100;   // Or slider's max
    document.getElementById('pe-slider').value = 100;    // Or slider's max
    document.getElementById('rsi-value').innerText = 100;
    document.getElementById('pe-value').innerText = 100;
    document.getElementById('cap-value').innerText = 0;
    document.getElementById('drop-value').innerText = "0%";
    filterStocks();
}

