/**
 * Settings > Admin > Login times: how long "Keep me logged in", "Remember
 * me" and "Remember this device" last (for every account), and everyone's
 * approved devices in the admin's homes.
 */

const LOGIN_TIME_FIELDS = [
  ['keep_logged_in_days', 'Keep me logged in (days)', 1, 365, 'How long a login with "Keep me logged in" lasts.'],
  ['remember_me_days', 'Remember me (days)', 1, 3650, 'How long the login name stays filled in.'],
  ['remember_device_days', 'Remember this device (days, 0 = forever)', 0, 3650, 'How long an approved device skips the two-factor code. Applies to devices approved earlier too.'],
];

class LoginTimesPanel {
  constructor(app) {
    this.app = app;
  }

  async render(container) {
    const times = await this.app.api.getLoginTimes();
    const inputs = {};
    const fields = LOGIN_TIME_FIELDS.map(([key, label, min, max, help]) => {
      inputs[key] = el('input', {
        type: 'number', testid: `login-time-${key}`, min: String(min), max: String(max), step: '1', required: true, value: String(times[key]),
      });
      return el('div', {}, [field(label, inputs[key]), el('p', { className: 'muted', text: help })]);
    });
    const form = el('form', { className: 'subpanel', testid: 'login-times' }, [
      el('h3', { text: 'Login times' }),
      el('div', { className: 'grid-fields' }, fields),
      el('button', { type: 'submit', testid: 'login-times-save', text: 'Save login times' }),
    ]);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      this.app.run(async () => {
        const body = Object.fromEntries(Object.entries(inputs).map(([key, input]) => [key, Number(input.value)]));
        const saved = await this.app.api.setLoginTimes(body);
        Object.entries(saved).forEach(([key, value]) => { inputs[key].value = String(value); });
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
