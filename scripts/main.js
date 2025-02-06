// main.js

console.log('main.js loaded');

// Import dependencies from CDN
import axios from 'https://cdn.jsdelivr.net/npm/axios@0.27.2/dist/axios.min.js';
import { Chart } from 'https://cdn.jsdelivr.net/npm/chart.js@3.7.1/dist/chart.min.js';

async function fetchStockData(symbol) {
    const url = `https://query1.finance.yahoo.com/v8/finance/chart/${symbol}?range=1d&interval=1d`;
    try {
        const response = await fetch(url);
        if (!response.ok) {
            console.error('Network response was not ok', response.statusText);
            return [];
        }
        const data = await response.json();
        console.log('Yahoo Finance API Response:', data);
        if (data.chart && data.chart.result && data.chart.result[0]) {
            const stockData = data.chart.result[0];
            const timestamps = stockData.timestamp;
            const closePrices = stockData.indicators.quote[0].close;
            const chartData = timestamps.map((timestamp, index) => ({
                x: new Date(timestamp * 1000),
                y: closePrices[index]
            }));
            return chartData;
        } else {
            console.error('Invalid data format received from Yahoo Finance', data);
            return [];
        }
    } catch (error) {
        console.error('Error fetching stock data:', error);
        return [];
    }
}

async function updateChart() {
    const symbol = 'TSLA';
    let stockData = await fetchStockData(symbol);

    // If fetching data fails or returns an empty array, use static test data
    if (!stockData || stockData.length === 0) {
        console.warn('Using static test data as fallback');
        stockData = [
            { x: new Date('2025-01-01T10:00:00'), y: 650 },
            { x: new Date('2025-01-01T11:00:00'), y: 660 },
            { x: new Date('2025-01-01T12:00:00'), y: 655 },
            { x: new Date('2025-01-01T13:00:00'), y: 670 }
        ];
    }

    console.log('Creating chart with data:', stockData);

    const canvas = document.getElementById('myChart');
    if (!canvas) {
        console.error('Canvas with id "myChart" not found.');
        return;
    }
    const ctx = canvas.getContext('2d');

    // Create the chart using Chart.js
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
                        unit: 'minute',
                        tooltipFormat: 'PPpp'
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

// Optionally expose updateChart globally (if needed)
window.updateChart = updateChart;

// Call updateChart immediately.
// If your <script type="module"> is placed at the end of the body (after the canvas element),
// the DOM should already be loaded.
updateChart();
