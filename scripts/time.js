fetch('data/signals.json')
  .then(response => response.json())
  .then(data => {
    allStocks = data.all || [];
    filterStocks();
    // Set last update
    if (data.generated_at_pt) {
      document.getElementById('last-update').innerText = "Last update: " + data.generated_at_pt;
    }
  });
