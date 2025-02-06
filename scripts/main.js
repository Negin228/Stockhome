// scripts/main.js

document.addEventListener("DOMContentLoaded", async function () {
  console.log("✅ main.js is running...");

  if (typeof Chart === "undefined") {
    console.error("❌ Chart.js failed to load.");
    return;
  }

  console.log("✅ Chart.js is available.");

  try {
    // ✅ Manually import and register the Date Adapter
    const dateAdapter = await import('https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0');
    Chart.register(dateAdapter.default);
    console.log("✅ Chart.js Date Adapter registered successfully.");
  } catch (err) {
    console.error("❌ Failed to register Chart.js Date Adapter:", err);
    return;
  }

  // ✅ Verify the Adapter is Now Registered
  if (!Chart._adapters || !Chart._adapters.date) {
    console.error("❌ Chart.js Date Adapter is still missing!");
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
