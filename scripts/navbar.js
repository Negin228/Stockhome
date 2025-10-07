// /scripts/navbar.js
(function () {
  function initNavbar() {
    var navToggle = document.querySelector('.nav-toggle');
    var nav = document.querySelector('.nav');
    if (!navToggle || !nav) return;

    navToggle.addEventListener('click', function () {
      nav.classList.toggle('open');
      var expanded = this.getAttribute('aria-expanded') === 'true';
      this.setAttribute('aria-expanded', (!expanded).toString());
    });
  }

  // expose a global init so you can call it after injecting header.html
  window.initNavbar = initNavbar;
})();
