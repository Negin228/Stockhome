function askSoldPrices() {
    const googlePrice = prompt("Enter the sold price of Google:");
    const facebookPrice = prompt("Enter the sold price of Facebook:");
    const metaPrice = prompt("Enter the sold price of Meta:");
    const soldDate = prompt("Enter the date you sold these:");

    // Set the sold prices in the table
    document.getElementById("googleSoldPrice").textContent = googlePrice;
    document.getElementById("facebookSoldPrice").textContent = facebookPrice;
    document.getElementById("metaSoldPrice").textContent = metaPrice;
}

function askPricesToday() {
    const googleToday = prompt("Enter the current price of Google:");
    const facebookToday = prompt("Enter the current price of Facebook:");
    const metaToday = prompt("Enter the current price of Meta:");

    // Update the Prices Today columns
    document.getElementById("googleTodayPrice").textContent = googleToday;
    document.getElementById("facebookTodayPrice").textContent = facebookToday;
    document.getElementById("metaTodayPrice").textContent = metaToday;

    // Calculate the delta for each company
    updateDelta("google");
    updateDelta("facebook");
    updateDelta("meta");
}

function updateDelta(company) {
    const soldPrice = parseFloat(document.getElementById(`${company}SoldPrice`).textContent);
    const todayPrice = parseFloat(document.getElementById(`${company}TodayPrice`).textContent);
    
    if (!isNaN(soldPrice) && !isNaN(todayPrice)) {
        const delta = todayPrice - soldPrice;
        document.getElementById(`${company}Delta`).textContent = delta.toFixed(2);
    }
}
