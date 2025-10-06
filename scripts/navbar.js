// scripts/navbar.js
document.addEventListener('DOMContentLoaded', function() {
  var navToggle = document.querySelector('.nav-toggle');
  if (navToggle) {
    navToggle.addEventListener('click', function() {
      var nav = document.querySelector('.nav');
      nav.classList.toggle('open');
      // For accessibility:
      var expanded = this.getAttribute('aria-expanded') === 'true';
      this.setAttribute('aria-expanded', !expanded);
    });
  }
});


document.querySelectorAll('a[data-spa]').forEach(link => {
  link.addEventListener('click', function(event) {
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
          // OPTIONAL: update active nav button here, re-initialize scripts
        } else {
          window.location.href = this.href; // fallback to full reload
        }
      })
      .catch(() => {
        window.location.href = this.href; // fallback on fetch error
      });
  });
});

window.addEventListener('popstate', () => {
  fetch(window.location.href)
    .then(response => response.text())
    .then(html => {
      const tempDiv = document.createElement('div');
      tempDiv.innerHTML = html;
      const newMain = tempDiv.querySelector('main');
      if (newMain) {
        document.querySelector('main').innerHTML = newMain.innerHTML;
        // OPTIONAL: update active nav button here
      } else {
        window.location.reload();
      }
    });
});

