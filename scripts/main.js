// scripts/main.js

// Import the date adapter for Chart.js (ES module version)
import 'https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@2.0.0/dist/chartjs-adapter-date-fns.esm.js';

// Import the named exports from Chart.js ESM build and register components
import { Chart, registerables } from 'https://cdn.jsdelivr.net/npm/chart.js@3.7.1/dist/chart.esm.js';
Chart.register(...registerables);

console.log('main.js loaded');

// Function to fetch stock data from Yahoo Finance using a proxy to avoid CORS issues
async function fetchStockData(symbol) {
  // Proxy URL – using thingproxy.freeboard.io for development purposes
  const proxyUrl = 'https://thingproxy.freeboard.io/fetch/';
  const targetUrl = `https://query1.finance.yahoo.com/v8/finance/chart/${symbol}?range=1d&interval=1d`;
  const url = proxyUrl + targetUrl;
  
  try {
    const response = await fetch(url);
    if (!response.ok) {
      console.error('Network response was not ok', response.statusText);
      return [];
    }
    const data = await response.json();
    console.log('Yahoo Finance API Response:', data);

    // Ensure the response has the expected structure
    if (data.chart && data.chart.result && data.chart.result[0]) {
      const result = data.chart.result[0];
      const timestamps = result.timestamp;
      const closePrices = result.indicators.quote[0].close;

      // Map the timestamps and prices into a format usable by Chart.js
      const chartData = timestamps.map((timestamp, index) => ({
        x: new Date(timestamp * 1000), // Convert UNIX timestamp to JavaScript Date
        y: closePrices[index]
      }));

      return chartData;
    } else {
      throw new Error('Invalid data format received from Yahoo Finance');
    }
  } catch (error) {
    console.error('Error fetching stock data:', error);
    // Return an empty array on error so the chart can handle the lack of data
    return [];
  }
}

// Function to update the chart with the fetched stock data
async function updateChart() {
  const symbol = 'TSLA';  // Change symbol if needed
  const stockData = await fetchStockData(symbol);
  console.log('Creating chart with data:', stockData);

  // Get the canvas element from the DOM
  const canvas = document.getElementById('myChart');
  if (!canvas) {
    console.error('Canvas with id "myChart" not found.');
    return;
  }
  const ctx = canvas.getContext('2d');

  // Create the Chart.js chart
  const chart = new Chart(ctx, {
    type: 'line',
    data: {
      datasets: [{
        label: `${symbol} Stock Price`,
        data: stockData,
        borderColor: 'rgb(75, 192, 192)',
        fill: false
      }]
    },
    options: {
      responsive: true,
      scales: {
        x: {
          type: 'time',
          time: {
            unit: 'minute', // Adjust as needed (minute, hour, etc.)
            tooltipFormat: 'll HH:mm'
          },
          title: {
            display: true,
            text: 'Time'
          }
        },
        y: {
          title: {
            display: true,
            text: 'Price (USD)'
          }
        }
      }
    }
  });
}

// When the window loads, update the chart
window.onload = function() {
  updateChart();
};
