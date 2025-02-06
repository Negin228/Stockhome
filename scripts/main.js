// scripts/main.js

document.addEventListener("DOMContentLoaded", async function () {
  console.log("✅ main.js is running...");

  if (typeof Chart === "undefined") {
    console.error("❌ Chart.js failed to load.");
    return;
  }

  console.log("✅ Chart.js is available.");

  try {
    // ✅ Manually register the Date Adapter with Chart.js
    await import("https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@2.0.0")
      .then((module) => {
        console.log("✅ Successfully loaded Chart.js Date Adapter.");
        Chart.register(module.default); // Manually register the adapter
      })
      .catch((err) => console.error("❌ Failed to load adapter:", err));
  } catch (err) {
    console.error("❌ Error importing adapter dynamically:", err);
  }

  // ✅ Verify adapter is loaded
  setTimeout(() => {
    if (!Chart._adapters || !Chart._adapters.date) {
      console.error("❌ Chart.js Date Adapter is still missing!");
      return;
    }
    console.log("✅ Chart.js Date Adapter is now ready.");

    startChart(); // Start the chart after adapter is ready
  }, 1000);
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
