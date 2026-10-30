/**
 * App shell: login, logout, the home switcher, and hash routing between the
 * devices view (#/devices), settings (#/settings/<category>) and enrollment
 * (#/enroll).
 */

const VIEWS = ['devices', 'cameras', 'settings'];
// Chosen colours (My account > Appearance); anything else follows the device.
const THEMES = ['light', 'dark', 'red', 'violet'];

class SmartHomeApp {
  constructor() {
    this.api = new SmartHomeAPI();
    this.account = null;
    this.home = null;
    this.status = new StatusBar(byTestId('status'));
    // Every Save button: a "Changes Saved" popup once the server has it.
    this.toast = new Toast();
    // A device that did not follow a command: a popup with the reason.
    this.commandPopup = new CommandPopup(this);
    this.api.onCommandFailed = (failure) => this.commandPopup.show(failure);
    document.addEventListener('click', (e) => { this.lastClick = { save: isSaveButton(e.target), at: Date.now() }; }, true);
    document.addEventListener('submit', (e) => { this.lastClick = { save: isSaveButton(e.submitter), at: Date.now() }; }, true);
    this.devices = new DevicesView(this, byTestId('view-devices'));
    this.settings = new SettingsView(this, byTestId('view-settings'));
    this.cameras = new CamerasView(this, byTestId('view-cameras'));
    this.enroll = new EnrollView(this);
    this.recover = new RecoverView(this);
    this.twoFactorGate = new TwoFactorGate(this);
    this.loginOptions = null;
    this.homeSelect = byTestId('home-select');

    document.getElementById('login-form').addEventListener('submit', (e) => this.login(e));
    byTestId('logout').addEventListener('click', () => this.logout());
    this.homeSelect.addEventListener('change', () => this.selectHome(this.homeSelect.value));
    window.addEventListener('hashchange', () => this.route());
    // Live state: how often the open page re-reads devices or camera events.
    this.refreshMs = 5000;
    this.working = 0;
    document.addEventListener('visibilitychange', () => { if (!document.hidden) this.scheduleLive(0); });
    this.start();
    this.scheduleLive();
  }

  scheduleLive(delay = this.refreshMs) {
    clearTimeout(this.liveTimer);
    this.liveTimer = setTimeout(() => this.liveTick().finally(() => this.scheduleLive()), delay);
  }

  /** Re-read the open page, unless the user is in the middle of something. */
  async liveTick() {
    if (document.hidden || !this.account || !this.home || this.working > 0) return;
    if (this.account.two_factor_setup_required) return;
    const active = document.activeElement;
    if (active && active.matches('input, select, textarea')) return;
    const [view, sub] = this.currentRoute();
    try {
      if (view === 'devices' && !this.devices.lightPanel.device && !this.devices.remote.device) {
        await this.devices.load();
      } else if (view === 'settings' && sub === 'integrations' && !this.settings.dirty) {
        this.settings.shown = null; // redraw the device lists, unless someone is editing
        await this.settings.load('integrations', { live: true });
      } else if (view === 'cameras' && this.cameras.grid && this.cameras.player.hidden) {
        await this.cameras.fillEvents();
      }
    } catch (error) {
      // Missed: the next tick tries again; an expired session shows on the next action.
    }
  }

  /** Is the caller's role in the current home at least `role`? */
  can(role) {
    return Boolean(this.home) && ROLE_RANK[this.home.role] >= ROLE_RANK[role];
  }

  /** Run a user action: clear the status first, report any error after. */
  async run(action) {
    this.status.pending();
    this.working += 1;
    const click = this.lastClick;
    const saving = Boolean(click && click.save && Date.now() - click.at < 1000);
    try {
      await action();
      if (saving) this.toast.saved();
    } catch (error) {
      this.handleError(error);
      if (saving && !(error instanceof AuthError)) this.toast.failed(error.message);
    } finally {
      this.working -= 1;
    }
  }

  handleError(error) {
    if (error instanceof AuthError) {
      this.account = null;
      this.showPage('login');
      return;
    }
    this.status.error(error.message);
  }

  showPage(name) {
    byTestId('login-page').hidden = name !== 'login';
    byTestId('enroll-page').hidden = name !== 'enroll';
    byTestId('recover-page').hidden = name !== 'recover';
    byTestId('twofactor-page').hidden = name !== 'twofactor';
    byTestId('app-shell').hidden = name !== 'app';
  }

  /** "#/settings/members" -> ['settings', 'members']; unknown -> ['devices', ''] */
  currentRoute() {
    const [view, sub = ''] = window.location.hash.replace(/^#\/?/, '').split('/');
    return VIEWS.includes(view) ? [view, sub] : ['devices', ''];
  }

  async start() {
    try {
      this.loginOptions = await this.api.getLoginOptions();
      this.applyLoginOptions();
      await this.fillRememberedLogin();
      await this.loadAccount();
    } catch (error) {
      if (!(error instanceof AuthError)) this.status.error(error.message);
    }
    this.route();
  }

  /** "Remember me": the server keeps the login name in an HttpOnly cookie. */
  async fillRememberedLogin() {
    let remembered;
    try { remembered = await this.api.getRememberedLogin(); } catch (error) { return; }
    const { login, device, keep_days: keepDays } = remembered;
    byTestId('login-device-known').hidden = !device;
    // A choice the admin turned off is hidden (and unticked).
    const show = (testid, on) => {
      const box = byTestId(testid);
      box.closest('label').hidden = !on;
      if (!on) box.checked = false;
    };
    show('login-keep', keepDays !== null && keepDays !== undefined);
    show('login-remember', remembered.remember_me !== false);
    show('login-remember-device', remembered.remember_device !== false);
    byTestId('login-keep-label').textContent = keepDays
      ? `Keep me logged in for ${keepDays} day${keepDays === 1 ? '' : 's'}`
      : 'Keep me logged in';
    if (login && !byTestId('login-email').value) {
      byTestId('login-email').value = login;
      byTestId('login-remember').checked = true;
    }
  }

  /** Login-name label and the recovery link follow the admin's login rules. */
  applyLoginOptions() {
    const options = this.loginOptions;
    if (!options) return;
    const label = options.require_email ? 'Email' : 'Email or username';
    document.getElementById('login-name-label').textContent = label;
    document.getElementById('recover-login-label').textContent = label;
    byTestId('recover-link').hidden = !options.allow_recovery;
  }

  applyTheme(theme) {
    if (THEMES.includes(theme)) document.documentElement.dataset.theme = theme;
    else delete document.documentElement.dataset.theme;
    // The phone's status bar follows the page background.
    const meta = document.querySelector('meta[name="theme-color"]');
    const bg = getComputedStyle(document.documentElement).getPropertyValue('--bg').trim();
    if (meta && bg) meta.setAttribute('content', bg);
  }

  async loadAccount() {
    this.account = await this.api.getAccount();
    this.applyTheme(this.account.theme);
    const homes = this.account.homes;
    this.homeSelect.replaceChildren(...homes.map((h) => el('option', { value: h.id, text: h.name })));
    this.homeSelect.hidden = homes.length < 2;
    const keep = this.home && homes.find((h) => h.id === this.home.id);
    this.home = keep || homes[0] || null;
    if (this.home) this.homeSelect.value = this.home.id;
  }

  async route() {
    if (!this.account || this.currentRoute()[0] !== 'settings') {
      this.settings.shown = null;
      this.settings.drawn = null; // coming back draws afresh, not over the old page
    }
    if (!this.account) {
      const hash = window.location.hash;
      if (hash === '#/recover' && this.loginOptions && this.loginOptions.allow_recovery) {
        if (byTestId('recover-page').hidden) this.recover.reset();
        this.showPage('recover');
        return;
      }
      const enrolling = hash === '#/enroll';
      if (enrolling && byTestId('enroll-page').hidden) this.enroll.reset();
      this.showPage(enrolling ? 'enroll' : 'login');
      return;
    }
    if (this.account.two_factor_setup_required) {
      // A home requires two-factor and it is off: nothing else until it is on.
      if (byTestId('twofactor-page').hidden) this.twoFactorGate.show();
      this.showPage('twofactor');
      return;
    }
    this.showPage('app');
    const [view, sub] = this.currentRoute();
    for (const name of VIEWS) {
      byTestId(`view-${name}`).hidden = name !== view;
      byTestId(`nav-${name}`).classList.toggle('active', name === view);
    }
    byTestId('home-name').textContent = this.home ? this.home.name : 'No home yet';
    if (!this.home) return;
    this.api.guest = this.isGuest(); // guests use the guest routes
    if (view === 'cameras' && !(await this.camerasAvailable())) {
      window.location.hash = '#/devices';
      return;
    }
    this.camerasAvailable();
    const loaders = { settings: () => this.settings.load(sub), cameras: () => this.cameras.load(), devices: () => this.devices.load() };
    this.run(loaders[view]);
  }

  isGuest() {
    return Boolean(this.home) && this.home.role === 'guest';
  }

  /** Cameras is shown to operators and up (and guests allowed to see them),
   * and only while Frigate is on. */
  async camerasAvailable() {
    let on = false;
    if (this.isGuest()) {
      try {
        const page = await this.api.getGuestPage(this.home.id);
        on = page.access.cameras && page.integrations_on.includes('frigate');
      } catch (error) {
        on = false;
      }
    } else if (this.can('operator')) {
      try {
        const integrations = await this.api.getIntegrations(this.home.id);
        on = integrations.some((i) => i.id === 'frigate' && i.enabled);
      } catch (error) {
        on = false;
      }
    }
    byTestId('nav-cameras').hidden = !on;
    return on;
  }

  selectHome(homeId) {
    this.home = this.account.homes.find((h) => h.id === homeId) || this.home;
    this.status.show('', 'info');
    this.route();
  }

  async login(event) {
    event.preventDefault();
    const errorEl = byTestId('login-error');
    errorEl.textContent = '';
    const password = byTestId('login-password');
    const code = byTestId('login-code');
    const name = byTestId('login-email').value.trim();
    try {
      await this.api.login(name, password.value, code.value.trim(), {
        keepLoggedIn: byTestId('login-keep').checked,
        rememberMe: byTestId('login-remember').checked,
        rememberDevice: byTestId('login-remember-device').checked,
      });
      password.value = '';
      code.value = '';
      await this.loadAccount();
      this.status.show('', 'info');
      this.route();
    } catch (error) {
      if (error.status === 429) errorEl.textContent = 'Too many failed attempts. Wait five minutes and try again.';
      else if (error.status === 403) errorEl.textContent = error.message; // locked: says why
      else errorEl.textContent = 'Login failed. Check your email, password and code.';
    }
  }

  async logout() {
    try {
      await this.api.logout();
    } catch (error) {
      // Already logged out or the session expired: show the login page anyway.
    }
    this.account = null;
    this.home = null;
    this.applyTheme('system');
    this.route();
    await this.fillRememberedLogin(); // a device approved at this login
  }
}

document.addEventListener('DOMContentLoaded', () => {
  window.smartHomeApp = new SmartHomeApp();
});
