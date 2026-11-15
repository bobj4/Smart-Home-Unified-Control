/**
 * My account > Alerts: which of this home's alerts I get, by email and as
 * notifications on this phone or computer. What each device alerts about
 * is set with its bell in Settings > Devices; cameras in Integrations >
 * Frigate.
 */

function keyBytes(text) {
  const padded = text.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (text.length % 4)) % 4);
  return Uint8Array.from(atob(padded), (c) => c.charCodeAt(0));
}

/** This browser's notifications: turned on (asks permission) or off. */
async function browserPush(app, on) {
  if (!('serviceWorker' in navigator) || !('PushManager' in window) || !window.isSecureContext) {
    throw new Error('This browser cannot take notifications here (it needs HTTPS; on an iPhone, add the app to the Home Screen first).');
  }
  const registration = await navigator.serviceWorker.ready;
  const current = await registration.pushManager.getSubscription();
  if (!on) {
    if (current) {
      await app.api.removePushDevice(current.endpoint);
      await current.unsubscribe();
    }
    return;
  }
  if (await Notification.requestPermission() !== 'granted') throw new Error('Notifications are blocked for this site in the browser settings.');
  const { key } = await app.api.getPushKey();
  if (!key) throw new Error('This server cannot send notifications: it needs SECRETS_KEY.');
  const subscription = current || await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(key) });
  const body = subscription.toJSON();
  await app.api.addPushDevice({ endpoint: body.endpoint, keys: body.keys, label: navigator.userAgent.slice(0, 100) });
}

class AlertsPanel {
  constructor(app) {
    this.app = app;
  }

  async render(container) {
    if (!this.app.home || this.app.isGuest()) return;
    const data = await this.app.api.getAlerts(this.app.home.id).catch(() => null);
    if (!data) return;
    const mine = data.mine;
    const kinds = data.kinds.map((k) => {
      const box = el('input', { type: 'checkbox', testid: `alert-kind-${k.id}`, checked: mine.kinds.includes(k.id), value: k.id });
      return el('label', { className: 'check' }, [box, el('span', { text: k.label })]);
    });
    const email = switchInput('alert-email', mine.email, 'Email me');
    email.disabled = !data.email_available && !mine.email;
    const push = switchInput('alert-push', mine.push, 'Notifications');
    const note = formNote('alerts-note');
    const save = (changes) => this.app.run(async () => {
      note.textContent = '';
      await this.app.api.setMyAlerts(this.app.home.id, changes);
      this.app.status.success('Alerts saved.');
    });
    kinds.forEach((label) => label.querySelector('input').addEventListener('change', () => save({
      kinds: kinds.map((l) => l.querySelector('input')).filter((b) => b.checked).map((b) => b.value),
    })));
    email.addEventListener('change', () => save({ email: email.checked }));
    push.addEventListener('change', () => this.app.run(async () => {
      try {
        await browserPush(this.app, push.checked);
        await this.app.api.setMyAlerts(this.app.home.id, { push: push.checked });
        this.app.status.success(push.checked ? 'Notifications on for this device.' : 'Notifications off for this device.');
      } catch (error) {
        push.checked = !push.checked;
        note.dataset.kind = 'error';
        note.textContent = error.message;
      }
    }));
    container.append(el('div', { className: 'subpanel', testid: 'my-alerts' }, [
      el('h3', { text: 'Alerts' }),
      el('p', { className: 'muted', text: `What ${this.app.home.name} tells you about, and how. Nothing is sent until you pick.` }),
      el('div', { className: 'guest-flags' }, kinds),
      settingRow('Email', data.email_available ? `To ${this.app.account.email}.` : 'Needs the email server (Admin > Email server).', email),
      settingRow('Notifications on this device', 'Phone or computer. Turn on on each device you want them on.', push),
      note,
      el('button', { type: 'button', className: 'secondary', testid: 'alert-test', text: 'Send me a test', onclick: () => this.app.run(async () => {
        const sent = await this.app.api.testAlert(this.app.home.id);
        this.app.status.success(`Test sent: ${[sent.email ? 'email' : '', sent.push ? `${sent.push} device${sent.push === 1 ? '' : 's'}` : ''].filter(Boolean).join(' and ') || 'nowhere yet'}.`);
      }) }),
    ]));
  }
}

window.AlertsPanel = AlertsPanel;
