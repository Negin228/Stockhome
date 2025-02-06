// scripts/main.js

// Import the date adapter for Chart.js
import 'https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@2.0.0/dist/chartjs-adapter-date-fns.esm.js';

// Import Chart.js and register its components (resolved via your import map)
import { Chart, registerables } from 'chart.js';
Chart.register(...registerables);

// Import and register the annotation plugin (for the vertical sell-line)
import annotationPlugin from 'https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@1.1.0/dist/chartjs-plugin-annotation.esm.js';
Chart.register(annotationPlugin);

console.log('Chart has been imported:', Chart);

/**
 * Fetch stock data from Yahoo Finance for a given symbol.
 * Returns a Promise that resolves to an array of { x: Date, y: Price } objects.
 */
function fetchStockData(symbol) {
  const proxyUrl = 'https://thingproxy.freeboard.io/fetch/';
  // Request data for the last 10 years with daily data
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
        // Map the timestamps and prices into a format usable by Chart.js
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
 * Custom zoom function that zooms in the x-axis by reducing its range by 10%,
 * centered on the click point.
 */
function zoomOnClick(chart, clickXPixel) {
  // Convert pixel to x-axis value.
  const xValue = chart.scales.x.getValueForPixel(clickXPixel);
  
  // Get the current x-axis range.
  const currentMin = chart.scales.x.min;
  const currentMax = chart.scales.x.max;
  const currentRange = currentMax - currentMin;
  
  // Compute the new range (reduce by 10%).
  const newRange = currentRange * 0.9;
  
  // Set new minimum and maximum so that xValue is at the center.
  const newMin = xValue - newRange / 2;
  const newMax = xValue + newRange / 2;
  
  // Update the x-axis only.
  chart.options.scales.x.min = newMin;
  chart.options.scales.x.max = newMax;
  chart.update();
}

/**
 * Fetch data for multiple symbols, compute a combined portfolio value (excluding SPY
 * from the portfolio calculation), and create a chart displaying all datasets.
 */
async function updateChart() {
  // List of stock symbols (SPY will be shown but excluded from portfolio calculation)
  const symbols = ["GOOG", "META", "NFLX", "AMZN", "MSFT", "SPY"];
  const colors = [
    "rgb(75, 192, 192)",  // teal
    "rgb(255, 99, 132)",  // red
    "rgb(54, 162, 235)",  // blue
    "rgb(255, 206, 86)",  // yellow
    "rgb(153, 102, 255)", // purple
    "rgb(255, 159, 64)"   // orange
  ];
  
  // Fetch stock data concurrently for each symbol and build datasets.
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
  
  // Compute the portfolio value dataset (exclude SPY from calculation).
  let portfolioData = [];
  if (stockDatasets.length > 0 && stockDatasets[0].data.length > 0) {
    const n = stockDatasets[0].data.length;
    for (let i = 0; i < n; i++) {
      const date = stockDatasets[0].data[i].x;
      let sum = 0;
      for (const ds of stockDatasets) {
        if (ds.label === "SPY Stock Price") continue;  // Skip SPY.
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
  
  const allDatasets = [...stockDatasets, portfolioDataset];
  console.log('Creating chart with datasets:', allDatasets);
  
  const canvas = document.getElementById('myChart');
  if (!canvas) {
    console.error('Canvas with id "myChart" not found.');
    return;
  }
  const ctx = canvas.getContext('2d');
  
  // Create the Chart.js chart without any interactive zoom/pan gestures.
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
              value: '2024-12-05', // Vertical line marking December 5, 2024.
              borderColor: 'red',
              borderWidth: 2,
              label: { enabled: true, content: 'Sold Stock', position: 'start' }
            }
          }
        }
        // No interactive zoom/pan configuration is enabled.
      }
    }
  });
  
  // Attach a click event listener to the canvas for x-axis zooming.
  canvas.addEventListener('click', (evt) => {
    const rect = canvas.getBoundingClientRect();
    const xPixel = evt.clientX - rect.left;
    zoomOnClick(chart, xPixel);
  });
  
  // Create custom zoom control buttons.
  const container = document.querySelector('.container');
  
  const resetButton = document.createElement('button');
  resetButton.textContent = 'Reset Zoom';
  resetButton.style.marginTop = '10px';
  resetButton.onclick = () => {
    chart.options.scales.x.min = undefined;
    chart.options.scales.x.max = undefined;
    chart.update();
  };
  container.appendChild(resetButton);
  
  const zoomInButton = document.createElement('button');
  zoomInButton.textContent = 'Zoom In';
  zoomInButton.style.marginTop = '10px';
  zoomInButton.onclick = () => zoomIn(chart);
  container.appendChild(zoomInButton);
  
  const zoomOutButton = document.createElement('button');
  zoomOutButton.textContent = 'Zoom Out';
  zoomOutButton.style.marginTop = '10px';
  zoomOutButton.onclick = () => zoomOut(chart);
  container.appendChild(zoomOutButton);
}

window.onload = function() {
  updateChart();
};
