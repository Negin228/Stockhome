<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Stock Portfolio</title>
    <style>
        table {
            width: 100%;
            border-collapse: collapse;
            margin: 10px 0;
        }

        table, th, td {
            border: 1px solid black;
        }

        th, td {
            padding: 8px;
            text-align: center;
        }

        .form-group {
            margin: 10px 0;
        }

        #login-form {
            margin-bottom: 20px;
        }
    </style>
</head>
<body>

    <!-- Login Form -->
    <div id="login-form">
        <h3>Login to Edit Data</h3>
        <input type="text" id="username" placeholder="Username" required>
        <input type="password" id="password" placeholder="Password" required>
        <button onclick="login()">Login</button>
    </div>

    <!-- Editable Table for Stocks -->
    <div id="stock-table" style="display: none;">
        <h2>Enter Your Stock Data</h2>
        <table id="stocksTable">
            <thead>
                <tr>
                    <th>Stock</th>
                    <th>Sold Price</th>
                    <th>Price Today</th>
                    <th>Quantity</th>
                    <th>Delta (%)</th>
                </tr>
            </thead>
            <tbody id="stocksData">
                <!-- Stock Data Rows will be inserted here -->
            </tbody>
        </table>
    </div>

    <!-- Portfolio Table -->
    <div id="portfolio-table" style="display: none;">
        <h2>Portfolio Summary</h2>
        <table id="portfolioTable">
            <thead>
                <tr>
                    <th>Portfolio Value (Sold)</th>
                    <th>Portfolio Value (Today)</th>
                    <th>Delta (%)</th>
                </tr>
            </thead>
            <tbody id="portfolioData">
                <tr>
                    <td id="soldPortfolioValue">0</td>
                    <td id="portfolioValueToday">0</td>
                    <td id="portfolioDelta">0</td>
                </tr>
            </tbody>
        </table>
    </div>

    <script>
        // Username and password for login
        const correctUsername = 'admin';
        const correctPassword = 'password123';

        // Load saved stock data from localStorage
        function loadSavedData() {
            const savedData = localStorage.getItem('stockData');
            if (savedData) {
                return JSON.parse(savedData);
            }
            return [
                { company: 'GOOG', soldPrice: null, priceToday: null, quantity: null },
                { company: 'MSFT', soldPrice: null, priceToday: null, quantity: null },
                { company: 'NFLX', soldPrice: null, priceToday: null, quantity: null },
                { company: 'AMZN', soldPrice: null, priceToday: null, quantity: null },
                { company: 'NVDA', soldPrice: null, priceToday: null, quantity: null },
                { company: 'META', soldPrice: null, priceToday: null, quantity: null }
            ];
        }

        // Save data to localStorage
        function saveDataToLocalStorage() {
            localStorage.setItem('stockData', JSON.stringify(stocks));
        }

        // Update stock data when inputs change
        function updateStockData(company, field, value) {
            const stock = stocks.find(stock => stock.company === company);
            stock[field] = field === 'quantity' ? parseInt(value) : parseFloat(value);
            saveDataToLocalStorage();  // Save data to localStorage
            updateStockTable();
            calculatePortfolio();
        }

        // Update stock table view
        function updateStockTable() {
            const stockTableBody = document.getElementById("stocksData");
            stockTableBody.innerHTML = '';
            stocks.forEach(stock => {
                const row = document.createElement('tr');
                row.innerHTML = `
                    <td>${stock.company}</td>
                    <td><input type="number" value="${stock.soldPrice || ''}" onchange="updateStockData('${stock.company}', 'soldPrice', this.value)"></td>
                    <td><input type="number" value="${stock.priceToday || ''}" onchange="updateStockData('${stock.company}', 'priceToday', this.value)"></td>
                    <td><input type="number" value="${stock.quantity || ''}" onchange="updateStockData('${stock.company}', 'quantity', this.value)"></td>
                    <td>${calculateDelta(stock)}</td>
                `;
                stockTableBody.appendChild(row);
            });
        }

        // Calculate the delta in percentage for each stock
        function calculateDelta(stock) {
            if (stock.soldPrice && stock.priceToday) {
                return ((stock.priceToday - stock.soldPrice) / stock.soldPrice * 100).toFixed(2) + '%';
            }
            return '-';
        }

        // Calculate portfolio values and delta
        function calculatePortfolio() {
            let soldPortfolioValue = 0;
            let portfolioValueToday = 0;

            stocks.forEach(stock => {
                if (stock.soldPrice && stock.quantity) {
                    soldPortfolioValue += stock.soldPrice * stock.quantity;
                }
                if (stock.priceToday && stock.quantity) {
                    portfolioValueToday += stock.priceToday * stock.quantity;
                }
            });

            const portfolioDelta = ((portfolioValueToday - soldPortfolioValue) / soldPortfolioValue * 100).toFixed(2) || 0;

            document.getElementById('soldPortfolioValue').textContent = soldPortfolioValue.toFixed(2);
            document.getElementById('portfolioValueToday').textContent = portfolioValueToday.toFixed(2);
            document.getElementById('portfolioDelta').textContent = portfolioDelta + '%';
        }

        // Login function to check username and password
        function login() {
            const username = document.getElementById('username').value;
            const password = document.getElementById('password').value;

            if (username === correctUsername && password === correctPassword) {
                document.getElementById('login-form').style.display = 'none';
                document.getElementById('stock-table').style.display = 'block';
                document.getElementById('portfolio-table').style.display = 'block';
                populateInputTable();
            } else {
                alert('Incorrect username or password');
            }
        }

        // Populate the table with saved stock data
        function populateInputTable() {
            updateStockTable();
            calculatePortfolio();
        }

        // Initial setup on page load
        let stocks = loadSavedData();  // Load data from localStorage or default
        populateInputTable();
    </script>

</body>
</html>
