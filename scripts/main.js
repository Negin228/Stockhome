// scripts/main.js

document.addEventListener("DOMContentLoaded", async function () {
  console.log("✅ main.js is running...");

  if (typeof Chart === "undefined") {
    console.error("❌ Chart.js failed to load.");
    return;
  }

  console.log("✅ Chart.js is available.");

  // ✅ Ensure Date Adapter is properly loaded
  let checkDateAdapter = setInterval(() => {
    if (Chart._adapters && Chart._adapters.date) {
      console.log("✅ Chart.js Date Adapter is ready.");
      clearInterval(checkDateAdapter);
      startChart();  // Start the chart only after everything is ready
    } else {
      console.warn("⏳ Waiting for Chart.js Date Adapter...");

      // 🚀 Try manually loading the adapter if it's missing
      let adapterScript = document.createElement("script");
      adapterScript.src = "https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@2.0.0";
      document.head.appendChild(adapterScript);
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
