// /scripts/navbar.js
(function () {
  function initNavbar() {
    var navToggle = document.querySelector('.nav-toggle');
    var nav = document.querySelector('.nav');
    
    // Check if elements exist and if we've already attached the listener
    if (!navToggle || !nav || navToggle.dataset.initialized === 'true') return;

    navToggle.addEventListener('click', function () {
      nav.classList.toggle('open');
      var expanded = this.getAttribute('aria-expanded') === 'true';
      this.setAttribute('aria-expanded', (!expanded).toString());
    });
    
    // Mark as initialized so we don't attach multiple listeners
    navToggle.dataset.initialized = 'true';
  }

  window.initNavbar = initNavbar;
})();
