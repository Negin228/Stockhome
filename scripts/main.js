// scripts/main.js

// 1. Import dependencies
import 'https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@2.0.0/dist/chartjs-adapter-date-fns.esm.js';
import { Chart, registerables } from 'chart.js';
Chart.register(...registerables);
import annotationPlugin from 'https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@1.1.0/dist/chartjs-plugin-annotation.esm.js';
Chart.register(annotationPlugin);
import zoomPlugin from 'https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@1.2.1/dist/chartjs-plugin-zoom.esm.js';
Chart.register(zoomPlugin);

console.log('Chart has been imported:', Chart);

// 2. Define fetchStockData function
function fetchStockData(symbol) {
  const proxyUrl = 'https://thingproxy.freeboard.io/fetch/';
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

// 3. Define updateChart function
async function updateChart() {
  const symbols = ["GOOG", "META", "NFLX", "AMZN", "MSFT", "SPY"];
  const colors = [
    "rgb(75, 192, 192)",
    "rgb(255, 99, 132)",
    "rgb(54, 162, 235)",
    "rgb(255, 206, 86)",
    "rgb(153, 102, 255)",
    "rgb(255, 159, 64)"
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
              value: '2024-12-05',
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
          pan: {
            enabled: true,
            mode: 'x'
          },
          zoom: {
            drag: {
              enabled: true,
              threshold: 50,
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
            mode: 'x',
            onZoomComplete({ chart }) {
              console.log('Zoom complete', chart);
            }
          }
        }
      }
    }
  });

  const resetButton = document.createElement('button');
  resetButton.textContent = 'Reset Zoom';
  resetButton.style.marginTop = '10px';
  resetButton.onclick = () => chart.resetZoom();
  document.querySelector('.container').appendChild(resetButton);
}

// 4. Call updateChart on window load
window.onload = function() {
  updateChart();
};
