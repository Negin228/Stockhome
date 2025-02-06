// scripts/main.js

// Import Chart.js named exports and register the components
import { Chart, registerables } from 'https://cdn.jsdelivr.net/npm/chart.js@3.7.1/dist/chart.esm.js';
Chart.register(...registerables);

console.log('main.js loaded');

// Function to fetch stock data from Yahoo Finance
async function fetchStockData(symbol) {
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${symbol}?range=1d&interval=1d`;
  try {
    const response = await fetch(url);
    const data = await response.json();
    console.log('Yahoo Finance API Response:', data);

    // Verify that data is in the expected format
    if (data.chart && data.chart.result && data.chart.result[0]) {
      const result = data.chart.result[0];
      const timestamps = result.timestamp;
      const closePrices = result.indicators.quote[0].close;

      // Format the data: each point is an object with an x (date) and y (price) property
      const chartData = timestamps.map((timestamp, index) => ({
        x: new Date(timestamp * 1000), // Convert timestamp to JavaScript Date
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

// Function to update (or create) the chart with the fetched stock data
async function updateChart() {
  const symbol = 'TSLA';  // Change this to another symbol if needed
  const stockData = await fetchStockData(symbol);
  console.log('Creating chart with data:', stockData);

  // Get the canvas element by its ID (ensure it matches your HTML)
  const canvas = document.getElementById('myChart');
  if (!canvas) {
    console.error('Canvas with id "myChart" not found.');
    return;
  }
  const ctx = canvas.getContext('2d');

  // Create the Chart.js chart with the fetched stock data
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
            unit: 'minute',      // Adjust the unit as needed (e.g., 'minute', 'hour')
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
