/* SYNTHESIS service worker — offline shell so the app installs on PC & mobile.
   API responses are network-first (live world state must never be stale-served silently). */
const SHELL = "synthesis-shell-v1";
const ASSETS = ["/", "/index.html", "/style.css", "/app.js", "/manifest.webmanifest",
                "/icons/icon-192.png", "/icons/icon-512.png", "/world.geo.json"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== SHELL).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.pathname.startsWith("/api/")) {
    // network-first, no cache write: evidence freshness matters
    e.respondWith(fetch(e.request).catch(() => new Response(JSON.stringify({ offline: true }), { headers: { "Content-Type": "application/json" } })));
    return;
  }
  e.respondWith(caches.match(e.request).then((hit) => hit || fetch(e.request)));
});
