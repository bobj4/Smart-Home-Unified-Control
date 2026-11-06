/**
 * Settings view: a menu of categories on the left (on top on a phone) and
 * one category at a time on the right, at #/settings/<category>.
 * Categories a role may not use are not shown.
 */

const SETTINGS_SECTIONS = [
  { id: 'account', label: 'My account', intro: 'Password, recovery codes, authenticator app and logged-in devices.' },
  { id: 'admin', label: 'Admin', intro: 'Users, home name, login rules, email server and HTTPS.', role: 'admin' },
  { id: 'devices', label: 'Devices', intro: 'Rename devices and choose their room.', role: 'operator' },
  { id: 'integrations', label: 'Integrations', intro: 'Device brands this home uses. A brand that is off accepts no commands and no new devices.', role: 'operator' },
  { id: 'safety', label: 'Safety limits', intro: 'Thermostats and water heaters only accept targets inside these limits. New devices start at the default target.', role: 'operator' },
  { id: 'activity', label: 'Activity log', intro: 'Logins, setting changes and device commands, newest first.', role: 'admin' },
];

/** What a page shows: its text and the values of its fields. */
function pageSignature(panel) {
  if (!panel) return '';
  const values = [...panel.querySelectorAll('input, select, textarea')].map((f) => (f.type === 'checkbox' ? String(f.checked) : f.value));
  return `${panel.textContent}\u0000${values.join('\u0001')}`;
}

class SettingsView {
  constructor(app, root) {
    this.app = app;
    this.root = root;
    this.account = new AccountSection(app);
    this.members = new MembersSection(app);
    this.home = new HomeSettings(app);
    this.shown = null;
  }

  visibleSections() {
    return SETTINGS_SECTIONS.filter((s) => !s.role || this.app.can(s.role));
  }

  /** `live`: the background refresh, which never replaces what someone is
   * typing into, and swaps the page in only once it is built. */
  async load(sectionId, { live = false } = {}) {
    const sections = this.visibleSections();
    const current = sections.find((s) => s.id === sectionId) || sections[0];
    // "#/settings" and "#/settings/account" show the same page: draw it once,
    // so a second draw never replaces a form someone is typing into.
    const key = `${this.app.home.id}/${current.id}`;
    if (this.shown === key) return;
    this.shown = key;
    const menu = el('nav', { className: 'settings-menu', testid: 'settings-menu', 'aria-label': 'Settings' },
      sections.map((s) => el('a', {
        href: `#/settings/${s.id}`,
        className: `settings-link${s.id === current.id ? ' active' : ''}`,
        testid: `settings-nav-${s.id}`,
        'aria-current': s.id === current.id ? 'page' : undefined,
        text: s.label,
      })));
    const panel = section(`settings-${current.id}`, current.label, current.intro);
    // Live refresh redraws the page only while nothing has been typed.
    this.dirty = false;
    panel.addEventListener('input', () => { this.dirty = true; });
    const page = [menu, el('div', { className: 'settings-content' }, [panel])];
    const redraw = key === this.drawn;
    this.drawn = key;
    const token = (this.drawToken || 0) + 1;
    this.drawToken = token;
    if (redraw && live) {
      // Built off screen and swapped in whole: no blank page, no jump. Not
      // swapped if someone typed meanwhile or a newer draw started, nor
      // when nothing changed (the page stays exactly as it is).
      const before = this.panel;
      await this.renderSection(current.id, panel);
      if (token !== this.drawToken || this.dirty || pageSignature(before) === pageSignature(panel)) {
        if (before && before.isConnected) {
          this.panel = before;
          this.formsAtDraw = before.querySelectorAll('form').length;
        }
        if (token === this.drawToken) this.shown = key; // still showing this page
        return;
      }
      const { scrollX, scrollY } = window; // where it is now, not when loading began
      this.root.replaceChildren(...page);
      window.scrollTo(scrollX, scrollY);
      return;
    }
    // Redrawing after a change (a switch, a new room): hold the page's height
    // while it reloads, so the browser does not scroll back to the top.
    if (redraw) this.root.style.minHeight = `${this.root.offsetHeight}px`;
    this.root.replaceChildren(...page);
    try {
      await this.renderSection(current.id, panel);
    } finally {
      if (redraw && token === this.drawToken) this.root.style.minHeight = '';
    }
  }

  /** Admin: Users first, then the home and login settings. */
  async renderAdmin(panel) {
    const steps = await setupStepsPanel(this.app);
    if (steps) panel.append(steps);
    const users = el('div', { className: 'subpanel', testid: 'settings-members' }, [el('h3', { text: 'Users' })]);
    panel.append(users);
    await this.members.render(users);
    await new AdminSection(this.app).render(panel);
  }

  /** Draw a page; pages with several sections get foldable headings. */
  async renderSection(id, panel) {
    await this.renderSectionBody(id, panel);
    makeCollapsible(this.app, id, panel);
    this.panel = panel;
    this.formsAtDraw = panel.querySelectorAll('form').length;
  }

  /** Every page updates by itself (every third refresh, the Integrations
   * page every refresh), but never while someone is typing, editing in
   * place, has a popup open or is looking at a code shown once. */
  liveDue() {
    this.ticks = (this.ticks || 0) + 1;
    const panel = this.panel;
    if (!panel || !panel.isConnected || this.dirty) return false;
    if (!panel.dataset.testid.endsWith('integrations') && this.ticks % 3 !== 0) return false;
    if (panel.querySelector('.secret:not([hidden]), .codes, img.qr, [data-testid$="-confirm"]')) return false;
    if (panel.querySelectorAll('form').length !== this.formsAtDraw) return false;
    return !document.querySelector('.overlay:not([hidden])');
  }

  renderSectionBody(id, panel) {
    switch (id) {
      case 'account': return this.account.render(panel);
      case 'devices': return this.home.renderDevices(panel);
      case 'integrations': return this.home.renderIntegrations(panel);
      case 'safety': return this.home.renderSafety(panel);
      case 'activity': return this.home.renderActivity(panel);
      case 'admin': return this.renderAdmin(panel);
      default: return null;
    }
  }
}

window.SettingsView = SettingsView;
