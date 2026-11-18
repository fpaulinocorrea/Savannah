// Minimal service worker: lets Savannah be installed as an app.
// Always fetches fresh from your computer; nothing private is cached.
self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()))
self.addEventListener('fetch', () => {})
