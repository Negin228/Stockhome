// scripts/main.js

// Import the date adapter for Chart.js
import 'https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@2.0.0/dist/chartjs-adapter-date-fns.esm.js';

// Import Chart.js and register its components (resolved via the import map)
import { Chart, registerables } from 'chart.js';
Chart.register(...registerables);

// Import and register the annotation plugin
import annotationPlugin from 'https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@1.1.0/dist/chartjs-plugin-annotation.esm.js';
Chart.register(annotationPlugin);

console.log('main.js loaded');

/**
 * Fetch stock data from Yahoo Finance for the given symbol.
 * Returns an array of { x: Date, y: Price } objects.
 */
async function fetchStockData(symbol) {
  const proxyUrl = 'https://thingproxy.freeboard.io/fetch/';
  // Request data for the last 10 years with daily data
  const targetUrl = `https://query1.finance.yahoo.com/v8/finance/chart/${symbol}?range=10y&interval=1d`;
  const url = proxyUrl + targetUrl;
  
  try {
    const response = await fetch(url);
    if (!response.ok) {
      console.error(`Network response for ${symbol} was not ok:`, response.statusText);
      return [];
    }
    const data = await response.json();
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
  } catch (error) {
    console.error(`Error fetching stock data for ${symbol}:`, error);
    return [];
  }
}

/**
 * Fetch data for multiple symbols, compute a combined portfolio value,
 * and create a chart displaying all datasets.
 */
async function updateChart() {
  // List of stock symbols to fetch (SPY added)
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
  // This assumes that each stock dataset has the same dates and ordering.
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

  // Create the Chart.js chart with all datasets and the annotation for the sell date
  const chart = new Chart(ctx, {
    type: 'line',
    data: {
      datasets: allDatasets
    },
    options: {
      responsive: true,
      scales: {
        x: {
          type: 'time',
          time: {
            unit: 'year',  // For 10-year data, showing years might be most appropriate
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
              value: '2024-12-05', // Updated sell date: December 5, 2024
              borderColor: 'red',
              borderWidth: 2,
              label: {
                enabled: true,
                content: 'Sold Stock',
                position: 'start'
              }
            }
          }
        }
      }
    }
  });
}

window.onload = function() {
  updateChart();
};
