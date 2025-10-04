// time.js
function updateTime() {
    const now = new Date();
    document.getElementById('time').innerText = now.toLocaleTimeString();
}
setInterval(updateTime, 1000);
