// scripts/main.js

// Import the named exports from Chart.js ESM build
import { Chart, registerables } from 'https://cdn.jsdelivr.net/npm/chart.js@3.7.1/dist/chart.esm.js';

// Register all necessary Chart.js components
Chart.register(...registerables);

console.log('main.js loaded');

// Get the canvas element immediately (since the script is placed after the canvas in the HTML)
const canvas = document.getElementById('myChart');
if (!canvas) {
  console.error('Canvas with id "myChart" not found.');
} else {
  const ctx = canvas.getContext('2d');

  // Create a simple test chart with static data
  const testChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: ['January', 'February', 'March', 'April'],
      datasets: [{
        label: 'Test Data',
        data: [10, 20, 30, 40],
        borderColor: 'rgb(75, 192, 192)',
        fill: false
      }]
    },
    options: {
      responsive: true,
      scales: {
        x: {
          title: {
            display: true,
            text: 'Month'
          }
        },
        y: {
          title: {
            display: true,
            text: 'Value'
          }
        }
      }
    }
  });

  console.log("Test chart created");
}
