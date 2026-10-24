/**
 * Settings > Admin > Users > Access (a guest's row): checkboxes for what
 * that guest may use. The server enforces these on every request.
 */

const GUEST_FLAGS = [
  ['light_power', 'Turn lights and plugs on and off'],
  ['light_settings', 'Change light brightness and colour'],
  ['cameras', 'See the cameras'],
  ['water_heater', 'Use the water heater'],
  ['show_blocked', 'Show devices they cannot use, greyed out (otherwise hidden)'],
];

class GuestAccessDialog {
  constructor(app) {
    this.app = app;
    this.overlay = el('div', { className: 'overlay', hidden: true });
    this.overlay.addEventListener('click', (e) => { if (e.target === this.overlay) this.close(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !this.overlay.hidden) this.close(); });
    document.body.append(this.overlay);
  }

  async open(member) {
    const homeId = this.app.home.id;
    const [access, devices] = await Promise.all([
      this.app.api.getGuestAccess(homeId, member.user_id),
      this.app.api.getDevices(homeId),
    ]);
    const boxes = {};
    const flagRows = GUEST_FLAGS.map(([key, label]) => {
      boxes[key] = el('input', { type: 'checkbox', testid: `guest-${key}`, checked: Boolean(access[key]) });
      return el('label', { className: 'check' }, [boxes[key], el('span', { text: label })]);
    });
    const thermostats = devices.filter((d) => d.type === 'thermostat');
    const thermoBoxes = thermostats.map((d) => {
      const box = el('input', { type: 'checkbox', testid: 'guest-thermostat', 'data-device-id': d.id, checked: access.thermostat_ids.includes(d.id) });
      return { id: d.id, box, label: el('label', { className: 'check' }, [box, el('span', { text: d.name })]) };
    });
    const save = el('button', {
      type: 'button', testid: 'guest-access-save', text: 'Save',
      onclick: () => this.app.run(async () => {
        const body = Object.fromEntries(Object.entries(boxes).map(([key, box]) => [key, box.checked]));
        body.thermostat_ids = thermoBoxes.filter((t) => t.box.checked).map((t) => t.id);
        await this.app.api.setGuestAccess(homeId, member.user_id, body);
        this.close();
        this.app.status.success(`Saved what ${member.email} can use.`);
      }),
    });
    this.overlay.replaceChildren(el('div', { className: 'remote info-panel', testid: 'guest-access', role: 'dialog', 'aria-label': `Access for ${member.email}` }, [
      el('div', { className: 'remote-head' }, [
        el('h2', { text: `Access: ${member.name || member.email}` }),
        el('button', { type: 'button', className: 'ghost', testid: 'guest-access-close', text: '✕', 'aria-label': 'Close', onclick: () => this.close() }),
      ]),
      el('div', { className: 'guest-flags' }, flagRows),
      el('h3', { text: 'Thermostats' }),
      thermoBoxes.length
        ? el('div', { className: 'guest-flags' }, thermoBoxes.map((t) => t.label))
        : el('p', { className: 'muted', text: 'This home has no thermostats.' }),
      el('div', { className: 'row' }, [
        save,
        el('button', { type: 'button', className: 'secondary', text: 'Cancel', onclick: () => this.close() }),
      ]),
    ]));
    this.overlay.hidden = false;
  }

  close() {
    this.overlay.hidden = true;
    this.overlay.replaceChildren();
  }
}

function guestAccessDialog(app) {
  if (!app.guestAccessDialog) app.guestAccessDialog = new GuestAccessDialog(app);
  return app.guestAccessDialog;
}

window.guestAccessDialog = guestAccessDialog;
