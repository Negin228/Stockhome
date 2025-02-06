// scripts/main.js

// Import the date adapter for Chart.js
import 'https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@2.0.0/dist/chartjs-adapter-date-fns.esm.js';

// Import Chart.js and register its components (resolved via the import map)
import { Chart, registerables } from 'chart.js';
Chart.register(...registerables);

// Import and register the annotation plugin
import annotationPlugin from 'https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@1.1.0/dist/chartjs-plugin-annotation.esm.js';
Chart.register(annotationPlugin);

// Import and register the zoom plugin for Chart.js
import zoomPlugin from 'https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@1.2.1/dist/chartjs-plugin-zoom.esm.js';
Chart.register(zoomPlugin);

console.log('main.js loaded');

/**
 * Fetch stock data from Yahoo Finance for the given symbol.
 * Returns an array of { x: Date, y: Price } objects.
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
 * Fetch data for multiple symbols, compute a combined portfolio value,
 * and create a chart displaying all datasets.
 */
async function updateChart() {
  // List of stock symbols to fetch (SPY is added)
  const symbols = ["GOOG", "META", "NFLX", "AMZN", "MSFT", "SPY"];
  
  // Colors for each individual stock dataset (6 colors now)
  const colors = [
    "rgb(75, 192, 192)",  // teal
    "rgb(255, 99, 132)",  // red
    "rgb(54, 162, 235)",  // blue
    "rgb(255, 206, 86)",  // yellow
    "rgb(153, 102, 255)", // purple
    "rgb(255, 159, 64)"   // orange
  ];
  
  // Fetch stock data concurrently for each symbol and build datasets
  const stockDatasets = await Promise.all(symbols.map(async (symbol, index) => {
    const stockData = await fetchStockData(symbol);
    return {
      label: `${symbol} Stock Price`,
      data: stockData,
      borderColor: colors[index % colors.length],
      fill: false,
      tension: 0.1 // Optional: smooths the line slightly
    };
  }));
  
  // Compute the portfolio value dataset assuming one share of each stock.
  let portfolioData = [];
  if (stockDatasets.length > 0 && stockDatasets[0].data.length > 0) {
    const n = stockDatasets[0].data.length;
    for (let i = 0; i < n; i++) {
      // Use the date from the first dataset (assumes alignment)
      const date = stockDatasets[0].data[i].x;
      // Sum the prices for each stock at index i
      let sum = 0;
      for (const ds of stockDatasets) {
        if (ds.data[i] && ds.data[i].y !== null) {
          sum += ds.data[i].y;
        }
      }
      portfolioData.push({ x: date, y: sum });
    }
  }
  
  // Create the portfolio dataset
  const portfolioDataset = {
    label: "Portfolio Value (1 share each)",
    data: portfolioData,
    borderColor: "black",
    borderWidth: 3,
    fill: false,
    tension: 0.1
  };

  // Combine all datasets (individual stocks plus the portfolio)
  const allDatasets = [...stockDatasets, portfolioDataset];
  
  console.log('Creating chart with datasets:', allDatasets);

  // Get the canvas element
  const canvas = document.getElementById('myChart');
  if (!canvas) {
    console.error('Canvas with id "myChart" not found.');
    return;
  }
  const ctx = canvas.getContext('2d');

  // Create the Chart.js chart with zoom/pan and annotation enabled
  const chart = new Chart(ctx, {
    type: 'line',
    data: {
      datasets: allDatasets
    },
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
          title: {
            display: true,
            text: 'Date'
          }
        },
        y: {
          title: {
            display: true,
            text: 'Price (USD)'
          }
        }
      },
      plugins: {
        annotation: {
          annotations: {
            sellLine: {
              type: 'line',
              scaleID: 'x',
              value: '2024-12-05', // Sell date: December 5, 2024
              borderColor: 'red',
              borderWidth: 2,
              label: {
                enabled: true,
                content: 'Sold Stock',
                position: 'start'
              }
            }
          }
        },
        zoom: {
          pan: {
            enabled: true,
            mode: 'x'
          },
          zoom: {
            drag: {
              enabled: true,
              threshold: 10,
              borderColor: 'rgba(225,225,225,0.3)',
              borderWidth: 1,
              backgroundColor: 'rgba(225,225,225,0.3)'
            },
            wheel: {
              enabled: true
            },
            pinch: {
              enabled: true
            },
            mode: 'x',
            onZoomComplete({ chart }) {
              console.log('Zoom complete', chart);
            }
          }
        }
      }
    }
  });

  // Add a reset zoom button below the chart
  const resetButton = document.createElement('button');
  resetButton.textContent = 'Reset Zoom';
  resetButton.style.marginTop = '10px';
  resetButton.onclick = () => chart.resetZoom();
  document.querySelector('.container').appendChild(resetButton);
}

window.onload = function() {
  updateChart();
};
