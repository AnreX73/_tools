(function () {
  'use strict';
  const button = document.getElementById('push-toggle');
  const status = document.getElementById('push-status');
  if (!button || !status) return;
  const supported = window.isSecureContext && 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
  if (!supported) {
    status.textContent = /iPad|iPhone|iPod/.test(navigator.userAgent)
      ? 'Для уведомлений добавьте сайт на экран «Домой» через меню «Поделиться» (iOS 16.4+).'
      : 'Уведомления доступны в поддерживаемом браузере по HTTPS.';
    return;
  }
  let registration;
  let active = false;
  let publicKey;
  const csrf = () => document.querySelector('[name=csrfmiddlewaretoken]')?.value;
  const paint = () => {
    button.textContent = active ? 'Выключить уведомления' : 'Включить уведомления о сообщениях';
  };
  async function post(url, body) {
    const response = await fetch(url, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      const data = await response.json();
      throw new Error(data.error || 'Не удалось сохранить настройки уведомлений.');
    }
  }
  async function save(subscription) {
    await post('/chat/push/subscribe/', { subscription: subscription.toJSON() });
    active = true;
    paint();
  }
  async function init() {
    try {
      // Retire the worker from the initial draft, whose scope was /static/js/.
      const registrations = await navigator.serviceWorker.getRegistrations();
      for (const item of registrations) {
        if (item.scope === location.origin + '/static/js/') await item.unregister();
      }
      await navigator.serviceWorker.register('/sw.js', { scope: '/' });
      registration = await navigator.serviceWorker.ready;
      const response = await fetch('/chat/push/vapid-public-key/');
      if (!response.ok) throw new Error('Не удалось загрузить настройки уведомлений.');
      const config = await response.json();
      if (!config.enabled) {
        status.textContent = 'Уведомления пока не настроены на сервере.';
        return;
      }
      publicKey = config.public_key;
      button.hidden = false;
      const subscription = await registration.pushManager.getSubscription();
      if (subscription && Notification.permission === 'granted') {
        try { await save(subscription); }
        catch (error) { status.textContent = error.message; }
      }
      paint();
    } catch (error) { status.textContent = error.message; }
  }
  button.addEventListener('click', async () => {
    button.disabled = true;
    status.textContent = '';
    try {
      if (active) {
        await post('/chat/push/unsubscribe/', {});
        const subscription = await registration.pushManager.getSubscription();
        if (subscription) await subscription.unsubscribe();
        active = false;
        paint();
        status.textContent = 'Уведомления выключены.';
      } else {
        // The browser permission prompt must start directly from the button click.
        const permission = await Notification.requestPermission();
        if (permission !== 'granted') throw new Error('Разрешите уведомления в настройках браузера для этого сайта.');
        if (button.dataset.operator !== 'true') await post('/chat/start/', {});
        let subscription = await registration.pushManager.getSubscription();
        if (subscription) {
          // Recreate after a session/account change so the endpoint cannot retain its old owner.
          await subscription.unsubscribe();
        }
        const raw = atob(publicKey.replace(/-/g, '+').replace(/_/g, '/'));
        subscription = await registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: Uint8Array.from(raw, (char) => char.charCodeAt(0)),
        });
        await save(subscription);
        status.textContent = 'Уведомления включены.';
      }
    } catch (error) { status.textContent = error.message; }
    finally { button.disabled = false; }
  });
  init();
})();
