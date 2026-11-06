/**
 * "Remember this device" on the login page: once the code is accepted and
 * the device is approved, a popup asks what to call it ("Kitchen tablet"),
 * so it is easy to recognise later in the approved-devices lists. A name is
 * required (no cancel); it starts as the browser and system.
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
    this.overlay = el('div', { className: 'overlay', testid: 'device-name-overlay', hidden: true });
    document.body.append(this.overlay);
  }

  /** After a login that approved this device: name it before going on. */
  async ask() {
    const devices = await this.app.api.getMyDevices();
    const mine = devices.find((d) => d.current);
    if (!mine) return; // not approved (an admin turned remembering off)
    const name = el('input', { type: 'text', testid: 'device-name-input', maxlength: '60', required: true, value: guessDeviceName(), 'aria-label': 'Device name' });
    const error = el('p', { className: 'error', role: 'alert' });
    const form = el('form', { className: 'remote device-name-popup', testid: 'device-name-popup', role: 'dialog', 'aria-label': 'Name this device' }, [
      el('h2', { text: 'Name this device' }),
      el('p', { className: 'muted', text: 'This device now skips the two-factor code. Give it a name you will recognise in My account > Approved devices.' }),
      field('Name', name),
      error,
      el('button', { type: 'submit', testid: 'device-name-ok', text: 'Save name' }),
    ]);
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const chosen = name.value.trim();
      if (!chosen) {
        error.textContent = 'Give this device a name.';
        return;
      }
      try {
        await this.app.api.renameMyDevice(mine.id, chosen);
        this.close();
      } catch (problem) {
        error.textContent = problem.message;
      }
    });
    this.overlay.replaceChildren(form);
    this.overlay.hidden = false;
    name.select();
  }

  close() {
    this.overlay.hidden = true;
    this.overlay.replaceChildren();
  }
}

document.addEventListener('DOMContentLoaded', () => {
  // After app.js made the app (its listener was added first).
  if (window.smartHomeApp) window.smartHomeApp.deviceNamePopup = new DeviceNamePopup(window.smartHomeApp);
});
