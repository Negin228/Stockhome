// /scripts/loader.js
async function loadComponent(elementId, componentPath, isNavbar = false) {
  const element = document.getElementById(elementId);
  if (!element) return;

  // Detect if we are in /pages/ or the root /
  const prefix = window.location.pathname.includes('/pages/') ? '../' : '';
  
  try {
    const response = await fetch(prefix + componentPath);
    const html = await response.text();
    element.innerHTML = html;

    // If this is the header, initialize the navbar
    if (isNavbar) {
      // Ensure navbar.js is loaded
      if (typeof window.initNavbar === 'function') {
        window.initNavbar();
      } else {
        // Dynamically load navbar.js if it's not already there
        const script = document.createElement('script');
        script.src = '/scripts/navbar.js';
        script.onload = () => { if (window.initNavbar) window.initNavbar(); };
        document.body.appendChild(script);
      }
    }
  } catch (error) {
    console.error(`Error loading ${componentPath}:`, error);
  }
}

// Automatically trigger loads when the script is included
document.addEventListener('DOMContentLoaded', () => {
  loadComponent('header-include', 'pages/header.html', true);
  loadComponent('footer-include', 'pages/footer.html');
});
