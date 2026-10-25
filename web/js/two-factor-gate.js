/**
 * Two-factor setup page. When a home the person belongs to requires
 * two-factor login and theirs is off, logging in works with the password
 * alone, but this page is all they see until an authenticator is set up.
 * (The server refuses every home request meanwhile; this only says why.)
 * Steps: confirm the password, scan the QR code and enter a code, save the
 * recovery codes, continue into the app.
 */

class TwoFactorGate {
  constructor(app) {
    this.app = app;
    this.card = byTestId('twofactor-card');
  }

  show() {
    const password = el('input', { type: 'password', testid: 'gate-password', autocomplete: 'current-password', required: true });
    const start = el('form', { className: 'gate-step' }, [
      el('p', { text: 'First, confirm your password.' }),
      field('Password', password),
      el('button', { type: 'submit', testid: 'gate-start', text: 'Show the QR code' }),
    ]);
    start.addEventListener('submit', (event) => {
      event.preventDefault();
      this.attempt(async () => {
        const result = await this.app.api.startTotpReset(password.value);
        password.value = '';
        start.replaceWith(this.scanStep(result));
      });
    });
    this.error = el('p', { className: 'error', testid: 'gate-error', role: 'alert' });
    this.card.replaceChildren(
      el('h1', { text: 'Set up two-factor login' }),
      el('p', {
        className: 'note',
        text: 'A home you belong to requires two-factor login. Set up an authenticator app (for example Google Authenticator, Microsoft Authenticator or 1Password) to continue.',
      }),
      start,
      this.error,
      el('button', { type: 'button', className: 'ghost', testid: 'gate-logout', text: 'Log out', onclick: () => this.app.logout() }),
    );
  }

  scanStep(result) {
    const code = el('input', { type: 'text', testid: 'gate-code', inputmode: 'numeric', maxlength: '6', autocomplete: 'one-time-code', required: true });
    const form = el('form', { className: 'gate-step' }, [
      el('p', { text: 'Scan this code with your authenticator app, then enter the 6-digit code it shows.' }),
      el('img', { className: 'qr', testid: 'gate-qr', src: result.qr_svg, alt: 'QR code to scan with your authenticator app' }),
      el('p', { className: 'muted', text: 'Or type this key:' }),
      el('p', { className: 'secret', testid: 'gate-secret', text: groupSecret(result.secret) }),
      el('a', { className: 'link', href: result.otpauth_uri, text: 'Open in authenticator app' }),
      field('Code from the app', code),
      el('button', { type: 'submit', testid: 'gate-confirm', text: 'Turn on two-factor login' }),
    ]);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      this.attempt(async () => {
        const done = await this.app.api.confirmTotpReset(code.value.trim());
        form.replaceWith(this.codesStep(done.recovery_codes || []));
      });
    });
    return form;
  }

  codesStep(codes) {
    return el('div', { className: 'gate-step', testid: 'gate-done' }, [
      el('p', { className: 'note', text: 'Two-factor login is on. From now on, logging in needs a code from your app.' }),
      codes.length ? el('p', { text: 'Save these recovery codes somewhere safe. Each works once, if you lose your phone. They are not shown again.' }) : null,
      codes.length ? codeList(codes, 'gate-recovery-codes') : null,
      el('button', { type: 'button', testid: 'gate-continue', text: 'Continue', onclick: () => this.finish() }),
    ]);
  }

  async finish() {
    await this.attempt(async () => {
      await this.app.loadAccount();
      this.app.route();
    });
  }

  async attempt(action) {
    this.error.textContent = '';
    try {
      await action();
    } catch (error) {
      if (error instanceof AuthError) {
        this.app.account = null;
        this.app.route();
        return;
      }
      this.error.textContent = error.message;
    }
  }
}

window.TwoFactorGate = TwoFactorGate;
