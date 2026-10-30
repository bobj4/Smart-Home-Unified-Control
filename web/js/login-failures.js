/**
 * Settings > Admin: what happens after repeated failed logins (every
 * account). None, Lockout (for a time, or until the password is reset) or
 * Lockdown (the account is turned off until an admin turns it on again).
 */

const FAILURE_ACTIONS = [
  ['none', 'None: only slow down repeated tries'],
  ['lockout', 'Lockout: block the account for a time, or until its password is reset'],
  ['lockdown', 'Lockdown: turn the account off until an admin turns it on again'],
];

class LoginFailuresPanel {
  constructor(app) {
    this.app = app;
  }

  async render(container) {
    const rules = await this.app.api.getLoginFailures();
    const action = el('select', { testid: 'failure-action', 'aria-label': 'After failed logins' },
      FAILURE_ACTIONS.map(([value, text]) => el('option', { value, text })));
    action.value = rules.action;
    const number = (testid, value) => el('input', {
      type: 'number', testid, min: '0', step: '1', placeholder: 'off', value: value === null ? '' : String(value),
    });
    const limit = number('failure-limit', rules.limit);
    const minutes = number('failure-minutes', rules.lockout_minutes);
    const minutesBox = el('div', {}, [
      field('Lockout length (minutes)', minutes),
      el('p', { className: 'muted', text: '0 = until the password is reset (by an admin or a reset code). Blank = lockouts off.' }),
    ]);
    const showMinutes = () => { minutesBox.hidden = action.value !== 'lockout'; };
    action.addEventListener('change', showMinutes);
    showMinutes();
    const form = el('form', { className: 'subpanel', testid: 'login-failures' }, [
      el('h3', { text: 'Failed logins' }),
      field('After repeated failed logins', action),
      el('div', { className: 'grid-fields' }, [
        el('div', {}, [
          field('Failed logins in a row', limit),
          el('p', { className: 'muted', text: 'How many wrong passwords or codes before it applies. Blank = off. A correct login starts the count again.' }),
        ]),
        minutesBox,
      ]),
      el('button', { type: 'submit', testid: 'failure-save', text: 'Save failed-login rule' }),
    ]);
    const value = (input) => (input.value.trim() === '' ? null : Number(input.value));
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      this.app.run(async () => {
        const saved = await this.app.api.setLoginFailures({ action: action.value, limit: value(limit), lockout_minutes: value(minutes) });
        limit.value = saved.limit === null ? '' : String(saved.limit);
        minutes.value = saved.lockout_minutes === null ? '' : String(saved.lockout_minutes);
        this.app.status.success('Failed-login rule saved.');
      });
    });
    container.append(form);
  }
}

window.LoginFailuresPanel = LoginFailuresPanel;
