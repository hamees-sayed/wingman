// Keeps the app's own page and icons so it opens offline. Everything else, the API and the live
// socket above all, always goes to the network.
const CACHE = "wingman-v1";
const SHELL = ["/", "/manifest.webmanifest", "/icon-192.png", "/icon-512.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== location.origin || !SHELL.includes(url.pathname)) return;
  // The newest page when online, the kept one when not.
  event.respondWith(fetch(event.request)
    .then((response) => {
      const copy = response.clone();
      caches.open(CACHE).then((cache) => cache.put(event.request, copy));
      return response;
    })
    .catch(() => caches.match(event.request)));
});
