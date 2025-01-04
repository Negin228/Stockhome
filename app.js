function askSoldPrices() {
    const googQuantity = prompt("Enter the quantity of Goog sold:");
    const msftQuantity = prompt("Enter the quantity of MSFT sold:");
    const nflxQuantity = prompt("Enter the quantity of NFLX sold:");
    const amznQuantity = prompt("Enter the quantity of AMZN sold:");
    const nvdaQuantity = prompt("Enter the quantity of NVDA sold:");
    const metaQuantity = prompt("Enter the quantity of META sold:");
    
    const googPrice = prompt("Enter the sold price of Goog:");
    const msftPrice = prompt("Enter the sold price of MSFT:");
    const nflxPrice = prompt("Enter the sold price of NFLX:");
    const amznPrice = prompt("Enter the sold price of AMZN:");
    const nvdaPrice = prompt("Enter the sold price of NVDA:");
    const metaPrice = prompt("Enter the sold price of META:");
    
    // Capture and display the sold date
    const soldDate = prompt("Enter the date you sold these:");
    document.getElementById("dateDisplay").textContent = `Sold on: ${soldDate}`;

    // Set the quantity and sold prices in the table
    document.getElementById("googQuantity").textContent = googQuantity;
    document.getElementById("msftQuantity").textContent = msftQuantity;
    document.getElementById("nflxQuantity").textContent = nflxQuantity;
    document.getElementById("amznQuantity").textContent = amznQuantity;
    document.getElementById("nvdaQuantity").textContent = nvdaQuantity;
    document.getElementById("metaQuantity").textContent = metaQuantity;

    document.getElementById("googSoldPrice").textContent = googPrice;
    document.getElementById("msftSoldPrice").textContent = msftPrice;
    document.getElementById("nflxSoldPrice").textContent = nflxPrice;
    document.getElementById("amznSoldPrice").textContent = amznPrice;
    document.getElementById("nvdaSoldPrice").textContent = nvdaPrice;
    document.getElementById("metaSoldPrice").textContent = metaPrice;
}

function askPricesToday() {
    const googToday = prompt("Enter the current price of Goog:");
    const msftToday = prompt("Enter the current price of MSFT:");
    const nflxToday = prompt("Enter the current price of NFLX:");
    const amznToday = prompt("Enter the current price of AMZN:");
    const nvdaToday = prompt("Enter the current price of NVDA:");
    const metaToday = prompt("Enter the current price of META:");

    // Update the Prices Today columns
    document.getElementById("googTodayPrice").textContent = googToday;
    document.getElementById("msftTodayPrice").textContent = msftToday;
    document.getElementById("nflxTodayPrice").textContent = nflxToday;
    document.getElementById("amznTodayPrice").textContent = amznToday;
    document.getElementById("nvdaTodayPrice").textContent = nvdaToday;
    document.getElementById("metaTodayPrice").textContent = metaToday;

    // Calculate the delta for each company
    updateDelta("goog");
    updateDelta("msft");
    updateDelta("nflx");
    updateDelta("amzn");
    updateDelta("nvda");
    updateDelta("meta");

    // Calculate the percentage delta for each company
    updateDeltaPercentage("goog");
    updateDeltaPercentage("msft");
    updateDeltaPercentage("nflx");
    updateDeltaPercentage("amzn");
    updateDeltaPercentage("nvda");
    updateDeltaPercentage("meta");
}

function updateDelta(company) {
    const soldPrice = parseFloat(document.getElementById(`${company}SoldPrice`).textContent);
    const todayPrice = parseFloat(document.getElementById(`${company}TodayPrice`).textContent);
    
    if (!isNaN(soldPrice) && !isNaN(todayPrice)) {
        const delta = todayPrice - soldPrice;
        document.getElementById(`${company}Delta`).textContent = delta.toFixed(2);
    }
}

function updateDeltaPercentage(company) {
    const soldPrice = parseFloat(document.getElementById(`${company}SoldPrice`).textContent);
    const todayPrice = parseFloat(document.getElementById(`${company}TodayPrice`).textContent);

    if (!isNaN(soldPrice) && !isNaN(todayPrice)) {
        const delta = todayPrice - soldPrice;
        const deltaPercentage = (delta / soldPrice) * 100;
        document.getElementById(`${company}DeltaPercentage`).textContent = deltaPercentage.toFixed(2) + "%";
    }
}
