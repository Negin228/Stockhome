async function updateChart() {
    // Use static data for testing:
    const stockData = [
        { x: new Date('2025-01-01T10:00:00'), y: 650 },
        { x: new Date('2025-01-01T11:00:00'), y: 660 },
        { x: new Date('2025-01-01T12:00:00'), y: 655 },
        { x: new Date('2025-01-01T13:00:00'), y: 670 }
    ];

    console.log('Creating chart with static data:', stockData);

    const canvas = document.getElementById('myChart');
    if (!canvas) {
        console.error('Canvas with id "myChart" not found.');
        return;
    }
    const ctx = canvas.getContext('2d');

    const chart = new Chart(ctx, {
        type: 'line',
        data: {
            datasets: [{
                label: `TSLA Stock Price (Static)`,
                data: stockData,
                borderColor: 'rgb(75, 192, 192)',
                fill: false
            }]
        },
        options: {
            responsive: true,
            scales: {
                x: {
                    type: 'time',
                    time: {
                        unit: 'hour',
                        tooltipFormat: 'PPpp'
                    },
                    title: {
                        display: true,
                        text: 'Time'
                    }
                },
                y: {
                    title: {
                        display: true,
                        text: 'Price (USD)'
                    }
                }
            }
        }
    });
}
