// Import dependencies from CDN
import axios from 'https://cdn.jsdelivr.net/npm/axios@0.27.2/dist/axios.min.js';
import { Chart } from 'https://cdn.jsdelivr.net/npm/chart.js@3.7.1/dist/chart.min.js';

// Function to fetch stock data from Alpha Vantage API
async function fetchStockData(symbol) {
    const apiKey = 'H2QP12QUP1EQF6FD'; // Replace with your actual API key
    const url = `https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol=${symbol}&apikey=${apiKey}`;

    try {
        const response = await fetch(url);
        const data = await response.json();
        console.log('API Response:', data); // Log the entire response to the console

        if (data['Time Series (Daily)']) {
            const timeSeries = data['Time Series (Daily)'];
            const stockData = Object.keys(timeSeries).map(date => {
                return {
                    date: new Date(date), // Convert date string to a Date object
                    close: parseFloat(timeSeries[date]['4. close']) // Extract closing price
                };
            });

            return stockData.reverse(); // Reverse data for most recent date first
        } else {
            throw new Error('Invalid data format received from Alpha Vantage');
        }
    } catch (error) {
        console.error('Error fetching stock data:', error);
        throw error;
    }
}






// Function to fetch portfolio value (sum of 1 share of each stock)
async function fetchPortfolioValue(symbols) {
    const stockDataPromises = symbols.map(fetchStockData);
    const allStockData = await Promise.all(stockDataPromises);

    // Ensure all data arrays are aligned by date and sum stock values
    const portfolioData = allStockData[0].map((_, index) => {
        const date = allStockData[0][index].date;
        const totalValue = allStockData.reduce((sum, stockData) => {
            const stockPrice = stockData[index]?.close || 0; // Handle missing data
            return sum + stockPrice;
        }, 0);
        return { date, value: totalValue };
    });

    return portfolioData;
}

// Function to generate a random color for each stock line
function getRandomColor() {
    return `#${Math.floor(Math.random() * 16777215).toString(16)}`;
}

// Function to render the chart
async function renderChart(symbol) {
    // Fetch stock data
    const stockData = await fetchStockData(symbol);
    
    // Check if we have valid data
    if (stockData.length === 0) {
        console.error('No valid stock data to render.');
        return;
    }

    // Chart rendering logic
    const ctx = document.getElementById('myChart').getContext('2d');
    
    const chart = new Chart(ctx, {
        type: 'line', // Using line chart
        data: {
            datasets: [{
                label: `${symbol} Stock Price`,
                data: stockData, // Use the correctly formatted stock data
                borderColor: 'rgba(75, 192, 192, 1)',
                fill: false,
                tension: 0.1 // Optional, for smoothing the line
            }]
        },
        options: {
            scales: {
                x: {
                    type: 'time', // Ensure x-axis is a time axis
                    time: {
                        unit: 'day', // Format to daily data
                        tooltipFormat: 'll', // Display the date in the tooltip (optional)
                    },
                    title: {
                        display: true,
                        text: 'Date'
                    }
                },
                y: {
                    title: {
                        display: true,
                        text: 'Stock Price (USD)'
                    }
                }
            },
            responsive: true,
            plugins: {
                tooltip: {
                    callbacks: {
                        title: function(tooltipItems) {
                            const date = tooltipItems[0].raw.date;
                            return date.toLocaleDateString(); // Format the date for the tooltip
                        }
                    }
                }
            }
        }
    });
}


// Function to update the chart with new stock data and portfolio value
async function updateChart() {
    const symbols = ['NFLX', 'AMZN', 'TSLA', 'META', 'GOOGL', 'MSFT', 'NVDA'];
    const stockData = await Promise.all(symbols.map(fetchStockData));
    const portfolioData = await fetchPortfolioValue(symbols);

    // Prepare the chart data
    const chartData = {
        labels: stockData[0].map((data) => data.date), // x-axis labels (dates)
        datasets: [
            ...symbols.map((symbol, index) => ({
                label: symbol,
                data: stockData[index].map((data) => data.close),
                borderColor: getRandomColor(),
                fill: false,
            })),
            {
                label: 'Portfolio Value',
                data: portfolioData.map((data) => data.value),
                borderColor: '#FF0000',
                fill: false,
                borderDash: [5, 5],
            },
        ],
    };

    // Render the chart with the data
    renderChart(chartData);
}

// Function to schedule the chart update every day at 12:00 PM
function scheduleDailyUpdate() {
    const now = new Date();
    const targetTime = new Date();
    targetTime.setHours(12, 0, 0, 0); // 12:00 PM Pacific Time
    if (now > targetTime) {
        targetTime.setDate(targetTime.getDate() + 1); // Move to the next day
    }
    const timeToUpdate = targetTime - now;

    // Set the initial update and then repeat every 24 hours
    setTimeout(() => {
        updateChart();
        setInterval(updateChart, 24 * 60 * 60 * 1000); // Repeat every 24 hours
    }, timeToUpdate);
}

// Call the function to schedule the first data update
scheduleDailyUpdate();
export { updateChart };
window.updateChart = updateChart;


