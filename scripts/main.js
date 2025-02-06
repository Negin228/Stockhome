// scripts/main.js

// Import the date adapter for Chart.js
import 'https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@2.0.0/dist/chartjs-adapter-date-fns.esm.js';

// Import Chart.js and register its components (resolved via your import map)
import { Chart, registerables } from 'chart.js';
Chart.register(...registerables);

// Import and register the annotation plugin (for the vertical sell-line)
import annotationPlugin from 'https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@1.1.0/dist/chartjs-plugin-annotation.esm.js';
Chart.register(annotationPlugin);

console.log('Chart has been imported:', Chart);

/**
 * Fetch stock data from Yahoo Finance for a given symbol.
 * Returns a Promise that resolves to an array of { x: Date, y: Price } objects.
 */
function fetchStockData(symbol) {
  const proxyUrl = 'https://thingproxy.freeboard.io/fetch/';
  // Request data for the last 10 years with daily data.
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
        // Map the timestamps and prices into a format usable by Chart.js.
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
 * Zooms in the x‑axis by reducing its range by 10%,
 * centering on the x‑axis value corresponding to the given pixel.
 */
function zoomInOnClick(chart, clickXPixel) {
  // Convert pixel to x-axis value.
  const xValue = chart.scales.x.getValueForPixel(clickXPixel);
  const currentMin = chart.scales.x.min;
  const currentMax = chart.scales.x.max;
  const currentRange = currentMax - currentMin;
  const newRange = currentRange * 0.9; // reduce range by 10%
  const newMin = xValue - newRange / 2;
  const newMax = xValue + newRange / 2;
  chart.options.scales.x.min = newMin;
  chart.options.scales.x.max = newMax;
  chart.update();
}

/**
 * Zooms out the x‑axis by increasing its range by about 11%
 * (the reverse of a 10% zoom in),
 * centering on the x‑axis value corresponding to the given pixel.
 */
function zoomOutOnClick(chart, clickXPixel) {
  const xValue = chart.scales.x.getValueForPixel(clickXPixel);
  const currentMin = chart.scales.x.min;
  const currentMax = chart.scales.x.max;
  const currentRange = currentMax - currentMin;
  const newRange = currentRange / 0.9; // increase range (reverse of 10% reduction)
  const newMin = xValue - newRange / 2;
  const newMax = xValue + newRange / 2;
  chart.options.scales.x.min = newMin;
  chart.options.scales.x.max = newMax;
  chart.update();
}

/**
 * Fetches data for multiple symbols
