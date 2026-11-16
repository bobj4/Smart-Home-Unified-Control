/**
 * Installing on a phone: register the service worker (web/sw.js), which
 * browsers need before they offer "Install app" / "Add to Home Screen".
 * Service workers only run over HTTPS (or on localhost).
 */

if ('serviceWorker' in navigator && window.isSecureContext) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {
      // Not installable then, but the app works the same.
    });
  });
}
