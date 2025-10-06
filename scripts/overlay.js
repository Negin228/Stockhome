// Function to open filters overlay
function openFiltersOverlay() {
    fetch('pages/filters.html')
        .then(response => response.text())
        .then(html => {
            const overlay = document.getElementById('filters-overlay');
            overlay.innerHTML = `
                <div style="
                    position:fixed;top:0;left:0;width:100vw;height:100vh;
                    background:rgba(0,0,0,0.4);z-index:9999;display:flex;align-items:center;justify-content:center;
                ">
                    <div style="background:#fff;padding:2rem 2rem;min-width:350px;position:relative;">
                        <button id="close-filters-overlay" style="
                            position:absolute;top:1rem;right:1rem;font-size:1.5rem;border:none;background:none;cursor:pointer;
                        ">&times;</button>
                        ${html}
                    </div>
                </div>
            `;
            overlay.style.display = 'block';
            // Close button logic
            document.getElementById('close-filters-overlay').onclick = closeFiltersOverlay;
        });
}

function closeFiltersOverlay() {
    const overlay = document.getElementById('filters-overlay');
    overlay.style.display = 'none';
    overlay.innerHTML = '';
}
