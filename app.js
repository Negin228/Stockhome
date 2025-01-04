let googSoldPrice, msftSoldPrice, nflxSoldPrice, amznSoldPrice, nvdaSoldPrice, metaSoldPrice;
let googQuantity, msftQuantity, nflxQuantity, amznQuantity, nvdaQuantity, metaQuantity;
let googToday, msftToday, nflxToday, amznToday, nvdaToday, metaToday;

function askSoldPrices() {
    // Ask for sold prices
    googSoldPrice = parseFloat(prompt("Enter Sold Price for Goog:"));
    msftSoldPrice = parseFloat(prompt("Enter Sold Price for MSFT:"));
    nflxSoldPrice = parseFloat(prompt("Enter Sold Price for NFLX:"));
    amznSoldPrice = parseFloat(prompt("Enter Sold Price for AMZN:"));
    nvdaSoldPrice = parseFloat(prompt("Enter Sold Price for NVDA:"));
    metaSoldPrice = parseFloat(prompt("Enter Sold Price for META:"));

    // Ask for quantities
    googQuantity = parseInt(prompt("Enter Quantity for Goog:"));
    msftQuantity = parseInt(prompt("Enter Quantity for MSFT:"));
    nflxQuantity = parseInt(prompt("Enter Quantity for NFLX:"));
    amznQuantity = parseInt(prompt("Enter Quantity for AMZN:"));
    nvdaQuantity = parseInt(prompt("Enter Quantity for NVDA:"));
    metaQuantity = parseInt(prompt("Enter Quantity for META:"));

    // Update stocks table
    updateStocksTable();

    // Update portfolio table
    updatePortfolio("goog", googQuantity, googSoldPrice, googSoldPrice);
    updatePortfolio("msft", msftQuantity, msftSoldPrice, msftSoldPrice);
    updatePortfolio("nflx", nflxQuantity, nflxSoldPrice, nflxSoldPrice);
    updatePortfolio("amzn", amznQuantity, amznSoldPrice, amznSoldPrice);
    updatePortfolio("nvda", nvdaQuantity, nvdaSoldPrice, nvdaSoldPrice);
    updatePortfolio("meta", metaQuantity, metaSoldPrice, metaSoldPrice);
}

function updateStocksTable() {
    // Calculate and update the delta
    let googDelta = (googToday - googSoldPrice) * googQuantity;
    let msftDelta = (msftToday - msftSoldPrice) * msftQuantity;
    let nflxDelta = (nflxToday - nflxSoldPrice) * nflxQuantity;
    let amznDelta = (amznToday - amznSoldPrice) * amznQuantity;
    let nvdaDelta = (nvdaToday - nvdaSoldPrice) * nvdaQuantity;
    let metaDelta = (metaToday - metaSoldPrice) * metaQuantity;

    // Display sold prices, quantity, and deltas
    document.getElementById("googSoldPrice").textContent = googSoldPrice;
    document.getElementById("msftSoldPrice").textContent = msftSoldPrice;
    document.getElementById("nflxSoldPrice").textContent = nflxSoldPrice;
    document.getElementById("amznSoldPrice").textContent = amznSoldPrice;
    document.getElementById("nvdaSoldPrice").textContent = nvdaSoldPrice;
    document.getElementById("metaSoldPrice").textContent = metaSoldPrice;

    document.getElementById("googQuantity").textContent = googQuantity;
    document.getElementById("msftQuantity").textContent = msftQuantity;
    document.getElementById("nflxQuantity").textContent = nflxQuantity;
    document.getElementById("amznQuantity").textContent = amznQuantity;
    document.getElementById("nvdaQuantity").textContent = nvdaQuantity;
    document.getElementById("metaQuantity").textContent = metaQuantity;

    // Calculate and update delta
    document.getElementById("googDelta").textContent = googDelta.toFixed(2);
    document.getElementById("msftDelta").textContent = msftDelta.toFixed(2);
    document.getElementById("nflxDelta").textContent = nflxDelta.toFixed(2);
    document.getElementById("amznDelta").textContent = amznDelta.toFixed(2);
    document.getElementById("nvdaDelta").textContent = nvdaDelta.toFixed(2);
    document.getElementById("metaDelta").textContent = metaDelta.toFixed(2);

    // Calculate and update delta percentage
    document.getElementById("googDeltaPercentage").textContent = ((googDelta / (googSoldPrice * googQuantity)) * 100).toFixed(2) + "%";
    document.getElementById("msftDeltaPercentage").textContent = ((msftDelta / (msftSoldPrice * msftQuantity)) * 100).toFixed(2) + "%";
    document.getElementById("nflxDeltaPercentage").textContent = ((nflxDelta / (nflxSoldPrice * nflxQuantity)) * 100).toFixed(2) + "%";
    document.getElementById("amznDeltaPercentage").textContent = ((amznDelta / (amznSoldPrice * amznQuantity)) * 100).toFixed(2) + "%";
    document.getElementById("nvdaDeltaPercentage").textContent = ((nvdaDelta / (nvdaSoldPrice * nvdaQuantity)) * 100).toFixed(2) + "%";
    document.getElementById("metaDeltaPercentage").textContent = ((metaDelta / (metaSoldPrice * metaQuantity)) * 100).toFixed(2) + "%";
}

function askPricesToday() {
    googToday = parseFloat(prompt("Enter Today's Price for Goog:"));
    msftToday = parseFloat(prompt("Enter Today's Price for MSFT:"));
    nflxToday = parseFloat(prompt("Enter Today's Price for NFLX:"));
    amznToday = parseFloat(prompt("Enter Today's Price for AMZN:"));
    nvdaToday = parseFloat(prompt("Enter Today's Price for NVDA:"));
    metaToday = parseFloat(prompt("Enter Today's Price for META:"));

    // Update portfolio with today's prices
    updatePortfolio("goog", googQuantity, googSoldPrice, googToday);
    updatePortfolio("msft", msftQuantity, msftSoldPrice, msftToday);
    updatePortfolio("nflx", nflxQuantity, nflxSoldPrice, nflxToday);
    updatePortfolio("amzn", amznQuantity, amznSoldPrice, amznToday);
    updatePortfolio("nvda", nvdaQuantity, nvdaSoldPrice, nvdaToday);
    updatePortfolio("meta", metaQuantity, metaSoldPrice, metaToday);
}

function updatePortfolio(company, quantity, soldPrice, todayPrice) {
    // Display Quantity
    document.getElementById(`${company}PortfolioQuantity`).textContent = quantity;

    // Calculate Sold Portfolio (Quantity * Sold Price)
    const soldPortfolio = quantity * soldPrice;
    document.getElementById(`${company}SoldPortfolio`).textContent = soldPrice;
    document.getElementById(`${company}PortfolioSoldValue`).textContent = soldPortfolio.toFixed(2);

    // Calculate Portfolio Today (Quantity * Today's Price)
    const portfolioToday = quantity * todayPrice;
    document.getElementById(`${company}PortfolioTodayPrice`).textContent = todayPrice;
    document.getElementById(`${company}PortfolioTodayValue`).textContent = portfolioToday.toFixed(2);
}
