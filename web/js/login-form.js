/**
 * The login form (part of SmartHomeApp): screen 1 asks for the name and
 * password; when that account needs a two-factor code, screen 2 asks for it
 * (with "Remember this device"). A remembered device skips screen 2.
 */

Object.assign(SmartHomeApp.prototype, {
  async login(event) {
    event.preventDefault();
    const errorEl = byTestId('login-error');
    errorEl.textContent = '';
    const password = byTestId('login-password');
    const code = byTestId('login-code');
    const second = !byTestId('login-step2').hidden;
    const remembered = second && byTestId('login-remember-device').checked;
    try {
      await this.api.login(byTestId('login-email').value.trim(), password.value, second ? code.value.trim() : '', {
        keepLoggedIn: byTestId('login-keep').checked,
        rememberMe: byTestId('login-remember').checked,
        rememberDevice: second && byTestId('login-remember-device').checked,
      });
      password.value = '';
      code.value = '';
      this.loginStep(1);
      await this.loadAccount();
      this.status.show('', 'info');
      this.route();
      if (remembered && this.deviceNamePopup) await this.deviceNamePopup.ask(); // a name is required
    } catch (error) {
      if (error.codeRequired) { this.loginStep(2); return; } // the code, on its own screen
      if (error.status === 429) errorEl.textContent = 'Too many failed attempts. Wait five minutes and try again.';
      else if (error.status === 403) errorEl.textContent = error.message; // locked: says why
      else errorEl.textContent = second ? 'That code did not work. Try again.' : 'Login failed. Check your email and password.';
    }
  },

  /** Screen 1: name and password. Screen 2: the two-factor code. */
  loginStep(step) {
    byTestId('login-step1').hidden = step !== 1;
    byTestId('login-step2').hidden = step !== 2;
    if (step === 2) byTestId('login-code').focus();
  },
});
