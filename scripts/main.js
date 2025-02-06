// scripts/main.js

// Import the date adapter for Chart.js.
import 'https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@2.0.0/dist/chartjs-adapter-date-fns.esm.js';

// Import Chart.js and register its components (resolved via your import map).
import { Chart, registerables } from 'chart.js';
Chart.register(...registerables);

// Import and register the annotation plugin (for the vertical sell-line).
import annotationPlugin from 'https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@1.1.0/dist/chartjs-plugin-annotation.esm.js';
Chart.register(annotationPlugin);

console.log('Chart has been imported:', Chart);

/**
 * Fetch stock data from Yahoo Finance for a given symbol.
 * Returns a Promise that resolves to an array of { x: Date, y: Price } objects.
 */
function fetchStockData(symbol) {
  const proxyUrl = 'https://thingproxy.freeboard.io/fetch/';
  // Request 10 years of daily data.
  const targetUrl = `https://query1.finance.yahoo.com/v8/finance/chart/${symbol}?range=10y&interval=1d`;
  const url = proxyUrl + targetUrl;
  
  return fetch(url)
    .then(response => {
      if (!response.ok) {
        console.error(`Network response for ${symbol} was not ok:`, response.statusText);
        return [];
      }
      return response.json();
    })
    .then(data => {
      console.log(`Yahoo Finance API Response for ${symbol}:`, data);
      if (data.chart && data.chart.result && data.chart.result[0]) {
        const result = data.chart.result[0];
        const timestamps = result.timestamp;
        const closePrices = result.indicators.quote[0].close;
        // Map timestamps and prices into the format { x: Date, y: Price }.
        const chartData = timestamps.map((timestamp, index) => ({
          x: new Date(timestamp * 1000),
          y: closePrices[index]
        }));
        return chartData;
      } else {
        throw new Error('Invalid data format received from Yahoo Finance');
      }
    })
    .catch(error => {
      console.error(`Error fetching stock data for ${symbol}:`, error);
      return [];
    });
}

/**
 * Update the chart's x-axis range to show the last [quantity] [unit]s.
 * The new x-axis range will be set to [currentMax - (quantity in ms), currentMax],
 * leaving the y-axis unchanged.
 * @param {Chart} chart - The Chart.js instance.
 * @param {string} unit - One of "day", "month", or "year".
 * @param {number} quantity - The number of units to subtract from the current max.
 */
function updateXAxisRange(chart, unit, quantity) {
  // Determine the current x-axis maximum. If not set, use the current date.
  const currentMaxValue = chart.options.scales.x.max
    ? new Date(chart.options.scales.x.max)
    : new Date();
  
  let newMin;
  if (unit === 'day') {
    newMin = new Date(currentMaxValue.getTime() - quantity * 24 * 60 * 60 * 1000);
  } else if (unit === 'month') {
    newMin = new Date(currentMaxValue);
    newMin.setMonth(newMin.getMonth() - quantity);
  } else if (unit === 'year') {
    newMin = new Date(currentMaxValue);
    newMin.setFullYear(newMin.getFullYear() - quantity);
  }
  
  chart.options.scales.x.min = newMin;
  chart.options.scales.x.max = currentMaxValue;
  chart.update();
}

/**
 * Fetch data for multiple symbols, compute a combined portfolio value (excluding SPY),
 * and create a chart with UI controls for updating the x-axis range.
 */
async function updateChart() {
  // Define the stock symbols (SPY is shown but excluded from the portfolio calculation).
  const symbols = ["GOOG", "META", "NFLX", "AMZN", "MSFT", "SPY"];
  const colors = [
    "rgb(75, 192, 192)",  // teal
    "rgb(255, 99, 132)",  // red
    "rgb(54, 162, 235)",  // blue
    "rgb(255, 206, 86)",  // yellow
    "rgb(153, 102, 255)", // purple
    "rgb(255, 159, 64)"   // orange
  ];
  
  // Fetch stock data concurrently for each symbol.
  const stockDatasets = await Promise.all(symbols.map(async (symbol, index) => {
    const stockData = await fetchStockData(symbol);
    return {
      label: `${symbol} Stock Price`,
      data: stockData,
      borderColor: colors[index % colors.length],
      fill: false,
      tension: 0.1
    };
  }));
  
  // Compute the portfolio value dataset by summing the prices of each stock, excluding SPY.
  let portfolioData = [];
  if (stockDatasets.length > 0 && stockDatasets[0].data.length > 0) {
    const n = stockDatasets[0].data.length;
    for (let i = 0; i < n; i++) {
      const date = stockDatasets[0].data[i].x;
      let sum = 0;
      for (const ds of stockDatasets) {
        if (ds.label === "SPY Stock Price") continue; // Skip SPY.
        if (ds.data[i] && ds.data[i].y !== null) {
          sum += ds.data[i].y;
        }
      }
      portfolioData.push({ x: date, y: sum });
    }
  }
  
  const portfolioDataset = {
    label: "Portfolio Value (1 share each, excluding SPY)",
    data: portfolioData,
    borderColor: "black",
    borderWidth: 3,
    fill: false,
    tension: 0.1
  };
  
  // Combine all datasets.
  const allDatasets = [...stockDatasets, portfolioDataset];
  console.log('Creating chart with datasets:', allDatasets);
  
  // Get the canvas element and create the chart.
  const canvas = document.getElementById('myChart');
  if (!canvas) {
    console.error('Canvas with id "myChart" not found.');
    return;
  }
  const ctx = canvas.getContext('2d');
  
  // Create the Chart.js chart without interactive zoom/pan.
  const chart = new Chart(ctx, {
    type: 'line',
    data: { datasets: allDatasets },
    options: {
      maintainAspectRatio: false,
      responsive: true,
      scales: {
        x: {
          type: 'time',
          time: {
            unit: 'year',
            tooltipFormat: 'MMM dd, yyyy'
          },
          title: { display: true, text: 'Date' }
        },
        y: {
          title: { display: true, text: 'Price (USD)' }
        }
      },
      plugins: {
        annotation: {
          annotations: {
            sellLine: {
              type: 'line',
              scaleID: 'x',
              value: '2024-12-05',
              borderColor: 'red',
              borderWidth: 2,
              label: { enabled: true, content: 'Sold Stock', position: 'start' }
            }
          }
        }
      }
    }
  });
  
  // Create UI controls for adjusting the x-axis range.
  const container = document.querySelector('.container');
  const controlDiv = document.createElement('div');
  controlDiv.innerHTML = `
    <label for="unitSelect">Show last: </label>
    <select id="unitSelect">
      <option value="day">Day(s)</option>
      <option value="month" selected>Month(s)</option>
      <option value="year">Year(s)</option>
    </select>
    <label for="quantityInput"> Quantity: </label>
    <input type="number" id="quantityInput" value="1" min="1" style="width: 50px;" />
    <button id="updateRangeButton">Update Range</button>
  `;
  container.appendChild(controlDiv);
  
  document.getElementById('updateRangeButton').addEventListener('click', () => {
    const unit = document.getElementById('unitSelect').value;
    const quantity = parseInt(document.getElementById('quantityInput').value, 10);
    updateXAxisRange(chart, unit, quantity);
  });
  
  // Create a Reset Range button.
  const resetButton = document.createElement('button');
  resetButton.textContent = 'Reset Range';
  resetButton.style.marginTop = '10px';
  resetButton.onclick = () => {
    chart.options.scales.x.min = undefined;
    chart.options.scales.x.max = undefined;
    chart.update();
  };
  container.appendChild(resetButton);
}

window.onload = function() {
  updateChart();
};
