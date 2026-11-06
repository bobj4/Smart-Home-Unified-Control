/**
 * Settings > Integrations > ratgdo (operators and up): add a garage door
 * opener with a ratgdo (ESPHome firmware) by its address, or remove one.
 */

class RatgdoPanel {
  constructor(app) {
    this.app = app;
  }

  async render(container) {
    this.list = el('div', { className: 'member-list' });
    container.append(el('div', { className: 'subpanel', testid: 'ratgdo-doors' }, [
      el('h3', { text: 'Garage doors (ratgdo)' }),
      el('p', { className: 'muted', text: 'For a ratgdo running ESPHome, with its web server on and no web login. Its address is shown in your router or the ESPHome dashboard.' }),
      this.list,
      this.addForm(),
    ]));
    await this.load();
  }

  async load() {
    const doors = await this.app.api.getDoors(this.app.home.id);
    this.list.replaceChildren(...doors.map((door) => el('div', { className: 'member-row', testid: 'ratgdo-row', 'data-device-id': door.device_id }, [
      el('div', {}, [el('strong', { text: door.name }), el('p', { className: 'muted', text: door.host })]),
      el('button', {
        type: 'button', className: 'danger', testid: 'ratgdo-remove', text: 'Remove',
        onclick: () => this.app.run(async () => {
          await this.app.api.removeDoor(this.app.home.id, door.device_id);
          await this.load();
          this.app.status.success(`${door.name} removed.`);
        }),
      }),
    ])));
    if (doors.length === 0) this.list.append(el('p', { className: 'muted', text: 'No garage doors added yet.' }));
  }

  addForm() {
    const name = el('input', { type: 'text', testid: 'ratgdo-name', maxlength: '100', required: true, value: 'Garage door' });
    const host = el('input', { type: 'text', testid: 'ratgdo-host', placeholder: '192.168.1.80', required: true });
    const note = formNote('ratgdo-note');
    const form = el('form', { className: 'row', testid: 'ratgdo-add-form' }, [
      field('Name', name), field('IP address', host),
      el('button', { type: 'submit', testid: 'ratgdo-add', text: 'Add garage door' }), note,
    ]);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      runWithNote(this.app, note, 'Asking the ratgdo…', async () => {
        const added = await this.app.api.addDoor(this.app.home.id, { name: name.value.trim(), host: host.value.trim() });
        host.value = '';
        await this.load();
        this.app.status.success(`${added.name} added.`);
      });
    });
    return form;
  }
}

window.RatgdoPanel = RatgdoPanel;
