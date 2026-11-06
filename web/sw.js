/**
 * Service worker: lets phones install the app (Add to Home Screen) and shows
 * a short page when the server cannot be reached. It stores nothing: every
 * request still goes to the server, so no home data is kept on the phone.
 */

const OFFLINE_PAGE = `<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Smart Home Unified Control</title></head>
<body style="font-family: system-ui, sans-serif; background: #111317; color: #e8eaed; display: grid; place-items: center; min-height: 100vh; margin: 0; text-align: center;">
<div><h1 style="font-size: 1.3rem;">Can't reach your smart home</h1>
<p>Check that this phone is on your home network (or VPN), then try again.</p>
<p><a href="/" style="color: #c99bff;">Try again</a></p></div></body></html>`;

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

self.addEventListener('fetch', (event) => {
  if (event.request.mode !== 'navigate') return; // everything else: the browser as usual
  event.respondWith(fetch(event.request).catch(() => new Response(OFFLINE_PAGE, {
    status: 503, headers: { 'Content-Type': 'text/html; charset=utf-8' },
  })));
});
