/* DS59 service worker — app-shell cache + fresh briefing data */
const CACHE = 'ds59-v2';
const ASSETS = [
  './', './index.html', './manifest.webmanifest', './brief.json',
  './icon-512.png', './maskable-512.png'
];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  // Always try the network first for the briefing data so the phone shows today's brief.
  if (url.pathname.endsWith('brief.json')) {
    e.respondWith(
      fetch(e.request).then((r) => {
        const copy = r.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
        return r;
      }).catch(() => caches.match(e.request))
    );
    return;
  }
  // App shell: cache-first, fall back to network.
  e.respondWith(caches.match(e.request).then((r) => r || fetch(e.request)));
});
