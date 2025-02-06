// scripts/main.js

document.addEventListener("DOMContentLoaded", function () {
  if (typeof window.Chart === "undefined") {
    console.error("Chart.js is not loaded properly.");
    return;
  }

  console.log("Chart.js loaded successfully.");

  // Register necessary Chart.js components
  window.Chart.register(
    Chart.TimeScale,
    Chart.LineController,
    Chart.LineElement,
    Chart.PointElement,
    Chart.LinearScale,
    Chart.Title,
    Chart.Tooltip,
    Chart.Legend
  );

  updateChart(); // Initialize chart after ensuring Chart.js is loaded
});

/**
 * Fetch stock data from Yahoo Finance using AllOrigins proxy to bypass CORS restrictions.
 */
async function fetchStockData(symbol) {
  const proxyUrl = 'https://api.allorigins.win/raw?url=';
  const targetUrl = `https://query1.finance.yahoo.com/v8/finance/chart/${symbol}?range=10y&interval=1d`;
  const url = proxyUrl + encodeURIComponent(targetUrl);

  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`Failed to fetch ${symbol}`);

    const data = await response.json();
    console.log(`Data for ${symbol}:`, data);

    if (data.chart && data.chart.result && data.chart.result[0]) {
      const result = data.chart.result[0];
      const timestamps = result.timestamp;
      const closePrices = result.indicators.quote[0].close;

      return timestamps.map((timestamp, index) => ({
        x: new Date(timestamp * 1000),
        y: closePrices[index]
      }));
    } else {
      throw new Error(`Invalid data for ${symbol}`);
    }
  } catch (error) {
    console.error(`Error fetching ${symbol}:`, error);
    return null;
  }
}

/**
 * Creates the stock chart after fetching data.
 */
async function updateChart() {
  const symbols = ["GOOG", "META", "NFLX", "AMZN", "MSFT", "SPY"];
  const colors = ["rgb(75,192,192)", "rgb(255,99,132)", "rgb(54,162,235)", "rgb(255,206,86)", "rgb(153,102,255)", "rgb(255,159,64)"];

  const stockDatasets = await Promise.all(symbols.map(async (symbol, index) => {
    const data = await fetchStockData(symbol);
    return data ? {
      label: `${symbol} Stock Price`,
      data,
      borderColor: colors[index],
      fill: false,
      tension: 0.1
    } : null;
  }));

  const validDatasets = stockDatasets.filter(ds => ds !== null);

  if (validDatasets.length === 0) {
    document.getElementById("errorMessage").style.display = "block";
    return;
  }

  // Create the chart
  const ctx = document.getElementById('myChart').getContext('2d');
  new window.Chart(ctx, {
    type: 'line',
    data: { datasets: validDatasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { type: 'time', title: { display: true, text: 'Date' } },
        y: { title: { display: true, text: 'Price (USD)' } }
      }
    }
  });
}
