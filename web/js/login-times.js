/**
 * Settings > Admin > Login times: how long "Keep me logged in", "Remember
 * me" and "Remember this device" last (for every account), and everyone's
 * approved devices in the admin's homes.
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
    const devices = el('div', { className: 'subpanel', testid: 'admin-devices' }, [
      el('h3', { text: 'Approved devices' }),
      el('p', { className: 'muted', text: 'Devices that skip the two-factor code, and whose they are. Remove one to ask for the code there again.' }),
    ]);
    container.append(form, devices);
    await new TrustedDevicesList(this.app, { all: true }).render(devices);
  }
}

window.LoginTimesPanel = LoginTimesPanel;
