// scripts/main.js

document.addEventListener("DOMContentLoaded", function () {
  console.log("✅ main.js is running...");

  if (typeof Chart === "undefined") {
    console.error("❌ Chart.js failed to load.");
    return;
  }

  console.log("✅ Chart.js is available.");

  // ✅ Manually force the adapter registration
  try {
    Chart._adapters._date = window['chartjs-adapter-date-fns'];
    console.log("✅ Chart.js Date Adapter manually registered.");
  } catch (err) {
    console.error("❌ Chart.js Date Adapter failed to register:", err);
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

  // ✅ Create a simple test dataset
  const testData = [
    { x: new Date(2024, 0, 1), y: 100 },
    { x: new Date(2024, 1, 1), y: 120 },
    { x: new Date(2024, 2, 1), y: 140 }
  ];

  // ✅ Render a simple test chart
  const ctx = document.getElementById('myChart').getContext('2d');
  new Chart(ctx, {
    type: 'line',
    data: {
      datasets: [{
        label: "Test Data",
        data: testData,
        borderColor: "rgb(75,192,192)",
        fill: false,
        tension: 0.1
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { type: 'time', title: { display: true, text: 'Date' } },
        y: { title: { display: true, text: 'Value' } }
      }
    }
  });

  console.log("✅ Chart rendered successfully.");
}
