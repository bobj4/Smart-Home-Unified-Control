/**
 * Device groups on the Devices page: a card per group switches every device
 * in it together (with a brightness slider when it has lights). The ⋯ button
 * opens a window with the group's devices for one-by-one control.
 */

class GroupsUI {
  constructor(app) {
    this.app = app;
    this.group = null;
    this.overlay = el('div', { className: 'overlay', hidden: true });
    this.overlay.addEventListener('click', (e) => { if (e.target === this.overlay) this.close(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && this.group) this.close(); });
    document.body.append(this.overlay);
  }

  /** "Make a group" link while the home has none (operators and admins). */
  hint(groups) {
    if (groups.length || !this.app.can('operator')) return null;
    return el('p', { className: 'muted', testid: 'groups-hint' }, [
      el('a', { href: '#/settings/devices', testid: 'groups-make', text: 'Make a group' }),
      ' to switch several lights or plugs together (for example the ceiling lights).',
    ]);
  }

  /** Groups in a section of their own (Admin > "Show grouped devices"). */
  section(groups) {
    if (groups.length === 0) return this.hint(groups);
    return el('section', { className: 'room', testid: 'groups' }, [
      el('h2', { text: 'Groups' }),
      el('div', { className: 'device-grid' }, groups.map((g) => this.app.devices.groupTile(g))),
    ]);
  }

  command(group, name, payload = {}) {
    const card = document.querySelector(`[data-testid="group-card"][data-group-id="${CSS.escape(group.id)}"]`);
    if (card) card.dataset.busy = 'true';
    return this.app.run(async () => {
      let result;
      try {
        result = await this.app.api.groupCommand(this.app.home.id, group.id, name, payload);
      } finally {
        await this.app.devices.load();
      }
      const failed = result.results.filter((r) => r.ok === false);
      if (failed.length) {
        this.app.status.error(`${group.name}: ${failed.length} device${failed.length === 1 ? '' : 's'} did not respond (${failed[0].detail}).`);
      } else {
        this.app.status.success(`${group.name}: done.`);
      }
    });
  }

  open(group) {
    this.group = group;
    this.overlay.hidden = false;
    this.renderWindow(this.app.devices.lastDevices || []);
  }

  close() {
    this.group = null;
    this.overlay.hidden = true;
    this.overlay.replaceChildren();
  }

  /** Called after every reload, so the window shows fresh states. */
  refresh(groups, devices) {
    if (!this.group) return;
    this.group = groups.find((g) => g.id === this.group.id) || null;
    if (!this.group) {
      this.close();
      return;
    }
    this.renderWindow(devices);
  }

  renderWindow(devices) {
    const byId = new Map(devices.map((d) => [d.id, d]));
    const members = this.group.device_ids.map((id) => byId.get(id)).filter(Boolean);
    this.overlay.replaceChildren(el('div', { className: 'remote group-panel', testid: 'group-panel', role: 'dialog', 'aria-label': this.group.name }, [
      el('div', { className: 'remote-head' }, [
        el('h2', { text: this.group.name }),
        el('button', { type: 'button', className: 'ghost', testid: 'group-close', text: '✕', 'aria-label': 'Close', onclick: () => this.close() }),
      ]),
      members.length
        ? el('div', { className: 'device-grid' }, members.map((d) => this.app.devices.card(d)))
        : el('p', { className: 'muted', text: 'No devices in this group yet (choose its devices in Settings > Devices).' }),
    ]));
  }
}

window.GroupsUI = GroupsUI;
