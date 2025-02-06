// Import dependencies from CDN
import axios from 'https://cdn.jsdelivr.net/npm/axios@0.27.2/dist/axios.min.js';
import { Chart } from 'https://cdn.jsdelivr.net/npm/chart.js@3.7.1/dist/chart.min.js';

// Function to fetch stock data from Yahoo Finance
async function fetchStockData(symbol) {
    const url = `https://query1.finance.yahoo.com/v8/finance/chart/${symbol}?range=1d&interval=1d`;

    try {
        const response = await fetch(url);
        const data = await response.json();

        // Log the response to check its structure
        console.log('Yahoo Finance API Response:', data);

        if (data.chart && data.chart.result) {
            const stockData = data.chart.result[0];
            const timestamps = stockData.timestamp;
            const closePrices = stockData.indicators.quote[0].close;

            // Format the data into a format usable for the chart
            const chartData = timestamps.map((timestamp, index) => ({
                x: new Date(timestamp * 1000),  // Convert timestamp to JavaScript Date
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

        // Assuming you are using Chart.js, update your chart with the new data
        const chart = new Chart(document.getElementById('stockChart').getContext('2d'), {
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

// Ensure the chart is updated when the page is loaded
window.onload = function() {
    updateChart();
};
// At the end of main.js
window.updateChart = updateChart;

