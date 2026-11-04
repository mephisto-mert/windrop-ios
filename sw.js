const CACHE_NAME = 'windrop-native-v12';
const SHELL_ASSETS = ['./', './index.html', './manifest.json', './icon-180.png'];

self.addEventListener('install', (e) => {
  self.skipWaiting();
  e.waitUntil(
    caches.open(CACHE_NAME).then((c) => c.addAll(SHELL_ASSETS))
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.map((k) => {
        if (k !== CACHE_NAME) return caches.delete(k);
      }))
    ).then(() => self.clients.claim())
  );
});

// NETWORK-FIRST FOR ALL PAGES & ASSETS
self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET') return;
  if (url.pathname.includes('/api/') || url.pathname.endsWith('.json') || url.pathname.endsWith('.png')) {
    return; // Do not cache API or live images
  }
  
  e.respondWith(
    fetch(e.request).then((netRes) => {
      if (netRes && netRes.status === 200) {
        const clone = netRes.clone();
        caches.open(CACHE_NAME).then((c) => c.put(e.request, clone));
      }
      return netRes;
    }).catch(() => caches.match(e.request))
  );
});
