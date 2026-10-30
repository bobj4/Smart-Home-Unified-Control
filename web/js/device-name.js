/**
 * "Remember this device" on the login page: ticking it asks what to call
 * this device ("Kitchen tablet"), so it is easy to recognise later in the
 * approved-devices lists. Cancel unticks it. The name goes with the login.
 */

function guessDeviceName() {
  const ua = navigator.userAgent;
  const browser = /Edg\//.test(ua) ? 'Edge' : /Firefox\//.test(ua) ? 'Firefox' : /Chrome\/|CriOS/.test(ua) ? 'Chrome' : /Safari\//.test(ua) ? 'Safari' : 'Browser';
  const system = /iPhone/.test(ua) ? 'iPhone' : /iPad/.test(ua) ? 'iPad' : /Android/.test(ua) ? 'Android' : /Windows/.test(ua) ? 'Windows' : /Mac OS/.test(ua) ? 'Mac' : /Linux/.test(ua) ? 'Linux' : 'this computer';
  return `${browser} on ${system}`;
}

class DeviceNamePopup {
  constructor(app) {
    this.app = app;
    this.box = byTestId('login-remember-device');
    this.overlay = el('div', { className: 'overlay', testid: 'device-name-overlay', hidden: true });
    document.body.append(this.overlay);
    this.box.addEventListener('change', () => {
      if (this.box.checked) this.ask();
      else this.app.api.deviceName = null;
    });
  }

  ask() {
    const name = el('input', { type: 'text', testid: 'device-name-input', maxlength: '60', value: this.app.api.deviceName || guessDeviceName(), 'aria-label': 'Device name' });
    const form = el('form', { className: 'remote device-name-popup', testid: 'device-name-popup', role: 'dialog', 'aria-label': 'Name this device' }, [
      el('h2', { text: 'Name this device' }),
      el('p', { className: 'muted', text: 'It will skip the two-factor code here, and show under this name in My account > Approved devices.' }),
      field('Name', name),
      el('div', { className: 'row' }, [
        el('button', { type: 'submit', testid: 'device-name-ok', text: 'Remember this device' }),
        el('button', { type: 'button', className: 'secondary', testid: 'device-name-cancel', text: 'Cancel', onclick: () => this.cancel() }),
      ]),
    ]);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      this.app.api.deviceName = name.value.trim() || guessDeviceName();
      this.close();
    });
    form.addEventListener('keydown', (e) => { if (e.key === 'Escape') this.cancel(); });
    this.overlay.replaceChildren(form);
    this.overlay.hidden = false;
    name.select();
  }

  cancel() {
    this.box.checked = false;
    this.app.api.deviceName = null;
    this.close();
  }

  close() {
    this.overlay.hidden = true;
    this.overlay.replaceChildren();
    this.box.focus();
  }
}

document.addEventListener('DOMContentLoaded', () => {
  // After app.js made the app (its listener was added first).
  if (window.smartHomeApp) window.smartHomeApp.deviceNamePopup = new DeviceNamePopup(window.smartHomeApp);
});
