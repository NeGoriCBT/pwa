const CACHE_NAME = "cbt-pwa-v222";
const ASSETS = [
  "./",
  "./main.html",
  "./index.html",
  "./styles.css",
  "./app.js",
  "./automatic-thought-help.js",
  "./image/1.png",
  "./image/2.png",
  "./image/3.png",
  "./image/4.png",
  "./image/5.png",
  "./image/SUN.png",
  "./image/SUN2.png",
  "./image/pl1.png",
  "./image/pl2.png",
  "./image/pl3.png",
  "./manifest.webmanifest"
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  event.respondWith(
    // Важно: матчить только внутри текущей версии кэша,
    // иначе можно случайно отдать старый `app.js` из прошлых кэшей.
    caches.open(CACHE_NAME).then((cache) =>
      cache.match(event.request).then((cached) => {
        if (cached) return cached;
        return fetch(event.request)
          .then((response) => {
            const copy = response.clone();
            cache.put(event.request, copy);
            return response;
          })
          .catch(() => cache.match("./index.html"));
      })
    )
  );
});
