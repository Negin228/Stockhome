(async function () {
  // Use a slight delay or check to ensure DOM is ready
  const tableBody = document.getElementById("spreads-body");
  const lastUpdatedEl = document.getElementById("last-updated");

  function fmt(n, d = 1) {
    return (n == null || isNaN(n)) ? "N/A" : Number(n).toFixed(d);
  }

  try {
    // Force the path to look back one directory since spread.html is in /pages/
    const res = await fetch("../data/spreads.json", { cache: "no-store" });
    const payload = await res.json();

    console.log("Payload loaded:", payload); // Check your browser console (F12) to see this

    if (payload.generated_at_pt) {
      if (lastUpdatedEl) {
        lastUpdatedEl.textContent = payload.generated_at_pt + " PT";
      } else {
        console.warn("Could not find element with id 'last-updated'");
      }
    }

    // Handle signals
    let signals = payload.data || payload.all || (Array.isArray(payload) ? payload : []);
    
    // ... rest of your rendering logic ...
    if (signals.length > 0) {
        tableBody.innerHTML = signals.map(s => {
            // your existing map code
        }).join("");
    }

  } catch (e) {
    console.error("Spread loading error:", e);
  }
})();
