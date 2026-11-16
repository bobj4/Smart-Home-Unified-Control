/**
 * Settings > Admin: what happens after repeated failed logins (every
 * account), set like the login times: a number per rule, blank = off.
 */

// [key, label, help]
const FAILURE_FIELDS = [
  ['lockout_after', 'Lock out after (failed logins)', 'Wrong passwords or codes in a row before the account is blocked for a while. Blank = off. A correct login starts the count again.'],
  ['lockout_minutes', 'Lockout length (minutes)', '0 = until the password is reset (by an admin or a reset code). Blank = lockouts off.'],
  ['lockdown_after', 'Lock down after (failed logins)', 'Failures in a row before the account is turned off until an admin turns it on again (Settings > Admin > Users). Blank = off. Use a higher number than the lockout, or on its own.'],
];

class LoginFailuresPanel {
  constructor(app) {
    this.app = app;
  }

  async render(container) {
    const rules = await this.app.api.getLoginFailures();
    const inputs = {};
    const fields = FAILURE_FIELDS.map(([key, label, help]) => {
      inputs[key] = el('input', {
        type: 'number', testid: `failure-${key}`, min: key === 'lockout_minutes' ? '0' : '1', step: '1', placeholder: 'off',
        value: rules[key] === null ? '' : String(rules[key]),
      });
      return el('div', {}, [field(label, inputs[key]), el('p', { className: 'muted', text: help })]);
    });
    const form = el('form', { className: 'subpanel', testid: 'login-failures' }, [
      el('h3', { text: 'Failed logins' }),
      el('p', { className: 'muted', text: 'Repeated tries are always slowed down. These add a lockout, a lockdown, or both.' }),
      el('div', { className: 'grid-fields' }, fields),
      el('button', { type: 'submit', testid: 'failure-save', text: 'Save failed-login rules' }),
    ]);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      this.app.run(async () => {
        const body = Object.fromEntries(Object.entries(inputs).map(([key, input]) => [key, input.value.trim() === '' ? null : Number(input.value)]));
        const saved = await this.app.api.setLoginFailures(body);
        Object.entries(saved).forEach(([key, value]) => { inputs[key].value = value === null ? '' : String(value); });
        this.app.status.success('Failed-login rules saved.');
      });
    });
    container.append(form);
  }
}

window.LoginFailuresPanel = LoginFailuresPanel;
