// scripts/main.js

// Import the date adapter for Chart.js
import 'https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@2.0.0/dist/chartjs-adapter-date-fns.esm.js';

// Import Chart.js and register its components (resolved via your import map)
import { Chart, registerables } from 'chart.js';
Chart.register(...registerables);

// Import and register the annotation plugin
import annotationPlugin from 'https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@1.1.0/dist/chartjs-plugin-annotation.esm.js';
Chart.register(annotationPlugin);

// Import and register the zoom plugin for Chart.js
import zoomPlugin from 'https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@1.2.1/dist/chartjs-plugin-zoom.esm.js';
Chart.register(zoomPlugin);

console.log('Chart has been imported:', Chart);

/**
 * Fetch stock data from Yahoo Finance for the given symbol.
 * Returns an array of { x: Date, y: Price } objects.
 */
function fetchStockData(symbol) {
  const proxyUrl = 'https://thingproxy.freeboard.io/fetch/';
  // Request data for the last 10 years with daily data
  const targetUrl = `https://query1.finance.yahoo.com/v8/finance/chart/${symbol}?range=10y&interval=1d`;
  const url = proxyUrl + targetUrl;
  
  return fetch(url)
    .then(response => {
      if (!response.ok) {
        console.error(`Network response for ${symbol} was not ok:`, response.statusText);
        return [];
      }
      return response.json();
    })
    .then(data => {
      console.log(`Yahoo Finance API Response for ${symbol}:`, data);
      if (data.chart && data.chart.result && data.chart.result[0]) {
        const result = data.chart.result[0];
        const timestamps = result.timestamp;
        const closePrices = result.indicators.quote[0].close;
        const chartData = timestamps.map((timestamp, index) => ({
          x: new Date(timestamp * 1000),
          y: closePrices[index]
        }));
        return chartData;
      } else {
        throw new Error('Invalid data format received from Yahoo Finance');
      }
    })
    .catch(error => {
      console.error(`Error fetching stock data for ${symbol}:`, error);
      return [];
    });
}

/**
 * Fetch data for multiple symbols, compute a combined portfolio value,
 * and create a chart displaying all datasets.
 */
async function updateChart() {
  // List of stock symbols to fetch (including SPY)
  const symbols = ["GOOG", "META", "NFLX", "AMZN", "MSFT", "SPY"];
  const colors = [
    "rgb(75, 192, 192)",  // teal
    "rgb(255, 99, 132)",  // red
    "rgb(54, 162, 235)",  // blue
    "rgb(255, 206, 86)",  // yellow
    "rgb(153, 102, 255)", // purple
    "rgb(255, 159, 64)"   // orange
  ];
  
  const stockDatasets = await Promise.all(symbols.map(async (symbol, index) => {
    const stockData = await fetchStockData(symbol);
    return {
      label: `${symbol} Stock Price`,
      data: stockData,
      borderColor: colors[index % colors.length],
      fill: false,
      tension: 0.1
    };
  }));
  
  // Compute portfolio value (1 share of each)
  let portfolioData = [];
  if (stockDatasets.length > 0 && stockDatasets[0].data.length > 0) {
    const n = stockDatasets[0].data.length;
    for (let i = 0; i < n; i++) {
      const date = stockDatasets[0].data[i].x;
      let sum = 0;
      for (const ds of stockDatasets) {
        if (ds.data[i] && ds.data[i].y !== null) {
          sum += ds.data[i].y;
        }
      }
      portfolioData.push({ x: date, y: sum });
    }
  }
  
  const portfolioDataset = {
    label: "Portfolio Value (1 share each)",
    data: portfolioData,
    borderColor: "black",
    borderWidth: 3,
    fill: false,
    tension: 0.1
  };
  
  const allDatasets = [...stockDatasets, portfolioDataset];
  console.log('Creating chart with datasets:', allDatasets);

  const canvas = document.getElementById('myChart');
  if (!canvas) {
    console.error('Canvas with id "myChart" not found.');
    return;
  }
  const ctx = canvas.getContext('2d');

  const chart = new Chart(ctx, {
    type: 'line',
    data: { datasets: allDatasets },
    options: {
      maintainAspectRatio: false,
      responsive: true,
      scales: {
        x: {
          type: 'time',
          time: {
            unit: 'year',
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
          // Disable wheel and pinch zoom to force drag-only zoom
          wheel: { enabled: false },
          pinch: { enabled: false },
          // Enable drag-to-zoom on the x-axis only
          zoom: {
            drag: {
              enabled: true,
              threshold: 100, // Increase threshold to require a deliberate drag (in pixels)
              borderColor: 'rgba(225,225,225,0.3)',
              borderWidth: 1,
              backgroundColor: 'rgba(225,225,225,0.3)'
            },
            mode: 'x',
            onZoomComplete({ chart }) {
              console.log('Zoom complete', chart);
            }
          },
          pan: {
            enabled: true,
            mode: 'x'
          }
        }
      }
    }
  });

  // Create a Reset Zoom button
  const resetButton = document.createElement('button');
  resetButton.textContent = 'Reset Zoom';
  resetButton.style.marginTop = '10px';
  resetButton.onclick = () => chart.resetZoom();
  document.querySelector('.container').appendChild(resetButton);
}

window.onload = function() {
  updateChart();
};
