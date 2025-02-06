async function fetchStockData(symbol) {
  console.log(`🔄 Fetching stock data for: ${symbol}...`);

  const proxyUrl = 'https://api.allorigins.win/raw?url=';
  const targetUrl = `https://query1.finance.yahoo.com/v8/finance/chart/${symbol}?range=10y&interval=1d`;
  const url = proxyUrl + encodeURIComponent(targetUrl);

  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`❌ Failed to fetch data for ${symbol} (HTTP ${response.status})`);

    const data = await response.json();
    console.log(`📊 Raw API Response for ${symbol}:`, data);

    // ✅ Ensure data exists before processing
    if (!data.chart || !data.chart.result || !data.chart.result[0]) {
      console.error(`❌ Invalid data format received for ${symbol}:`, data);
      return null;
    }

    const result = data.chart.result[0];
    const timestamps = result.timestamp;
    const closePrices = result.indicators?.quote?.[0]?.close;

    if (!timestamps || !closePrices) {
      console.error(`❌ Missing timestamps or price data for ${symbol}`);
      return null;
    }

    return timestamps.map((timestamp, index) => ({
      x: new Date(timestamp * 1000),
      y: closePrices[index] ?? null  // Ensure y-values are valid
    })).filter(point => point.y !== null); // Remove null values

  } catch (error) {
    console.error(`❌ API request error for ${symbol}:`, error);
    return null;
  }
}
