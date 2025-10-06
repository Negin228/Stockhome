document.addEventListener('DOMContentLoaded', function() {
  var navToggle = document.querySelector('.nav-toggle');
  if (navToggle) {
    navToggle.addEventListener('click', function() {
      var nav = document.querySelector('.nav');
      nav.classList.toggle('open');
      var expanded = this.getAttribute('aria-expanded') === 'true';
      this.setAttribute('aria-expanded', !expanded);
    });
  }
});

<!-- index.html or main file -->
<div id="header-include"></div>
<script>
  fetch('header.html')
    .then(res => res.text())
    .then(html => {
      document.getElementById('header-include').innerHTML = html;
      // Now DOM has hamburger/button/menu, so run navbar.js
      var script = document.createElement('script');
      script.src = 'navbar.js';
      document.body.appendChild(script);
    });
</script>


