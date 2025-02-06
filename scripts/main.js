async function updateChart() {
  // List of stock symbols to fetch (SPY is added)
  const symbols = ["GOOG", "META", "NFLX", "AMZN", "MSFT", "SPY"];
  
  // Colors for each individual stock dataset (6 colors now)
  const colors = [
    "rgb(75, 192, 192)",  // teal
    "rgb(255, 99, 132)",  // red
    "rgb(54, 162, 235)",  // blue
    "rgb(255, 206, 86)",  // yellow
    "rgb(153, 102, 255)", // purple
    "rgb(255, 159, 64)"   // orange
  ];
  
  // Fetch stock data concurrently for each symbol and build datasets
  const stockDatasets = await Promise.all(symbols.map(async (symbol, index) => {
    const stockData = await fetchStockData(symbol);
    return {
      label: `${symbol} Stock Price`,
      data: stockData,
      borderColor: colors[index % colors.length],
      fill: false,
      tension: 0.1 // Optional: smooths the line slightly
    };
  }));
  
  // Compute the portfolio value dataset assuming one share of each stock.
  let portfolioData = [];
  if (stockDatasets.length > 0 && stockDatasets[0].data.length > 0) {
    const n = stockDatasets[0].data.length;
    for (let i = 0; i < n; i++) {
      // Use the date from the first dataset (assumes alignment)
      const date = stockDatasets[0].data[i].x;
      // Sum the prices for each stock at index i
      let sum = 0;
      for (const ds of stockDatasets) {
        if (ds.data[i] && ds.data[i].y !== null) {
          sum += ds.data[i].y;
        }
      }
      portfolioData.push({ x: date, y: sum });
    }
  }
  
  // Create the portfolio dataset
  const portfolioDataset = {
    label: "Portfolio Value (1 share each)",
    data: portfolioData,
    borderColor: "black",
    borderWidth: 3,
    fill: false,
    tension: 0.1
  };

  // Combine all datasets (individual stocks plus the portfolio)
  const allDatasets = [...stockDatasets, portfolioDataset];
  
  console.log('Creating chart with datasets:', allDatasets);

  // Get the canvas element
  const canvas = document.getElementById('myChart');
  if (!canvas) {
    console.error('Canvas with id "myChart" not found.');
    return;
  }
  const ctx = canvas.getContext('2d');

  // Create the Chart.js chart with zoom/pan and annotation enabled
  const chart = new Chart(ctx, {
    type: 'line',
    data: {
      datasets: allDatasets
    },
    options: {
      maintainAspectRatio: false,
      responsive: true,
      scales: {
        x: {
          type: 'time',
          time: {
            unit: 'year',  // For 10-year data
            tooltipFormat: 'MMM dd, yyyy'
          },
          title: {
            display: true,
            text: 'Date'
          }
        },
        y: {
          title: {
            display: true,
            text: 'Price (USD)'
          }
        }
      },
      plugins: {
        annotation: {
          annotations: {
            sellLine: {
              type: 'line',
              scaleID: 'x',
              value: '2024-12-05', // Sell date: December 5, 2024
              borderColor: 'red',
              borderWidth: 2,
              label: {
                enabled: true,
                content: 'Sold Stock',
                position: 'start'
              }
            }
          }
        },
        zoom: {
          // Enable panning on the x-axis only.
          pan: {
            enabled: true,
            mode: 'x'
          },
          // Enable zooming by dragging and with the mouse wheel.
          zoom: {
            drag: {
              enabled: true,
              threshold: 10, // Minimum pixels the user must drag to activate zoom
              borderColor: 'rgba(225,225,225,0.3)',
              borderWidth: 1,
              backgroundColor: 'rgba(225,225,225,0.3)'
            },
            wheel: {
              enabled: true
            },
            pinch: {
              enabled: true
            },
            mode: 'x', // Zoom along the x-axis only
            onZoomComplete({chart}) {
              console.log('Zoom complete', chart);
            }
          }
        }
      }
    }
  });

  // Add a reset zoom button below the chart
  const resetButton = document.createElement('button');
  resetButton.textContent = 'Reset Zoom';
  resetButton.style.marginTop = '10px';
  resetButton.onclick = () => chart.resetZoom();
  document.querySelector('.container').appendChild(resetButton);
}

window.onload = function() {
  updateChart();
};
