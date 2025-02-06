// Import dependencies from CDN
import axios from 'https://cdn.jsdelivr.net/npm/axios@0.27.2/dist/axios.min.js';
import { Chart } from 'https://cdn.jsdelivr.net/npm/chart.js@3.7.1/dist/chart.min.js';

// Function to fetch stock data from Yahoo Finance
async function fetchStockData(symbol) {
    const url = `https://query1.finance.yahoo.com/v8/finance/chart/${symbol}?range=1d&interval=1d`;

    try {
        const response = await fetch(url);
        const data = await response.json();

        // Log the API response to inspect its structure
        console.log('Yahoo Finance API Response:', data);

        if (data.chart && data.chart.result) {
            const stockData = data.chart.result[0];
            const timestamps = stockData.timestamp;
            const closePrices = stockData.indicators.quote[0].close;

            // Format the data into an array of objects usable by Chart.js
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
        throw new Error('Error fetching stock data: ' + error.message);
    }
}

// Function to update the chart with the fetched stock data
async function updateChart() {
    const symbol = 'TSLA';  // Example stock symbol

    try {
        const stockData = await fetchStockData(symbol);
        console.log('Creating chart with data:', stockData);

        // Get the canvas context using the correct canvas id "myChart"
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
    } catch (error) {
        console.error('Error updating chart:', error);
    }
}

// Expose updateChart globally if needed (optional)
window.updateChart = updateChart;

// Call updateChart on page load
window.onload = function() {
    updateChart();
};
