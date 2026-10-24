/**
 * Joining a home with a one-time enrollment code (no login needed).
 * Step 1: check the code. Step 2: a new person sets a password and adds the
 * authenticator key; someone with an account confirms with their own
 * password and code. Step 3: show the recovery codes once.
 */

const byTestId = (id) => document.querySelector(`[data-testid="${id}"]`);

class EnrollView {
  constructor(app) {
    this.app = app;
    this.code = '';
    this.existing = false;
    this.startForm = document.getElementById('enroll-start-form');
    this.finishForm = document.getElementById('enroll-finish-form');
    this.result = document.getElementById('enroll-result');
    this.error = byTestId('enroll-error');
    this.startForm.addEventListener('submit', (e) => this.start(e));
    this.finishForm.addEventListener('submit', (e) => this.finish(e));
    byTestId('enroll-done').addEventListener('click', () => { window.location.hash = '#/'; });
  }

  reset() {
    this.code = '';
    this.startForm.reset();
    this.finishForm.reset();
    this.startForm.hidden = false;
    this.finishForm.hidden = true;
    this.result.hidden = true;
    byTestId('enroll-secret').textContent = '';
    byTestId('enroll-qr').removeAttribute('src');
    byTestId('enroll-recovery-codes').replaceChildren();
    this.error.textContent = '';
  }

  async start(event) {
    event.preventDefault();
    this.error.textContent = '';
    const code = byTestId('enroll-code').value.trim();
    try {
      const info = await this.app.api.startEnrollment(code);
      this.code = code;
      this.existing = info.existing_account;
      byTestId('enroll-email').textContent = info.email;
      byTestId('enroll-existing').hidden = !this.existing;
      document.getElementById('enroll-new').hidden = this.existing;
      document.getElementById('enroll-confirm-wrap').hidden = this.existing;
      document.getElementById('enroll-totp-wrap').hidden = this.existing && !info.two_factor;
      if (!this.existing) {
        byTestId('enroll-secret').textContent = groupSecret(info.totp_secret);
        byTestId('enroll-qr').src = info.qr_svg;
        document.getElementById('enroll-uri').href = info.otpauth_uri;
      }
      this.startForm.hidden = true;
      this.finishForm.hidden = false;
    } catch (error) {
      this.error.textContent = error.status === 429
        ? 'Too many tries. Wait five minutes and try again.'
        : 'That code is not valid. Check it, or ask an admin for a new one.';
    }
  }

  async finish(event) {
    event.preventDefault();
    this.error.textContent = '';
    const password = byTestId('enroll-password').value;
    if (!this.existing) {
      if (password !== byTestId('enroll-password-confirm').value) {
        this.error.textContent = 'The passwords do not match.';
        return;
      }
      if (password.length < 12) {
        this.error.textContent = 'Use at least 12 characters.';
        return;
      }
    }
    try {
      const done = await this.app.api.finishEnrollment(this.code, password, byTestId('enroll-totp').value.trim());
      this.finishForm.reset();
      this.finishForm.hidden = true;
      const codes = done.recovery_codes || [];
      byTestId('enroll-recovery-codes').replaceChildren(...codes.map((c) => el('li', { text: c })));
      document.getElementById('enroll-recovery').hidden = codes.length === 0;
      this.result.hidden = false;
    } catch (error) {
      this.error.textContent = error.status === 403
        ? 'Password or code is incorrect.'
        : error.message;
    }
  }
}

window.EnrollView = EnrollView;
