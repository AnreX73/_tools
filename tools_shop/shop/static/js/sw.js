'use strict';

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    // Remove the cache from the initial PWA draft (it could contain private pages).
    await caches.delete('tools-shop-v1');
    await self.clients.claim();
  })());
});

self.addEventListener('push', (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch { /* use fallback */ }
  event.waitUntil(self.registration.showNotification(data.title || 'Новое сообщение', {
    body: data.body || 'У вас новое сообщение в чате',
    icon: '/static/shop/images/pwa-192.png',
    tag: data.tag || 'chat-message',
    data: data.data || { url: '/?chat=open' },
  }));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  let target;
  try { target = new URL(event.notification.data?.url || '/?chat=open', self.location.origin); }
  catch { return; }
  if (target.origin !== self.location.origin) return;
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    const client = windows.find((item) => item.url.startsWith(self.location.origin + '/'));
    if (client) {
      await client.navigate(target.href);
      await client.focus();
    } else {
      await self.clients.openWindow(target.href);
    }
  })());
});
