document.getElementById('filters-btn').onclick = function(event) {
  event.preventDefault();
  fetch('pages/filters-1.html')
    .then(response => response.text())
    .then(html => {
      document.getElementById('buy-signals').innerHTML = html;
    });
};
