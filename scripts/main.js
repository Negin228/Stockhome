// Import dependencies from CDN
import axios from 'https://cdn.jsdelivr.net/npm/axios@0.27.2/dist/axios.min.js';
import { Chart } from 'https://cdn.jsdelivr.net/npm/chart.js@3.7.1/dist/chart.min.js';

// Function to fetch stock data from Yahoo Finance
async function fetchStockData(symbol) {
    const url = `https://query1.finance.yahoo.com/v8/finance/chart/${symbol}?range=1d&interval=1d`;
    
    try {
        const response = await fetch(url);
        const data = await response.json();
        
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

// Function to fetch portfolio value (sum of 1 share of each stock)
async function fetchPortfolioValue(symbols) {
    const stockDataPromises = symbols.map(fetchStockData);
    const allStockData = await Promise.all(stockDataPromises);

    // Ensure all data arrays are aligned by date and sum stock values
    const portfolioData = allStockData[0].map((_, index) => {
        const date = allStockData[0][index].x; // Using 'x' for the date
        const totalValue = allStockData.reduce((sum, stockData) => {
            const stockPrice = stockData[index]?.y || 0; // Handle missing data
            return sum + stockPrice;
        }, 0);
        return { date, value: totalValue };
    });

    return portfolioData;
}

// Function to render the chart with multiple stocks and portfolio value
async function renderChart(symbols) {
    const stockData = await Promise.all(symbols.map(fetchStockData));
    const portfolioData = await fetchPortfolioValue(symbols);

    // Prepare the chart data
    const chartData = {
        labels: stockData[0].map((data) => data.x), // x-axis labels (dates)
        datasets: [
            ...symbols.map((symbol, index) => ({
                label: `${symbol} Stock Price`,
                data: stockData[index].map((data) => data.y),
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

    // Assuming you are using Chart.js, update your chart with the new data
    const ctx = document.getElementById('stockChart').getContext('2d');
    const chart = new Chart(ctx, {
        type: 'line',
        data: chartData,
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
        renderChart(['NFLX', 'AMZN', 'TSLA', 'META', 'GOOGL', 'MSFT', 'NVDA']);
        setInterval(() => renderChart(['NFLX', 'AMZN', 'TSLA', 'META', 'GOOGL', 'MSFT', 'NVDA']), 24 * 60 * 60 * 1000); // Repeat every 24 hours
    }, timeToUpdate);
}

// Call the function to schedule the first data update
scheduleDailyUpdate();

// Function to generate a random color for each stock line
function getRandomColor() {
    return `#${Math.floor(Math.random() * 16777215).toString(16)}`;
}
