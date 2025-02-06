// scripts/main.js

document.addEventListener("DOMContentLoaded", function () {
  console.log("✅ DOM Loaded. Initializing Chart.js...");

  if (typeof Chart === "undefined") {
    console.error("❌ Chart.js failed to load.");
    return;
  }

  console.log("✅ Chart.js is available.");

  // ✅ Ensure Date Adapter is properly loaded
  if (!Chart._adapters || !Chart._adapters.date) {
    console.error("❌ Chart.js Date Adapter failed to load.");
    return;
  }

  console.log("✅ Chart.js Date Adapter is ready.");

  // ✅ Ensure canvas exists
  const canvas = document.getElementById("myChart");
  if (!canvas) {
    console.error("❌ Canvas element 'myChart' is missing.");
    return;
  }

  // ✅ Register necessary Chart.js components
  Chart.register(
    Chart.TimeScale,
    Chart.LineController,
    Chart.LineElement,
    Chart.PointElement,
    Chart.LinearScale,
    Chart.Title,
    Chart.Tooltip,
    Chart.Legend
  );

  // ✅ Expose updateChart globally
  window.updateChart = updateChart;

  // ✅ Manually create a test chart to verify rendering
  createTestChart();

  // ✅ Fetch stock data and create the real chart
  updateChart();
});

/**
 * Manually create a test chart to ensure Chart.js is rendering.
 */
function createTestChart() {
  const testCtx = document.getElementById("myChart").getContext("2d");
  new Chart(testCtx, {
    type: "bar",
    data: {
      labels: ["Test A", "Test B", "Test C"],
      datasets: [
        {
          label: "Test Data",
          data: [10, 20, 30],
          backgroundColor: ["blue", "green", "red"]
        }
      ]
    }
  });
  console.log("✅ Test Chart rendered successfully.");
}

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
    console.log(`📊 Data for ${symbol}:`, data);

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
    console.error(`❌ Error fetching ${symbol}:`, error);
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
