// stock_filter.js

let allStocks = [];

fetch('../data/signals.json')  // If this fails, use 'signals.json' based on previous fix
  .then(response => {
    if (!response.ok) throw new Error("HTTP error " + response.status);
    return response.json();
  })
  .then(data => {
    allStocks = data.all || [];
    
    // Sort by Score descending (High to Low) by default
    allStocks.sort((a, b) => b.score - a.score);

    filterStocks();
    if (data.generated_at_pt) {
      const dateEl = document.getElementById("last-updated");
      if (dateEl) dateEl.textContent = data.generated_at_pt;
    }
  })
  .catch(err => console.error("Error loading data:", err));

function filterStocks() {
    var rsi = parseFloat(document.getElementById('rsi-slider').value);
    var pe = parseFloat(document.getElementById('pe-slider').value);
    var cap = parseFloat(document.getElementById('cap-slider').value) * 1e9;
    var drop = parseFloat(document.getElementById('drop-slider').value);

    var filtered = allStocks.filter(function(stock) {
        var dropOk = (drop === 0) ? true : (typeof stock.pct_drop === "number" ? stock.pct_drop >= drop : false);
        return stock.rsi <= rsi && stock.pe <= pe && stock.market_cap >= cap && dropOk;
    });
  
    var div = document.getElementById('filtered-stocks');
    
    if (filtered.length) {
        div.innerHTML = "<ul class='stock-list'>" + filtered.map(function(stock) {
            // Determine color for score
            let color = stock.score >= 70 ? "#4caf50" : (stock.score >= 40 ? "#ff9800" : "#f44336");
            
            return `
            <li style="margin-bottom: 15px; padding: 15px; border: 1px solid #eee; border-radius: 8px; list-style: none;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <span style="background-color: ${color}; color: white; padding: 4px 8px; border-radius: 4px; font-weight: bold; margin-right: 10px;">
                            ${stock.score.toFixed(0)}
                        </span>
                        <strong style="font-size: 1.2em;">${stock.ticker}</strong>
                        <span style="color: #666; font-size: 0.9em; margin-left: 10px;">
                            RSI: ${stock.rsi_str} | P/E: ${stock.pe_str}
                        </span>
                    </div>
                </div>
                <div style="margin-top: 8px; color: #555; font-size: 0.95em;">
                    <em>${stock.why}</em>
                </div>
            </li>`;
        }).join("") + "</ul>";
    } else {
        div.innerHTML = "<p>No stocks match your filters.</p>";
    }
}

// ... Keep your setupSliderHandlers() and resetFilters() the same ...

function setupSliderHandlers() {
  var rsiSlider = document.getElementById('rsi-slider');
  if (rsiSlider) rsiSlider.oninput = function() {
    document.getElementById('rsi-value').innerText = this.value;
    filterStocks();
  };
  var dropSlider = document.getElementById('drop-slider');
  if (dropSlider) dropSlider.oninput = function() {
    document.getElementById('drop-value').innerText = this.value + "%";
    filterStocks();
  };
  var peSlider = document.getElementById('pe-slider');
  if (peSlider) peSlider.oninput = function() {
    document.getElementById('pe-value').innerText = this.value;
    filterStocks();
  };
  var capSlider = document.getElementById('cap-slider');
  if (capSlider) capSlider.oninput = function() {
    document.getElementById('cap-value').innerText = this.value;
    filterStocks();
  };
  filterStocks();
}

function resetFilters() {
    document.getElementById('cap-slider').value = 0;
    document.getElementById('drop-slider').value = 0;
    document.getElementById('rsi-slider').value = 100;
    document.getElementById('pe-slider').value = 100;
    document.getElementById('rsi-value').innerText = 100;
    document.getElementById('pe-value').innerText = 100;
    document.getElementById('cap-value').innerText = 0;
    document.getElementById('drop-value').innerText = "0%";
    filterStocks();
}

setupSliderHandlers();
