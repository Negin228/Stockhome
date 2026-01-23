(function () {
  function initNavbar() {
    const navToggle = document.querySelector('.nav-toggle');
    const nav = document.querySelector('.nav');
    
    // Safety checks
    if (!navToggle || !nav) return;
    
    // Remove existing listeners to avoid "double-toggle" bugs
    const newToggle = navToggle.cloneNode(true);
    navToggle.parentNode.replaceChild(newToggle, navToggle);

    newToggle.addEventListener('click', function () {
      nav.classList.toggle('open');
      const expanded = this.getAttribute('aria-expanded') === 'true';
      this.setAttribute('aria-expanded', (!expanded).toString());
    });
  }

  window.initNavbar = initNavbar;
})();
