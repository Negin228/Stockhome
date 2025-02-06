// scripts/main.js

document.addEventListener("DOMContentLoaded", function () {
  console.log("✅ main.js is running...");

  if (typeof Chart === "undefined") {
    console.error("❌ Chart.js failed to load.");
    return;
  }

  console.log("✅ Chart.js is available.");

  // ✅ Register Chart.js TimeScale
  Chart.register(Chart.TimeScale);

  // ✅ Ensure the adapter is available before proceeding
  if (!Chart._adapters?.date) {
    console.error("❌ Chart.js Date Adapter failed to load.");
    return;
  }

  console.log("✅ Chart.js Date Adapter is now ready.");
  startChart(); // Start the chart after adapter is ready
});

/**
 * Function to initialize the chart after everything has loaded.
 */
function startChart() {
  console.log("🚀 Initializing Chart...");

  // ✅ Ensure canvas exists
  const canvas = document.getElementById("myChart");
  if (!canvas) {
    console.error("❌ Canvas element 'myChart' is missing.");
    return;
  }

  // ✅ Register necessary Chart.js components
  Chart.register(
    Chart.LineController,
    Chart.LineElement,
    Chart.PointElement,
    Chart.LinearScale,
    Chart.Title,
    Chart.Tooltip,
    Chart.Legend
  );

  // ✅ Attach updateChart to window so it can be called from the console
  window.updateChart = updateChart;

  // ✅ Fetch stock data and create the real chart
  console.log("🔄 Fetching stock data on page load...");
  updateChart();
}

/**
 * Fetch stock data from Yahoo Finance using AllOrigins proxy to bypass CORS restrictions.
 */
async function fetchStockData(symbol) {
  console.log(`🔄 Fetching stock data for: ${symbol}...`);

  const proxyUrl = 'https://api.allorigins.win/raw?url=';
  const targetUrl = `https://query1.finance.yahoo.com/v8/finance/chart/${symbol}?range=10y&interval=1d`;
  const url = proxyUrl + encodeURIComponent(targetUrl);

  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`❌ Failed to fetch data for ${symbol} (HTTP ${response.status})`);

    const data = await response.json();
    console.log(`📊 Raw API Response for ${symbol}:`, data);

    if (!data.chart || !data.chart.result || !data.chart.result[0]) {
      console.error(`❌ Invalid data format received for ${symbol}:`, data);
      return null;
    }

    const result = data.chart.result[0];
    const timestamps = result.timestamp;
    const closePrices = result.indicators?.quote?.[0]?.close;

    if (!timestamps || !closePrices) {
      console.error(`❌ Missing timestamps or price data for ${symbol}`);
      return null;
    }

    return timestamps.map((timestamp, index) => ({
      x: new Date(timestamp * 1000),
      y: closePrices[index] ?? null
    })).filter(point => point.y !== null);

  } catch (error) {
    console.error(`❌ API request error for ${symbol}:`, error);
    return null;
  }
}

/**
 * Creates the stock chart after fetching data.
 */
async function updateChart() {
  console.log("🔄 Running updateChart()...");
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
    console.error("❌ No valid stock data available.");
    return;
  }

  // Create the chart
  const ctx = document.getElementById('myChart').getContext('2d');
  new Chart(ctx, {
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

  console.log("✅ Stock Chart rendered successfully.");
}
