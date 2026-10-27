/**
 * Settings > Your account: password, recovery codes, authenticator app and
 * logged-in sessions. Secrets shown here are displayed once and never stored.
 */

const MIN_PASSWORD = 12;

function passwordInput(testid, autocomplete) {
  return el('input', { type: 'password', testid, autocomplete, required: true });
}

class AccountSection {
  constructor(app) {
    this.app = app;
  }

  async render(container) {
    container.append(
      el('p', { className: 'muted', text: `Logged in as ${this.app.account.email}` }),
      this.passwordForm(),
      this.themeBox(),
      this.twoFactorBox(),
      this.recoveryForm(),
      this.totpForm(),
    );
    // Two tabs: where you are logged in now, and the devices approved to
    // skip the two-factor code.
    this.sessionsBox = el('div', { className: 'sessions' });
    const approved = new TrustedDevicesList(this.app);
    const approvedBox = el('div', { hidden: true });
    const tabs = [['sessions', 'Logged-in devices', this.sessionsBox], ['approved', 'Approved devices', approvedBox]];
    const buttons = tabs.map(([key, label, box]) => el('button', {
      type: 'button', className: key === 'sessions' ? 'on' : 'secondary', testid: `account-tab-${key}`, text: label,
      'aria-pressed': String(key === 'sessions'),
      onclick: () => {
        tabs.forEach(([, , other], i) => {
          other.hidden = other !== box;
          buttons[i].className = other === box ? 'on' : 'secondary';
          buttons[i].setAttribute('aria-pressed', String(other === box));
        });
        if (key === 'approved') this.app.run(() => approved.load());
      },
    }));
    container.append(el('div', { className: 'segmented', role: 'group', 'aria-label': 'Devices' }, buttons), this.sessionsBox, approvedBox);
    await Promise.all([this.loadSessions(), approved.render(approvedBox)]);
  }

  passwordForm() {
    const current = passwordInput('password-current', 'current-password');
    const next = passwordInput('password-new', 'new-password');
    const confirm = passwordInput('password-confirm', 'new-password');
    const form = el('form', { className: 'subpanel' }, [
      el('h3', { text: 'Change password' }),
      field('Current password', current),
      field(`New password (at least ${MIN_PASSWORD} characters)`, next),
      field('Repeat new password', confirm),
      el('button', { type: 'submit', testid: 'password-save', text: 'Change password' }),
    ]);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      this.app.run(async () => {
        if (next.value !== confirm.value) throw new Error('The new passwords do not match.');
        if (next.value.length < MIN_PASSWORD) throw new Error(`Use at least ${MIN_PASSWORD} characters.`);
        await this.app.api.changePassword(current.value, next.value);
        form.reset();
        this.app.status.success('Password changed. Your other devices were logged out.');
        await this.loadSessions();
      });
    });
    return form;
  }

  themeBox() {
    const select = el('select', { testid: 'theme-select', 'aria-label': 'Appearance' }, [
      el('option', { value: 'system', text: 'Device Theme' }),
      el('option', { value: 'light', text: 'Light' }),
      el('option', { value: 'dark', text: 'Dark' }),
      el('option', { value: 'red', text: 'Red' }),
      el('option', { value: 'violet', text: 'Purple' }),
    ]);
    select.value = this.app.account.theme || 'system';
    select.addEventListener('change', () => this.app.run(async () => {
      await this.app.api.setPreferences({ theme: select.value });
      this.app.account.theme = select.value;
      this.app.applyTheme(select.value);
      this.app.status.success('Appearance saved.');
    }));
    return el('div', { className: 'subpanel' }, [el('h3', { text: 'Appearance' }), field('Colours', select)]);
  }

  twoFactorBox() {
    this.twoFactor = el('div', { className: 'subpanel', testid: 'two-factor' });
    this.fillTwoFactor();
    return this.twoFactor;
  }

  fillTwoFactor() {
    const account = this.app.account;
    const parts = [
      el('h3', { text: 'Two-factor login' }),
      el('p', {
        testid: 'two-factor-status',
        text: account.two_factor
          ? 'On: logging in needs a code from your authenticator app.'
          : 'Off: logging in needs only your password. Set up an authenticator below to turn it on.',
      }),
    ];
    if (account.two_factor && account.two_factor_required) {
      parts.push(el('p', { className: 'note', testid: 'two-factor-required', text: 'A home you belong to requires two-factor login, so it stays on.' }));
    } else if (account.two_factor) {
      const password = passwordInput('two-factor-password', 'current-password');
      const code = el('input', { type: 'text', testid: 'two-factor-code', inputmode: 'numeric', maxlength: '6', autocomplete: 'one-time-code', required: true });
      const form = el('form', { className: 'grid-fields' }, [
        field('Password', password),
        field('Code from your app', code),
        el('button', { type: 'submit', className: 'danger', testid: 'two-factor-off', text: 'Turn off two-factor' }),
      ]);
      form.addEventListener('submit', (event) => {
        event.preventDefault();
        this.app.run(async () => {
          await this.app.api.disableTotp(password.value, code.value.trim());
          await this.refreshTwoFactor();
          this.app.status.success('Two-factor login is off.');
        });
      });
      parts.push(form);
    }
    this.twoFactor.replaceChildren(...parts);
  }

  async refreshTwoFactor() {
    this.app.account = await this.app.api.getAccount();
    this.fillTwoFactor();
  }

  recoveryForm() {
    const password = passwordInput('recovery-password', 'current-password');
    const output = el('div');
    const form = el('form', { className: 'subpanel' }, [
      el('h3', { text: 'Recovery codes' }),
      el('p', { className: 'muted', text: 'New codes replace all old ones.' }),
      field('Password', password),
      el('button', { type: 'submit', testid: 'recovery-generate', text: 'Make new recovery codes' }),
      output,
    ]);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      this.app.run(async () => {
        const result = await this.app.api.newRecoveryCodes(password.value);
        password.value = '';
        output.replaceChildren(
          el('p', { className: 'note', text: 'Save these somewhere safe. Each works once; they are not shown again.' }),
          codeList(result.recovery_codes, 'recovery-codes'),
        );
        this.app.status.success('New recovery codes made.');
      });
    });
    return form;
  }

  totpForm() {
    const password = passwordInput('totp-password', 'current-password');
    const code = el('input', { type: 'text', testid: 'totp-code', inputmode: 'numeric', maxlength: '6', autocomplete: 'one-time-code' });
    const step2 = el('div', { hidden: true });
    const on = this.app.account.two_factor;
    const start = el('form', { className: 'subpanel' }, [
      el('h3', { text: 'Authenticator app' }),
      el('p', {
        className: 'muted',
        text: on
          ? 'Move your login codes to a new phone or app. The old app keeps working until you confirm.'
          : 'Set up an authenticator app to turn two-factor login on.',
      }),
      field('Password', password),
      el('button', { type: 'submit', testid: 'totp-start', text: on ? 'Set up a new authenticator' : 'Set up an authenticator' }),
      step2,
    ]);
    start.addEventListener('submit', (event) => {
      event.preventDefault();
      this.app.run(async () => {
        const result = await this.app.api.startTotpReset(password.value);
        password.value = '';
        const confirm = el('button', {
          type: 'button', testid: 'totp-confirm', text: 'Confirm',
          onclick: () => this.app.run(async () => {
            const done = await this.app.api.confirmTotpReset(code.value.trim());
            code.value = '';
            step2.replaceChildren();
            step2.hidden = !done.recovery_codes;
            if (done.recovery_codes) {
              // Two-factor was off: these are the first recovery codes.
              step2.append(
                el('p', { className: 'note', text: 'Save these recovery codes somewhere safe. Each works once; they are not shown again.' }),
                codeList(done.recovery_codes, 'totp-recovery-codes'),
              );
            }
            await this.refreshTwoFactor();
            this.app.status.success('Authenticator set up. Logging in now needs its code.');
          }),
        });
        step2.replaceChildren(
          el('p', { className: 'note', text: 'Scan this code with the new app, then enter the code it shows.' }),
          el('img', { className: 'qr', testid: 'totp-qr', src: result.qr_svg, alt: 'QR code to scan with the new authenticator app' }),
          el('p', { className: 'muted', text: 'Or type this key:' }),
          el('p', { className: 'secret', testid: 'totp-secret', text: groupSecret(result.secret) }),
          el('a', { className: 'link', href: result.otpauth_uri, text: 'Open in authenticator app' }),
          field('Code from the new app', code),
          confirm,
        );
        step2.hidden = false;
      });
    });
    return start;
  }

  async loadSessions() {
    const sessions = await this.app.api.getSessions();
    const rows = sessions.map((s) => {
      const row = el('div', { className: 'session-row', testid: 'session-row', 'data-current': String(s.current) }, [
        el('div', {}, [
          el('strong', { text: s.current ? 'This device' : (s.ip_address || 'Unknown address') }),
          el('p', { className: 'muted', text: `Last active ${formatTime(s.last_activity)} · since ${formatTime(s.created_at)}` }),
        ]),
      ]);
      if (!s.current) {
        row.append(el('button', {
          type: 'button', className: 'secondary', testid: 'session-end', text: 'Log out',
          onclick: () => this.app.run(async () => {
            await this.app.api.endSession(s.id);
            await this.loadSessions();
            this.app.status.success('That device was logged out.');
          }),
        }));
      }
      return row;
    });
    const endOthers = el('button', {
      type: 'button', className: 'secondary', testid: 'sessions-end-others', text: 'Log out all other devices',
      disabled: sessions.length < 2,
      onclick: () => this.app.run(async () => {
        await this.app.api.endOtherSessions();
        await this.loadSessions();
        this.app.status.success('All other devices were logged out.');
      }),
    });
    this.sessionsBox.replaceChildren(...rows, endOthers);
  }
}

window.AccountSection = AccountSection;
