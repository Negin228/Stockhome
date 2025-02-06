// scripts/main.js

document.addEventListener("DOMContentLoaded", function () {
  console.log("✅ main.js is running...");

  if (typeof Chart === "undefined") {
    console.error("❌ Chart.js failed to load.");
    return;
  }

  console.log("✅ Chart.js is available.");

  try {
    // ✅ Register Chart.js TimeScale and Date Adapter correctly
    Chart.register(Chart.TimeScale);

    // ✅ Ensure the adapter is loaded properly
    if (typeof window['chartjs-adapter-date-fns'] !== 'undefined') {
      console.log("✅ Chart.js Date Adapter is available.");
    } else {
      console.error("❌ Chart.js Date Adapter failed to load.");
      return;
    }
  } catch (err) {
    console.error("❌ Failed to register Chart.js Date Adapter:", err);
    return;
  }

  startChart(); // Start the chart after the adapter is ready
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
