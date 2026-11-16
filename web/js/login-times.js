/**
 * Settings > Admin > Login rules > Login times: how long "Keep me logged in", "Remember
 * me" and "Remember this device" last (for every account); and everyone's
 * approved devices in the admin's homes (under 2 Factor Login).
 */

// Each: days; 0 = never expires; blank = turned off (its login checkbox is hidden).
const LOGIN_TIME_FIELDS = [
  ['keep_logged_in_days', 'Keep me logged in (days)', 'How long a login with "Keep me logged in" lasts. 0 = until logging out. Blank = off: the checkbox is hidden and every login ends when the browser closes.'],
  ['remember_me_days', 'Remember me (days)', 'How long the login name stays filled in. 0 = never forgotten. Blank = off: the checkbox is hidden.'],
  ['remember_device_days', 'Remember this device (days)', 'How long an approved device skips the two-factor code. 0 = never expires. Blank = off: the checkbox is hidden and every device needs the code again. Applies to devices approved earlier too.'],
];

class LoginTimesPanel {
  constructor(app) {
    this.app = app;
  }

  async render(container) {
    const times = await this.app.api.getLoginTimes();
    const inputs = {};
    const fields = LOGIN_TIME_FIELDS.map(([key, label, help]) => {
      inputs[key] = el('input', {
        type: 'number', testid: `login-time-${key}`, min: '0', step: '1', placeholder: 'off', value: times[key] === null ? '' : String(times[key]),
      });
      return el('div', {}, [field(label, inputs[key]), el('p', { className: 'muted', text: help })]);
    });
    const warning = el('p', { className: 'note', testid: 'login-times-forever-warning', text: '"Keep me logged in" with 0 never logs out on its own. Use it only if this server is not reachable from the internet, or every account has two-factor login.' });
    const warn = () => { warning.hidden = inputs.keep_logged_in_days.value.trim() !== '0'; };
    inputs.keep_logged_in_days.addEventListener('input', warn);
    warn();
    fields.push(warning);
    const form = el('form', { className: 'subpanel', testid: 'login-times' }, [
      el('h3', { text: 'Login times' }),
      el('div', { className: 'grid-fields' }, fields),
      el('button', { type: 'submit', testid: 'login-times-save', text: 'Save login times' }),
    ]);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      this.app.run(async () => {
        const body = Object.fromEntries(Object.entries(inputs).map(([key, input]) => [key, input.value.trim() === '' ? null : Number(input.value)]));
        const saved = await this.app.api.setLoginTimes(body);
        Object.entries(saved).forEach(([key, value]) => { inputs[key].value = value === null ? '' : String(value); });
        warn();
        this.app.status.success('Login times saved. New logins use them.');
      });
    });
    container.append(form);
  }

  /** Everyone's devices (shown under 2 Factor Login): where each person is
   * logged in, and the devices approved to skip the two-factor code. */
  async renderDevices(container) {
    const loggedIn = new AdminSessionsList(this.app);
    const approved = new TrustedDevicesList(this.app, { all: true });
    const approvedBox = el('div', {}, [
      el('p', { className: 'muted', text: 'Devices that skip the two-factor code ("Remember this device" at login), and whose they are. Remove one to ask for the code there again.' }),
    ]);
    const sessionsBox = el('div', { hidden: true }, [
      el('p', { className: 'muted', text: 'Everyone\'s logged-in devices, and whose they are.' }),
    ]);
    const tabs = [['approved', 'Approved devices', approvedBox, approved], ['sessions', 'Logged-in devices', sessionsBox, loggedIn]];
    const buttons = tabs.map(([key, label, box, list]) => el('button', {
      type: 'button', className: key === 'approved' ? 'on' : 'secondary', testid: `admin-devices-tab-${key}`, text: label,
      'aria-pressed': String(key === 'approved'),
      onclick: () => {
        tabs.forEach(([, , other], i) => {
          other.hidden = other !== box;
          buttons[i].className = other === box ? 'on' : 'secondary';
          buttons[i].setAttribute('aria-pressed', String(other === box));
        });
        this.app.run(() => list.load());
      },
    }));
    const devices = el('div', { className: 'subpanel', testid: 'admin-devices' }, [
      el('h3', { text: 'Everyone\'s devices' }),
      el('div', { className: 'segmented', role: 'group', 'aria-label': 'Everyone\'s devices' }, buttons),
      sessionsBox, approvedBox,
    ]);
    container.append(devices);
    await Promise.all([loggedIn.render(sessionsBox), approved.render(approvedBox)]);
  }
}

window.LoginTimesPanel = LoginTimesPanel;
