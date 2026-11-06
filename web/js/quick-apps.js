/**
 * A TV tile's ⋯ menu (operators and admins, 2016+ Samsung TVs): choose up to
 * six of the apps installed on the TV for the remote's quick buttons. None
 * chosen = the usual six (Netflix, YouTube, ...).
 */

const MAX_QUICK_APPS = 6;

class QuickAppsPanel {
  constructor(app) {
    this.app = app;
    this.device = null;
    this.overlay = el('div', { className: 'overlay', hidden: true });
    this.overlay.addEventListener('click', (e) => { if (e.target === this.overlay) this.close(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && this.device) this.close(); });
    document.body.append(this.overlay);
  }

  /** The ⋯ button for a TV tile's head, or null when it does not apply. */
  menuButton(device) {
    if (device.integration !== 'samsung_tv' || device.protocol !== 'tizen' || !this.app.can('operator')) return null;
    return el('button', {
      type: 'button', className: 'icon-button group-menu', testid: 'tv-quick-menu', text: '⋯',
      'aria-label': `${device.name}: quick apps`, title: 'Quick apps', onclick: () => this.open(device),
    });
  }

  async open(device) {
    this.device = device;
    this.chosen = (device.quick_apps || []).map((a) => ({ ...a }));
    this.error = el('p', { className: 'error', testid: 'quick-apps-error', role: 'alert' });
    this.list = el('div', { className: 'quick-apps-list', testid: 'quick-apps-list' }, [el('p', { className: 'muted', text: 'Asking the TV for its apps...' })]);
    this.count = el('p', { className: 'muted', testid: 'quick-apps-count' });
    this.overlay.replaceChildren(el('div', { className: 'remote quick-apps', testid: 'quick-apps-panel', role: 'dialog', 'aria-label': `${device.name} quick apps` }, [
      el('div', { className: 'remote-head' }, [
        el('h2', { text: 'Quick apps' }),
        el('button', { type: 'button', className: 'ghost', testid: 'quick-apps-close', text: '✕', 'aria-label': 'Close', onclick: () => this.close() }),
      ]),
      el('p', { className: 'muted', text: `Up to ${MAX_QUICK_APPS} apps for the buttons on ${device.name}'s remote. None = the usual six.` }),
      this.count, this.list, this.error,
      el('div', { className: 'remote-row' }, [
        el('button', { type: 'button', className: 'secondary', testid: 'quick-apps-reset', text: 'Use the usual six', onclick: () => this.save([]) }),
        el('button', { type: 'button', testid: 'quick-apps-save', text: 'Save', onclick: () => this.save(this.chosen) }),
      ]),
    ]));
    this.overlay.hidden = false;
    this.renderCount();
    try {
      const apps = await this.app.api.getTvApps(this.app.home.id, device.id);
      if (this.device === device) this.renderList(apps);
    } catch (error) {
      if (this.device !== device) return;
      this.list.replaceChildren();
      this.error.textContent = `${error.message}. The TV must be on.`;
    }
  }

  renderCount() {
    this.count.textContent = `${this.chosen.length} of ${MAX_QUICK_APPS} chosen`;
  }

  renderList(apps) {
    // Chosen apps the TV did not list (uninstalled, or off the list) stay choosable.
    const known = new Set(apps.map((a) => a.id));
    const all = [...this.chosen.filter((a) => !known.has(a.id)), ...apps];
    if (!all.length) {
      this.list.replaceChildren(el('p', { className: 'muted', text: 'The TV did not list any apps.' }));
      return;
    }
    const boxes = all.map((entry) => {
      const box = el('input', { type: 'checkbox', testid: `quick-app-${entry.id}`, checked: this.chosen.some((a) => a.id === entry.id) });
      box.addEventListener('change', () => {
        if (box.checked) this.chosen.push({ id: entry.id, name: entry.name });
        else this.chosen = this.chosen.filter((a) => a.id !== entry.id);
        this.renderCount();
        this.limit(boxes);
      });
      return box;
    });
    this.list.replaceChildren(...all.map((entry, i) => el('label', { className: 'check' }, [boxes[i], ` ${entry.name}`])));
    this.limit(boxes);
  }

  /** With six chosen, the rest cannot be ticked. */
  limit(boxes) {
    const full = this.chosen.length >= MAX_QUICK_APPS;
    boxes.forEach((box) => { box.disabled = full && !box.checked; });
  }

  save(apps) {
    const device = this.device;
    return this.app.run(async () => {
      await this.app.api.setQuickApps(this.app.home.id, device.id, apps);
      this.close();
      this.app.status.success(`${device.name}: quick apps saved.`);
      await this.app.devices.load();
    });
  }

  close() {
    this.device = null;
    this.overlay.hidden = true;
    this.overlay.replaceChildren();
  }
}

window.QuickAppsPanel = QuickAppsPanel;
