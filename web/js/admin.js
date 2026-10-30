/**
 * Settings > Admin (owners): the home's name, requiring two-factor login in
 * this home, and the login rules for every account (email or username,
 * password recovery, password requirements), and HTTPS: the certificate
 * and the switch (used the next time the server starts).
 */

function switchInput(testid, checked, label) {
  return el('input', { type: 'checkbox', role: 'switch', className: 'switch', testid, checked, 'aria-label': label });
}

function settingRow(title, help, control) {
  return el('div', { className: 'integration-row' }, [
    el('div', {}, [el('strong', { text: title }), el('p', { className: 'muted', text: help })]),
    control,
  ]);
}

class AdminSection {
  constructor(app) {
    this.app = app;
  }

  async render(container) {
    const [policy, security, https, email, display] = await Promise.all([
      this.app.api.getLoginPolicy(),
      this.app.api.getSecurityPolicy(this.app.home.id),
      this.app.api.getHttps(),
      this.app.api.getEmailServer(),
      this.app.api.getDisplay(this.app.home.id),
    ]);
    this.httpsBox = el('div', { className: 'subpanel', testid: 'https-box' });
    this.fillHttps(https);
    container.append(this.nameForm(), this.displayBox(display), this.twoFactor(security), this.policyForm(policy));
    await new LoginTimesPanel(this.app).render(container);
    await new LoginFailuresPanel(this.app).render(container);
    container.append(this.emailForm(email), this.httpsBox);
  }

  /** Optional: an email server, so people can get recovery codes by email. */
  emailForm(email) {
    const host = el('input', { type: 'text', testid: 'smtp-host', value: email.host || '', placeholder: 'smtp.example.com', required: true });
    const port = el('input', { type: 'number', testid: 'smtp-port', min: '1', max: '65535', value: String(email.port || 587), required: true });
    const security = el('select', { testid: 'smtp-security' }, [['starttls', 'STARTTLS (port 587)'], ['ssl', 'SSL/TLS (port 465)'], ['none', 'None (not recommended)']]
      .map(([value, text]) => el('option', { value, text })));
    security.value = email.security || 'starttls';
    const username = el('input', { type: 'text', testid: 'smtp-username', value: email.username || '', autocomplete: 'off' });
    const password = el('input', { type: 'password', testid: 'smtp-password', autocomplete: 'new-password', placeholder: email.password_saved ? 'saved (leave empty to keep)' : '' });
    const sender = el('input', { type: 'email', testid: 'smtp-from', value: email.sender || '', placeholder: 'home@example.com', required: true });
    const testTo = el('input', { type: 'email', testid: 'smtp-test-to', placeholder: 'you@example.com' });
    const form = el('form', { className: 'subpanel', testid: 'email-server' }, [
      el('h3', { text: 'Email server (optional)' }),
      el('p', { className: 'muted', text: 'With an email server and password recovery on, people with an email login can get a recovery code by email.' }),
      el('div', { className: 'grid-fields' }, [
        field('Server', host), field('Port', port), field('Security', security),
        field('Username', username), field('Password', password), field('Send from', sender),
      ]),
      el('div', { className: 'row' }, [
        el('button', { type: 'submit', testid: 'smtp-save', text: 'Save email server' }),
        field('Send a test to', testTo),
        el('button', {
          type: 'button', className: 'secondary', testid: 'smtp-test', text: 'Send test',
          onclick: () => this.app.run(async () => {
            await this.app.api.testEmailServer(testTo.value.trim());
            this.app.status.success(`Test email sent to ${testTo.value.trim()}.`);
          }),
        }),
      ]),
    ]);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      this.app.run(async () => {
        const body = {
          host: host.value.trim(), port: Number(port.value), security: security.value,
          username: username.value.trim() || null, sender: sender.value.trim(),
        };
        if (password.value) body.password = password.value;
        await this.app.api.saveEmailServer(body);
        password.value = '';
        this.app.loginOptions = await this.app.api.getLoginOptions();
        this.app.applyLoginOptions();
        this.app.status.success('Email server saved.');
      });
    });
    return form;
  }

  fillHttps(https) {
    const cert = https.certificate;
    const toggle = switchInput('https-toggle', https.enabled, 'Serve the app over HTTPS');
    toggle.disabled = !cert;
    toggle.addEventListener('change', () => this.app.run(async () => {
      try {
        this.fillHttps(await this.app.api.setHttps(toggle.checked));
      } catch (error) {
        toggle.checked = !toggle.checked;
        throw error;
      }
      this.app.status.success('Saved. Restart the server for it to take effect.');
    }));
    const certFile = el('input', { type: 'file', testid: 'https-cert-file', accept: '.pem,.crt,.cer' });
    const keyFile = el('input', { type: 'file', testid: 'https-key-file', accept: '.pem,.key' });
    const upload = el('form', { className: 'subform' }, [
      field('Certificate (PEM, with any intermediate certificates)', certFile),
      field('Private key (PEM, without a password)', keyFile),
      el('button', { type: 'submit', testid: 'https-upload', text: cert ? 'Replace certificate' : 'Upload certificate' }),
    ]);
    upload.addEventListener('submit', (event) => {
      event.preventDefault();
      this.app.run(async () => {
        if (!certFile.files[0] || !keyFile.files[0]) throw new Error('Choose both the certificate and the private key file.');
        const [certificate, privateKey] = await Promise.all([certFile.files[0].text(), keyFile.files[0].text()]);
        this.fillHttps(await this.app.api.saveHttpsCertificate(certificate, privateKey));
        this.app.status.success('Certificate saved.');
      });
    });
    const details = cert
      ? el('div', { testid: 'https-certificate' }, [
        el('p', { text: `Certificate for ${cert.hostnames.join(', ') || cert.subject}` }),
        el('p', { className: 'muted', text: `Issued by ${cert.self_signed ? 'itself (self-signed)' : cert.issuer}; valid until ${new Date(cert.not_after).toLocaleDateString()}.` }),
        el('button', {
          type: 'button', className: 'secondary', testid: 'https-remove', text: 'Remove certificate',
          onclick: () => this.app.run(async () => {
            this.fillHttps(await this.app.api.deleteHttpsCertificate());
            this.app.status.success('Certificate removed; HTTPS is off from the next restart.');
          }),
        }),
      ])
      : el('p', { className: 'muted', testid: 'https-no-certificate', text: 'No certificate uploaded.' });
    const now = https.active ? 'This page is being served over HTTPS.' : 'This page is being served over plain HTTP.';
    this.httpsBox.replaceChildren(
      el('h3', { text: 'HTTPS' }),
      settingRow('Use HTTPS', 'Needs a certificate. Takes effect when the server restarts (scripts/serve.py).', toggle),
      el('p', { className: https.restart_needed ? 'warning' : 'muted', testid: 'https-state', text: https.restart_needed ? `${now} Restart the server to apply the change.` : now }),
      details,
      upload,
    );
  }

  nameForm() {
    const name = el('input', { type: 'text', testid: 'home-name-input', maxlength: '100', required: true, value: this.app.home.name });
    const form = el('form', { className: 'subpanel' }, [
      el('h3', { text: 'Home' }),
      el('div', { className: 'row' }, [field('Home name', name), el('button', { type: 'submit', testid: 'home-name-save', text: 'Rename' })]),
    ]);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      this.app.run(async () => {
        const saved = await this.app.api.renameHome(this.app.home.id, name.value.trim());
        await this.app.loadAccount();
        byTestId('home-name').textContent = saved.name;
        this.app.status.success(`Home renamed to ${saved.name}.`);
      });
    });
    return form;
  }

  displayBox(display) {
    const toggle = switchInput('show-grouped-toggle', display.show_grouped_devices, 'Show grouped devices separately');
    toggle.addEventListener('change', () => this.app.run(async () => {
      try {
        await this.app.api.setDisplay(this.app.home.id, toggle.checked);
      } catch (error) {
        toggle.checked = !toggle.checked;
        throw error;
      }
      this.app.status.success(toggle.checked
        ? 'Groups now have their own section, and their devices are listed in their rooms too.'
        : 'Each group is now one tile in its room; its devices are under its ⋯ button.');
    }));
    return el('div', { className: 'subpanel' }, [
      el('h3', { text: 'Devices page' }),
      settingRow('Show grouped devices separately', 'Off: a group is one tile in its room and its devices are hidden there. On: groups get their own section and every device is also listed in its room.', toggle),
    ]);
  }

  twoFactor(security) {
    const toggle = switchInput('require-2fa-toggle', security.require_two_factor, 'Require two-factor login for everyone');
    toggle.addEventListener('change', () => this.app.run(async () => {
      try {
        await this.app.api.setSecurityPolicy(this.app.home.id, toggle.checked);
      } catch (error) {
        toggle.checked = !toggle.checked;
        throw error;
      }
      this.app.status.success(toggle.checked
        ? 'Everyone in this home now needs two-factor login.'
        : 'Two-factor login is now each person\'s choice.');
    }));
    return el('div', { className: 'subpanel' }, [
      el('h3', { text: 'Two-factor login' }),
      settingRow('Require two-factor login', 'Members without it can only open My account until they set it up.', toggle),
    ]);
  }

  policyForm(policy) {
    const email = switchInput('require-email-toggle', policy.require_email, 'Require an email address');
    const recovery = switchInput('allow-recovery-toggle', policy.allow_recovery, 'Allow password recovery codes');
    const minLength = el('input', { type: 'number', testid: 'pw-min-length', min: '0', max: '16', step: '1', required: true, value: String(policy.password.min_length) });
    const rules = [['pw-upper', 'upper', 'Uppercase letter'], ['pw-lower', 'lower', 'Lowercase letter'], ['pw-digit', 'digit', 'Number'], ['pw-special', 'special', 'Special character']]
      .map(([testid, key, label]) => [key, switchInput(testid, policy.password[key], `Require ${label.toLowerCase()}`), label]);
    const form = el('form', { className: 'subpanel' }, [
      el('h3', { text: 'Login rules (every account)' }),
      settingRow('Require an email address', 'When off, new accounts may use a username instead.', email),
      settingRow('Password recovery', 'Owners can give a member a one-time code to set a new password.', recovery),
      el('h3', { text: 'Password requirements' }),
      field('Minimum length (0-16; 0 = no minimum)', minLength),
      ...rules.map(([, toggle, label]) => settingRow(label, `Passwords must contain at least one ${label.toLowerCase()}.`, toggle)),
      el('p', { className: 'muted', text: 'New rules apply to passwords set from now on.' }),
      el('button', { type: 'submit', testid: 'login-policy-save', text: 'Save login rules' }),
    ]);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      this.app.run(async () => {
        const body = {
          require_email: email.checked,
          allow_recovery: recovery.checked,
          password: { min_length: Number(minLength.value), ...Object.fromEntries(rules.map(([key, toggle]) => [key, toggle.checked])) },
        };
        this.app.loginOptions = await this.app.api.setLoginPolicy(body);
        this.app.applyLoginOptions();
        this.app.status.success('Login rules saved.');
      });
    });
    return form;
  }
}

window.AdminSection = AdminSection;
