// Installable-shell service worker (see decisions.md's "PWA" entry).
// Deliberately does NOT cache API responses, trip data, or anything
// per-user -- that's "offline trip viewing," a larger scope explicitly
// not built here. This only caches the small set of static assets every
// page needs, so a repeat visit paints faster and the app is installable
// at all (a manifest without a controlling service worker doesn't pass
// most browsers' installability check).
const CACHE_NAME = "itinera-shell-v1";
const SHELL_ASSETS = [
  "/manifest.webmanifest",
  "/pwa-icon-192.png",
  "/pwa-icon-512.png",
  "/pwa-icon-maskable-512.png",
  "/favicon.ico",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_ASSETS)),
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))),
    ),
  );
  self.clients.claim();
});

// Cache-first for the shell assets above; everything else (pages, API
// calls, chat/trip data) goes straight to the network, untouched -- this
// app's data is per-user and changes constantly, the opposite of what a
// cache-first strategy should touch.
self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;
  if (!SHELL_ASSETS.includes(url.pathname)) return;

  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request)),
  );
});
