// stock_filter.js

let allStocks = [];

// 1. Data Loading
if (window.STOCK_DATA) {
    processData(window.STOCK_DATA);
} else {
    fetch('../data/signals.json')
      .then(res => res.json())
      .then(data => processData(data))
      .catch(err => document.getElementById('filtered-stocks').innerHTML = "<p>Error loading data.</p>");
}

function processData(data) {
    allStocks = data.all || [];
    allStocks.sort((a, b) => b.score - a.score);
    
    const urlParams = new URLSearchParams(window.location.search);
    const targetTicker = urlParams.get('ticker');

    if (targetTicker) {
        showSpecificTicker(targetTicker);
    } else {
        filterStocks();
    }

    if (data.generated_at_pt) {
        const dateEl = document.getElementById("last-updated");
        if (dateEl) dateEl.textContent = data.generated_at_pt+ " PT";
    }
}

function showSpecificTicker(ticker) {
    resetFilters(); // Sets sliders to default ranges
    var filtered = allStocks.filter(s => s.ticker.toUpperCase() === ticker.toUpperCase());
    renderStockList(filtered);
}

// SINGLE source of truth for rendering
function renderStockList(filtered) {
    var div = document.getElementById('filtered-stocks');
    if (filtered.length) {
        div.innerHTML = "<ul class='stock-list' style='padding: 0;'>" + filtered.map(function(stock) {
            let color = stock.score >= 70 ? "#4caf50" : (stock.score >= 40 ? "#ff9800" : "#f44336");
            let dropText = (typeof stock.pct_drop === "number") ? stock.pct_drop.toFixed(1) + "%" : "0%";

            // --- NEW: Market State Classification ---
            // You can easily tweak these thresholds right here!
            let isHighVolume = (stock.rvol >= 1.2); 
            let atrPercent = (stock.price > 0) ? (stock.atr / stock.price) * 100 : 0; 
            let isHighVolatility = (atrPercent >= 2.5); // 2.5% daily average move

            let stateText = "Stable";
            let stateColor = "#4caf50";

            if (isHighVolume && isHighVolatility) {
                stateText = "Momentum";
                stateColor = "#2196F3"; // Blue
            } else if (!isHighVolume && isHighVolatility) {
                stateText = "Danger";
                stateColor = "#f44336"; // Red
            } else if (!isHighVolume && !isHighVolatility) {
                stateText = "Chop";
                stateColor = "#9e9e9e"; // Grey
            } else if (isHighVolume && !isHighVolatility) {
                stateText = "Grind"; // High volume but tight price action (accumulation)
                stateColor = "#ff9800"; // Orange
            }
            
            let stateBadge = `<span style="background-color: ${stateColor}; color: white; padding: 4px 8px; border-radius: 4px; font-size: 0.8em; margin-left: 10px; vertical-align: middle;">${stateText}</span>`;
            let volText = isHighVolume 
                ? `<span style="color: #2196F3; font-weight: bold; font-size: 0.85em;">(High Vol)</span>` 
                : `<span style="color: #9e9e9e; font-size: 0.85em;">(Low Vol)</span>`;
                
            let volatText = isHighVolatility 
                ? `<span style="color: #f44336; font-weight: bold; font-size: 0.85em;">(High Move)</span>` 
                : `<span style="color: #9e9e9e; font-size: 0.85em;">(Low Move)</span>`;

            
            return `
            <li style="margin-bottom: 15px; padding: 20px; border: 1px solid #eee; border-radius: 8px; list-style: none; background: white; box-shadow: 0 2px 4px rgba(0,0,0,0.05);">
                <div style="display: flex; align-items: center; margin-bottom: 8px;">
                    <span style="background-color: ${color}; color: white; padding: 5px 10px; border-radius: 6px; font-weight: bold; margin-right: 12px; font-size: 1.1em;">${stock.score.toFixed(0)}</span>
                    <strong style="font-size: 1.4em; margin-right: 10px; color: #000;">${stock.ticker}</strong>
                    <strong style="font-size: 1.4em; margin-right: 15px; color: #333;">$${stock.price_str}</strong>
                    <span style="color: #666; font-size: 1.1em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${stock.company}</span>
                    ${stateBadge} </div>
                <div style="display: flex; flex-wrap: wrap; gap: 15px; font-size: 0.9em; color: #444; margin-bottom: 10px; padding-bottom: 10px; border-bottom: 1px solid #f0f0f0;">
                    <span><strong>Cap:</strong> ${stock.market_cap_str}</span>
                    <span><strong>RSI:</strong> ${stock.rsi_str}</span>
                    <span><strong>P/E:</strong> ${stock.pe_str}</span>
                    <span><strong>Drop:</strong> ${dropText}</span>
                    <span><strong>DMA50:</strong> $${stock.dma50_str}</span>
                    <span><strong>DMA200:</strong> $${stock.dma200_str}</span>
                    <span><strong>RVOL:</strong> ${stock.rvol || 0}x ${volText}</span>
                    <span><strong>ATR:</strong> $${stock.atr || 0} ${volatText}</span>
                </div>
                <div style="color: #666; font-style: italic; font-size: 0.95em;"><strong>Trend Analysis:</strong> ${stock.why}</div>
            </li>`;
        }).join("") + "</ul>";
    } else {
        div.innerHTML = "<p style='text-align:center; margin-top: 20px; color: #666;'>Ticker not found / No matches.</p>";
    }
}

function filterStocks() {
    var rsi = parseFloat(document.getElementById('rsi-slider').value);
    var peInput = parseFloat(document.getElementById('pe-slider').value);
    var peLimit = (peInput >= 100) ? Infinity : peInput; 
    var cap = parseFloat(document.getElementById('cap-slider').value) * 1e9;
    var drop = parseFloat(document.getElementById('drop-slider').value);
    
    var rvolMin = parseFloat(document.getElementById('rvol-slider').value);
    var atrMin = parseFloat(document.getElementById('atr-slider').value);

    var filtered = allStocks.filter(function(stock) {
        // 1. Drop Check
        var passDrop = (drop === 0) ? true : (typeof stock.pct_drop === "number" ? stock.pct_drop >= drop : false);
        
        // 2. RSI Check (allow if missing, otherwise check)
        var passRSI = (stock.rsi == null) ? true : (stock.rsi <= rsi);
        
        // 3. P/E Check (If slider is maxed out, allow all. Otherwise, must have PE and be under limit)
        var passPE = (peLimit === Infinity) ? true : (stock.pe != null && stock.pe <= peLimit);
        
        // 4. Market Cap Check
        var passCap = (stock.market_cap == null) ? true : (stock.market_cap >= cap);
        
        // 5. RVOL & ATR Checks
        var passRVOL = (stock.rvol || 0) >= rvolMin;
        var passATR = (stock.atr || 0) >= atrMin;

        return passRSI && passPE && passCap && passDrop && passRVOL && passATR;
    });
    
    renderStockList(filtered);
}



// 3. Updated Slider Handlers
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

  // --- P/E TEXT CHANGE ---
  var peSlider = document.getElementById('pe-slider');
  if (peSlider) peSlider.oninput = function() {
    // If value is 100, show ">100", otherwise show value
    document.getElementById('pe-value').innerText = (this.value >= 100) ? ">100" : this.value;
    filterStocks();
  };

  var capSlider = document.getElementById('cap-slider');
  if (capSlider) capSlider.oninput = function() {
    document.getElementById('cap-value').innerText = this.value;
    filterStocks();
  };

  var rvolSlider = document.getElementById('rvol-slider');
  if (rvolSlider) rvolSlider.oninput = function() {
    document.getElementById('rvol-value').innerText = this.value + "x";
    filterStocks();
  };

  var atrSlider = document.getElementById('atr-slider');
  if (atrSlider) atrSlider.oninput = function() {
    document.getElementById('atr-value').innerText = "$" + this.value;
    filterStocks();
  };
}

function resetFilters() {
    document.getElementById('cap-slider').value = 0;
    document.getElementById('drop-slider').value = 0;
    document.getElementById('rsi-slider').value = 100;
    
    // Reset P/E to 100 (which now means Infinity)
    document.getElementById('pe-slider').value = 100;
    
    document.getElementById('rsi-value').innerText = 100;
    document.getElementById('pe-value').innerText = ">100"; // Reset text to >100
    document.getElementById('cap-value').innerText = 0;
    document.getElementById('drop-value').innerText = "0%";

    document.getElementById('rvol-slider').value = 0;
    document.getElementById('atr-slider').value = 0;
    document.getElementById('rvol-value').innerText = "0x";
    document.getElementById('atr-value').innerText = "$0";
    
    filterStocks();
}

setupSliderHandlers();
