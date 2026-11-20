/**
 * "Remember this device" on the login page: once the code is accepted and
 * the device is approved, a popup asks what to call it ("Kitchen tablet"),
 * so it is easy to recognise later in the approved-devices lists. A name is
 * required (no cancel); it starts as whose and what it is ("Vulture's
 * Samsung S26").
 */

/** A phone's model code as people say it: "SM-S948U" -> "Samsung S26 Ultra"; '' if unknown. */
function phoneName(model) {
  const code = String(model || '').trim();
  const samsungS = code.match(/^SM-S9(\d)(\d)/);
  const suffix = (digit) => (digit === '8' ? ' Ultra' : ['6', '7'].includes(digit) ? '+' : '');
  if (samsungS) return `Samsung S${22 + Number(samsungS[1])}${suffix(samsungS[2])}`;
  const s21 = code.match(/^SM-G99(\d)/);
  if (s21) return `Samsung S21${suffix(s21[1])}`;
  if (/^SM-F9/.test(code)) return 'Samsung Z Fold';
  if (/^SM-F7/.test(code)) return 'Samsung Z Flip';
  const a = code.match(/^SM-A(\d\d)/);
  if (a) return `Samsung A${Number(a[1])}`;
  if (/^SM-/.test(code)) return `Samsung ${code}`;
  return code && code !== 'K' ? code : ''; // "K": a browser hiding the model
}

/** What this device is: "Samsung S26", "Pixel 9", "iPhone", "Windows PC". */
async function deviceKind() {
  const ua = navigator.userAgent;
  let model = '';
  try {
    if (navigator.userAgentData && navigator.userAgentData.getHighEntropyValues) {
      model = (await navigator.userAgentData.getHighEntropyValues(['model'])).model || '';
    }
  } catch (error) {
    model = '';
  }
  const legacy = (ua.match(/Android [^;)]*; ([^;)]+?)(?: Build[^;)]*)?\)/) || [])[1];
  const phone = phoneName(model) || phoneName(legacy);
  if (phone) return phone;
  if (/iPhone/.test(ua)) return 'iPhone';
  if (/iPad/.test(ua)) return 'iPad';
  if (/Android/.test(ua)) return /Mobile/.test(ua) ? 'Android phone' : 'Android tablet';
  if (/CrOS/.test(ua)) return 'Chromebook';
  if (/Windows/.test(ua)) return 'Windows PC';
  if (/Mac OS/.test(ua)) return 'Mac';
  if (/Linux/.test(ua)) return 'Linux PC';
  return 'computer';
}

/** The suggested name: whose and what ("Vulture's Samsung S26"). */
async function guessDeviceName(app) {
  let who = '';
  try {
    const me = await app.api.getAccount();
    who = String(me.name || '').trim().split(/\s+/)[0] || String(me.email || '').split('@')[0];
  } catch (error) {
    who = '';
  }
  const kind = await deviceKind();
  return who ? `${who}${/s$/i.test(who) ? "'" : "'s"} ${kind}` : kind;
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
    const name = el('input', { type: 'text', testid: 'device-name-input', maxlength: '60', required: true, value: (await guessDeviceName(this.app)).slice(0, 60), 'aria-label': 'Device name' });
    const error = el('p', { className: 'error', role: 'alert' });
    const form = el('form', { className: 'remote device-name-popup', testid: 'device-name-popup', role: 'dialog', 'aria-label': 'Name this device' }, [
      el('h2', { text: 'Name this device' }),
      el('p', { className: 'muted', text: 'This device now skips the two-factor code. Give it a name you will recognise in My Account > Approved devices.' }),
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
