/**
 * My account > Alerts: which of this home's alerts I get, by email and as
 * notifications on this phone or computer. Settings > Admin > Alerts sets
 * what the home watches for (AlertSettingsPanel, below).
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

class AlertSettingsPanel {
  constructor(app) {
    this.app = app;
  }

  async render(container) {
    const data = await this.app.api.getAlerts(this.app.home.id).catch(() => null);
    if (!data) return;
    const s = data.settings;
    const minutes = (testid, value, label) => el('input', { type: 'number', min: '0', max: '1440', testid, value: String(value), 'aria-label': label });
    const open = minutes('alert-garage-minutes', s.garage_open_minutes, 'Garage open alert minutes');
    const close = minutes('alert-auto-close', s.auto_close_minutes, 'Close it after minutes');
    const offline = minutes('alert-offline-minutes', s.offline_minutes, 'Offline alert minutes');
    const obstruction = switchInput('alert-obstruction', s.obstruction, 'Obstruction');
    const heater = switchInput('alert-heater', s.water_heater, 'Water heater');
    const types = [['thermostat', 'Thermostats'], ['water_heater', 'Water heaters'], ['garage_door', 'Garage doors'], ['tv', 'TVs'], ['light', 'Lights'], ['plug', 'Plugs']].map(([id, label]) => el('label', { className: 'check' }, [
      el('input', { type: 'checkbox', testid: `alert-offline-${id}`, value: id, checked: s.offline_types.includes(id) }), el('span', { text: label }),
    ]));
    const labels = el('input', { type: 'text', testid: 'alert-camera-labels', value: s.frigate_labels.join(', '), placeholder: 'person, car', 'aria-label': 'Camera labels' });
    const form = el('form', { className: 'subpanel', testid: 'alert-settings' }, [
      el('h3', { text: 'Alerts' }),
      el('p', { className: 'muted', text: 'What this home watches for. Each person picks what they get in My account > Alerts. 0 minutes turns that alert off.' }),
      el('div', { className: 'grid-fields' }, [
        field('Garage open longer than (minutes)', open),
        field('Then close it after (minutes, 0: never)', close),
        field('Offline longer than (minutes)', offline),
      ]),
      el('p', { className: 'muted', text: 'Offline alerts for:' }),
      el('div', { className: 'guest-flags' }, types),
      settingRow('Garage door blocked', 'A ratgdo\'s obstruction sensor sees something in the way.', obstruction),
      settingRow('Water heater problems', 'A Rheem water heater reports a new alert.', heater),
      field('Camera alerts for (Frigate labels, empty: none)', labels),
      el('button', { type: 'submit', testid: 'alert-settings-save', text: 'Save' }),
    ]);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      this.app.run(async () => {
        await this.app.api.setAlertSettings(this.app.home.id, {
          garage_open_minutes: Number(open.value || 0),
          auto_close_minutes: Number(close.value || 0),
          offline_minutes: Number(offline.value || 0),
          offline_types: types.map((t) => t.querySelector('input')).filter((b) => b.checked).map((b) => b.value),
          obstruction: obstruction.checked,
          water_heater: heater.checked,
          frigate_labels: labels.value.split(',').map((x) => x.trim()).filter(Boolean),
        });
        this.app.status.success('Alert settings saved.');
      });
    });
    container.append(form);
  }
}

window.AlertsPanel = AlertsPanel;
window.AlertSettingsPanel = AlertSettingsPanel;
