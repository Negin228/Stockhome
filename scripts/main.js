// scripts/main.js

// Import the date adapter for Chart.js
import 'https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@2.0.0/dist/chartjs-adapter-date-fns.esm.js';

// Import Chart.js and register its components
import { Chart, registerables } from 'chart.js';
Chart.register(...registerables);

// Import and register the annotation plugin
import annotationPlugin from 'https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@1.1.0/dist/chartjs-plugin-annotation.esm.js';
Chart.register(annotationPlugin);

console.log('main.js loaded');

// Function to fetch stock data from Yahoo Finance using a proxy to avoid CORS issues
async function fetchStockData(symbol) {
  const proxyUrl = 'https://thingproxy.freeboard.io/fetch/';
  // Request data for the last 5 years with daily data
  const targetUrl = `https://query1.finance.yahoo.com/v8/finance/chart/${symbol}?range=5y&interval=1d`;
  const url = proxyUrl + targetUrl;
  
  try {
    const response = await fetch(url);
    if (!response.ok) {
      console.error('Network response was not ok', response.statusText);
      return [];
    }
    const data = await response.json();
    console.log('Yahoo Finance API Response:', data);

    if (data.chart && data.chart.result && data.chart.result[0]) {
      const result = data.chart.result[0];
      const timestamps = result.timestamp;
      const closePrices = result.indicators.quote[0].close;

      const chartData = timestamps.map((timestamp, index) => ({
        x: new Date(timestamp * 1000),
        y: closePrices[index]
      }));

      return chartData;
    } else {
      throw new Error('Invalid data format received from Yahoo Finance');
    }
  } catch (error) {
    console.error('Error fetching stock data:', error);
    return [];
  }
}

// Function to update the chart with the fetched stock data and annotation
async function updateChart() {
  const symbol = 'TSLA';
  const stockData = await fetchStockData(symbol);
  console.log('Creating chart with data:', stockData);

  const canvas = document.getElementById('myChart');
  if (!canvas) {
    console.error('Canvas with id "myChart" not found.');
    return;
  }
  const ctx = canvas.getContext('2d');

  // Create the Chart.js chart with the annotation plugin configured
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
            unit: 'month',
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
              value: '2025-01-06', // The date when you sold the stock
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
