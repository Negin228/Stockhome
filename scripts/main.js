// Import dependencies from CDN
import axios from 'https://cdn.jsdelivr.net/npm/axios@0.27.2/dist/axios.min.js';
import { Chart } from 'https://cdn.jsdelivr.net/npm/chart.js@3.7.1/dist/chart.min.js';

// Function to fetch stock data from Alpha Vantage API
async function fetchStockData(symbol) {
    const apiKey = 'H2QP12QUP1EQF6FD'; // Replace with your Alpha Vantage API key
    const url = `https://www.alphavantage.co/query?function=TIME_SERIES_DAILY_ADJUSTED&symbol=${symbol}&apikey=${apiKey}`;
    console.log(`Fetching data for ${symbol}`);

    try {
        const response = await axios.get(url);
        if (response.data && response.data['Time Series (Daily)']) {
            const dailyData = response.data['Time Series (Daily)'];
            // Format the data into an array of date/price pairs
            const formattedData = Object.entries(dailyData).map(([date, values]) => ({
                date,
                close: parseFloat(values['4. close']), // Closing price
            }));
            return formattedData.reverse(); // Reverse for chronological order
        } else {
            throw new Error('Invalid data format received from Alpha Vantage');
        }
    } catch (error) {
        console.error('Error fetching stock data:', error);
        return [];
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
function renderChart(data) {
    const ctx = document.getElementById('myChart').getContext('2d');
    new Chart(ctx, {
        type: 'line',
        data,
        options: {
            responsive: true,
            scales: {
                x: {
                    type: 'time',
                    time: { unit: 'day' },
                },
                y: {
                    beginAtZero: true,
                },
            },
        },
    });
}

// Function to update the chart with new stock data and portfolio value
export async function updateChart() {
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


