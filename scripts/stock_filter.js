// stock_filter.js

let allStocks = [];

// Check if data was loaded from the JS file (Solution 2)
if (window.STOCK_DATA) {
    console.log("Data loaded from window.STOCK_DATA");
    processData(window.STOCK_DATA);
} 
// Fallback: Try fetching if window variable isn't found (Solution 1)
else {
    fetch('../data/signals.json')
      .then(response => {
        if (!response.ok) throw new Error("HTTP error " + response.status);
        return response.json();
      })
      .then(data => processData(data))
      .catch(err => {
          console.error("Error loading data:", err);
          document.getElementById('filtered-stocks').innerHTML = "<p>Error loading data.</p>";
      });
}

function processData(data) {
    allStocks = data.all || [];
    // Sort by Score descending (High to Low)
    allStocks.sort((a, b) => b.score - a.score);

    filterStocks();
    
    if (data.generated_at_pt) {
      const dateEl = document.getElementById("last-updated");
      if (dateEl) dateEl.textContent = data.generated_at_pt;
    }
}

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
        div.innerHTML = "<ul class='stock-list' style='padding: 0;'>" + filtered.map(function(stock) {
            // Determine badge color based on score
            let color = stock.score >= 70 ? "#4caf50" : (stock.score >= 40 ? "#ff9800" : "#f44336");
            
            // Format Drop % safely
            let dropText = (typeof stock.pct_drop === "number") ? stock.pct_drop.toFixed(1) + "%" : "0%";

            return `
            <li style="margin-bottom: 15px; padding: 20px; border: 1px solid #eee; border-radius: 8px; list-style: none; background: white; box-shadow: 0 2px 4px rgba(0,0,0,0.05);">
                
                <div style="display: flex; align-items: center; margin-bottom: 8px;">
                    <span style="background-color: ${color}; color: white; padding: 5px 10px; border-radius: 6px; font-weight: bold; margin-right: 12px; font-size: 1.1em;">
                        ${stock.score.toFixed(0)}
                    </span>
                    <strong style="font-size: 1.4em; margin-right: 10px;">${stock.ticker}</strong>
                    <span style="color: #666; font-size: 1em;">${stock.company}</span>
                </div>

                <div style="display: flex; flex-wrap: wrap; gap: 15px; font-size: 0.9em; color: #444; margin-bottom: 10px; padding-bottom: 10px; border-bottom: 1px solid #f0f0f0;">
                    <span><strong>Price:</strong> $${stock.price_str}</span>
                    <span><strong>Cap:</strong> $${stock.market_cap_str}</span>
                    <span><strong>RSI:</strong> ${stock.rsi_str}</span>
                    <span><strong>P/E:</strong> ${stock.pe_str}</span>
                    <span><strong>Drop:</strong> ${dropText}</span>
                    <span><strong>DMA50:</strong> $${stock.dma50_str}</span>
                    <span><strong>DMA200:</strong> $${stock.dma200_str}</span>
                </div>

                <div style="color: #666; font-style: italic; font-size: 0.95em;">
                    ${stock.why}
                </div>
            </li>`;
        }).join("") + "</ul>";
    } else {
        div.innerHTML = "<p style='text-align:center; margin-top: 20px; color: #666;'>No stocks match your filters.</p>";
    }
}

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
  // Initial run is handled by processData calling filterStocks
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
