// scripts/main.js

document.addEventListener("DOMContentLoaded", async function () {
  console.log("✅ main.js is running...");

  if (typeof Chart === "undefined") {
    console.error("❌ Chart.js failed to load.");
    return;
  }

  console.log("✅ Chart.js is available.");

  // ✅ Wait for Date Adapter to Load
  let checkDateAdapter = setInterval(() => {
    if (Chart._adapters && Chart._adapters.date) {
      console.log("✅ Chart.js Date Adapter is ready.");
      clearInterval(checkDateAdapter);
      startChart();  // Start the chart only after everything is ready
    } else {
      console.warn("⏳ Waiting for Chart.js Date Adapter...");
    }
  }, 500);
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
    Chart.TimeScale,
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
