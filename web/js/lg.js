/**
 * Settings > Integrations > LG TV (operators and up): add an LG webOS TV by
 * its address, pair it (a prompt on the TV: accept it with the remote), or
 * remove it. The MAC address lets the app turn the TV on.
 */

class LgPanel {
  constructor(app) {
    this.app = app;
  }

  async render(container) {
    this.list = el('div', { className: 'member-list' });
    container.append(el('div', { className: 'subpanel', testid: 'lg-tvs' }, [
      el('h3', { text: 'LG TVs' }),
      el('p', { className: 'muted', text: 'To turn the TV on from here: on the TV, Settings > General > Devices > TV Management > Quick Start+ on, and Mobile TV On on, then give its MAC address.' }),
      this.list,
      this.addForm(),
    ]));
    await this.load();
  }

  async load() {
    const tvs = await this.app.api.getLgTvs(this.app.home.id);
    this.list.replaceChildren(...tvs.map((tv) => this.row(tv)));
    if (tvs.length === 0) this.list.append(el('p', { className: 'muted', text: 'No LG TVs added yet.' }));
  }

  row(tv) {
    const note = formNote('lg-pair-note');
    return el('div', { className: 'member-row', testid: 'lg-row', 'data-device-id': tv.device_id }, [
      el('div', {}, [
        el('strong', { text: tv.name }),
        el('p', { className: 'muted', testid: 'lg-paired', text: `${tv.host} · ${tv.paired ? 'Paired' : 'Not paired yet'}` }),
        note,
      ]),
      el('button', {
        type: 'button', className: 'secondary', testid: 'lg-pair', text: tv.paired ? 'Pair again' : 'Pair',
        onclick: () => runWithNote(this.app, note, 'Accept the prompt on the TV with its remote…', async () => {
          await this.app.api.pairLgTv(this.app.home.id, tv.device_id);
          await this.load();
          this.app.status.success(`${tv.name} paired.`);
        }),
      }),
      el('button', {
        type: 'button', className: 'danger', testid: 'lg-remove', text: 'Remove',
        onclick: () => this.app.run(async () => {
          await this.app.api.removeLgTv(this.app.home.id, tv.device_id);
          await this.load();
          this.app.status.success(`${tv.name} removed.`);
        }),
      }),
    ]);
  }

  addForm() {
    const name = el('input', { type: 'text', testid: 'lg-name', maxlength: '100', required: true });
    const host = el('input', { type: 'text', testid: 'lg-host', placeholder: '192.168.1.70', required: true });
    const mac = el('input', { type: 'text', testid: 'lg-mac', placeholder: 'optional, for turning on' });
    const form = el('form', { className: 'row', testid: 'lg-add-form' }, [
      field('Name', name), field('IP address', host), field('MAC address', mac),
      el('button', { type: 'submit', testid: 'lg-add', text: 'Add TV' }),
    ]);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      this.app.run(async () => {
        const body = { name: name.value.trim(), host: host.value.trim() };
        if (mac.value.trim()) body.mac = mac.value.trim();
        const added = await this.app.api.addLgTv(this.app.home.id, body);
        [name, host, mac].forEach((input) => { input.value = ''; });
        await this.load();
        this.app.status.success(`${added.name} added. Press Pair next.`);
      });
    });
    return form;
  }
}

window.LgPanel = LgPanel;
