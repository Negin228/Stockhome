// scripts/main.js

document.addEventListener("DOMContentLoaded", function () {
  console.log("✅ main.js is running...");

  if (typeof Chart === "undefined") {
    console.error("❌ Chart.js failed to load.");
    return;
  }

  console.log("✅ Chart.js is available.");

  // ✅ Check if the Date Adapter is Available
  if (typeof Chart._adapters?.date === "undefined") {
    console.error("❌ Chart.js Date Adapter failed to load. Trying to register manually...");
    
    try {
      import('https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@2.0.0')
        .then(() => {
          console.log("✅ Chart.js Date Adapter manually loaded.");
          startChart();  // Initialize chart after adapter loads
        })
        .catch(err => console.error("❌ Manual adapter import failed:", err));
      return; // Stop execution until the adapter is available
    } catch (err) {
      console.error("❌ Error importing adapter dynamically:", err);
      return;
    }
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
