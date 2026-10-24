/** Resetting a forgotten password with a code from an admin, or one sent by
 * email when an email server is set up (#/recover). */

class RecoverView {
  constructor(app) {
    this.app = app;
    this.form = document.getElementById('recover-form');
    this.error = byTestId('recover-error');
    this.form.addEventListener('submit', (e) => this.submit(e));
    byTestId('recover-email-send').addEventListener('click', () => this.emailCode());
  }

  async emailCode() {
    this.error.textContent = '';
    const login = byTestId('recover-login').value.trim();
    if (!login) {
      this.error.textContent = 'Enter your email address first.';
      return;
    }
    try {
      await this.app.api.emailRecoveryCode(login);
      byTestId('recover-email-sent').hidden = false;
    } catch (error) {
      this.error.textContent = error.message;
    }
  }

  reset() {
    this.form.reset();
    this.form.hidden = false;
    byTestId('recover-done').hidden = true;
    this.error.textContent = '';
    byTestId('recover-rules').textContent = passwordRulesText(this.app.loginOptions);
    byTestId('recover-email-send').hidden = !(this.app.loginOptions && this.app.loginOptions.email_recovery);
    byTestId('recover-email-sent').hidden = true;
  }

  async submit(event) {
    event.preventDefault();
    this.error.textContent = '';
    const password = byTestId('recover-password').value;
    if (password !== byTestId('recover-password-confirm').value) {
      this.error.textContent = 'The passwords do not match.';
      return;
    }
    try {
      await this.app.api.recover(byTestId('recover-login').value.trim(), byTestId('recover-code').value.trim(), password);
      this.form.reset();
      this.form.hidden = true;
      byTestId('recover-done').hidden = false;
    } catch (error) {
      this.error.textContent = error.status === 404 ? 'That code is not valid for this account.' : error.message;
    }
  }
}

window.RecoverView = RecoverView;
