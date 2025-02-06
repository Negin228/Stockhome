// scripts/main.js

// Import the date adapter for Chart.js (and resolve bare specifiers via our import map)
import 'https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@2.0.0/dist/chartjs-adapter-date-fns.esm.js';

// Import the named exports from Chart.js (resolved via import map) and register components
import { Chart, registerables } from 'chart.js';
Chart.register(...registerables);

console.log('main.js loaded');

async function fetchStockData(symbol) {
  const proxyUrl = 'https://thingproxy.freeboard.io/fetch/';
  // Request data for the last 5 years with a daily interval
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
            unit: 'month',  // You can adjust the unit to 'month' for a 5-year period.
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
      }
    }
  });
}

window.onload = function() {
  updateChart();
};
