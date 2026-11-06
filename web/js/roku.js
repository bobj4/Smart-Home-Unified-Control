/**
 * Settings > Integrations > Roku TV (operators and up): add a Roku TV or
 * player by its address on the home network, or remove one. No pairing:
 * the Roku must allow "Control by mobile apps" (its network settings).
 */

class RokuPanel {
  constructor(app) {
    this.app = app;
  }

  async render(container) {
    this.list = el('div', { className: 'member-list' });
    container.append(el('div', { className: 'subpanel', testid: 'roku-tvs' }, [
      el('h3', { text: 'Roku TVs and players' }),
      el('p', { className: 'muted', text: 'On the Roku: Settings > System > Advanced system settings > Control by mobile apps > Network access: Default. Its address is under Settings > Network > About.' }),
      this.list,
      this.addForm(),
    ]));
    await this.load();
  }

  async load() {
    const tvs = await this.app.api.getRokus(this.app.home.id);
    this.list.replaceChildren(...tvs.map((tv) => this.row(tv)));
    if (tvs.length === 0) this.list.append(el('p', { className: 'muted', text: 'No Rokus added yet.' }));
  }

  row(tv) {
    return el('div', { className: 'member-row', testid: 'roku-row', 'data-device-id': tv.device_id }, [
      el('div', {}, [
        el('strong', { text: tv.name }),
        el('p', { className: 'muted', text: `${tv.host} · ${tv.model || 'Roku'}${tv.is_tv ? ' (TV)' : ' (player)'}` }),
      ]),
      el('button', {
        type: 'button', className: 'danger', testid: 'roku-remove', text: 'Remove',
        onclick: () => this.app.run(async () => {
          await this.app.api.removeRoku(this.app.home.id, tv.device_id);
          await this.load();
          this.app.status.success(`${tv.name} removed.`);
        }),
      }),
    ]);
  }

  addForm() {
    const name = el('input', { type: 'text', testid: 'roku-name', maxlength: '100', placeholder: 'optional: the Roku\'s own name' });
    const host = el('input', { type: 'text', testid: 'roku-host', placeholder: '192.168.1.60', required: true });
    const note = formNote('roku-note');
    const form = el('form', { className: 'row', testid: 'roku-add-form' }, [
      field('Name', name), field('IP address', host),
      el('button', { type: 'submit', testid: 'roku-add', text: 'Add Roku' }), note,
    ]);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      runWithNote(this.app, note, 'Asking the Roku…', async () => {
        const body = { host: host.value.trim() };
        if (name.value.trim()) body.name = name.value.trim();
        const added = await this.app.api.addRoku(this.app.home.id, body);
        name.value = '';
        host.value = '';
        await this.load();
        this.app.status.success(`${added.name} added.`);
      });
    });
    return form;
  }
}

window.RokuPanel = RokuPanel;
