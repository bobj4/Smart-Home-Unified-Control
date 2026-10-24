/**
 * App shell: login, logout, the home switcher, and hash routing between the
 * devices view (#/devices), settings (#/settings/<category>) and enrollment
 * (#/enroll).
 */

const VIEWS = ['devices', 'cameras', 'settings'];

class SmartHomeApp {
  constructor() {
    this.api = new SmartHomeAPI();
    this.account = null;
    this.home = null;
    this.status = new StatusBar(byTestId('status'));
    this.devices = new DevicesView(this, byTestId('view-devices'));
    this.settings = new SettingsView(this, byTestId('view-settings'));
    this.cameras = new CamerasView(this, byTestId('view-cameras'));
    this.enroll = new EnrollView(this);
    this.recover = new RecoverView(this);
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
    try {
      await action();
    } catch (error) {
      this.handleError(error);
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
    let login = '';
    try { ({ login } = await this.api.getRememberedLogin()); } catch (error) { return; }
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
    if (theme === 'light' || theme === 'dark') document.documentElement.dataset.theme = theme;
    else delete document.documentElement.dataset.theme;
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
    this.showPage('app');
    const [view, sub] = this.currentRoute();
    for (const name of VIEWS) {
      byTestId(`view-${name}`).hidden = name !== view;
      byTestId(`nav-${name}`).classList.toggle('active', name === view);
    }
    byTestId('home-name').textContent = this.home ? this.home.name : 'No home yet';
    if (!this.home) return;
    if (view === 'cameras' && !(await this.camerasAvailable())) {
      window.location.hash = '#/devices';
      return;
    }
    this.camerasAvailable();
    const loaders = { settings: () => this.settings.load(sub), cameras: () => this.cameras.load(), devices: () => this.devices.load() };
    this.run(loaders[view]);
  }

  /** Cameras is shown to operators and up, and only while Frigate is on. */
  async camerasAvailable() {
    let on = false;
    if (this.can('operator')) {
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
      });
      password.value = '';
      code.value = '';
      await this.loadAccount();
      this.status.show('', 'info');
      this.route();
    } catch (error) {
      errorEl.textContent = error.status === 429
        ? 'Too many failed attempts. Wait five minutes and try again.'
        : 'Login failed. Check your email, password and code.';
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
  }
}

document.addEventListener('DOMContentLoaded', () => {
  window.smartHomeApp = new SmartHomeApp();
});
