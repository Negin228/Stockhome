// SPA helper
function attachSpaLinks() {
  document.querySelectorAll('a[data-spa]').forEach(link => {
    link.onclick = function(event) {
      event.preventDefault();
      fetch(this.href)
        .then(response => response.text())
        .then(html => {
          const tempDiv = document.createElement('div');
          tempDiv.innerHTML = html;
          const newMain = tempDiv.querySelector('main');
          if (newMain) {
            document.querySelector('main').innerHTML = newMain.innerHTML;
            history.pushState(null, '', this.href);
            attachSpaLinks(); // re-bind for new content!
            if (typeof initializeFilters === 'function') initializeFilters();
          } else {
            window.location.href = this.href;
          }
        })
        .catch(() => window.location.href = this.href);
    };
  });
}
document.addEventListener('DOMContentLoaded', attachSpaLinks);

window.addEventListener('popstate', function() {
  fetch(window.location.href)
    .then(response => response.text())
    .then(html => {
      const tempDiv = document.createElement('div');
      tempDiv.innerHTML = html;
      const newMain = tempDiv.querySelector('main');
      if (newMain) {
        document.querySelector('main').innerHTML = newMain.innerHTML;
        attachSpaLinks();
        if (typeof initializeFilters === 'function') initializeFilters();
      } else {
        window.location.reload();
      }
    });
});
