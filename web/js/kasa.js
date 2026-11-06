/**
 * Settings > Integrations > TP-Link Kasa (operators and up): add a Kasa
 * device by its address (a power strip adds each outlet), remove one, and
 * the TP-Link (Kasa app) login that devices with newer firmware need.
 */

class KasaPanel {
  constructor(app) {
    this.app = app;
  }

  async render(container) {
    this.box = el('div', { className: 'subpanel', testid: 'kasa-devices' });
    container.append(this.box);
    await this.load();
  }

  async load() {
    const info = await this.app.api.getKasa(this.app.home.id);
    const list = el('div', { className: 'member-list' }, info.devices.length
      ? info.devices.map((d) => el('div', { className: 'member-row', testid: 'kasa-row', 'data-device-id': d.device_id }, [
        el('div', {}, [el('strong', { text: d.name }), el('p', { className: 'muted', text: `${d.host} · ${d.model || 'Kasa'}` })]),
        el('button', {
          type: 'button', className: 'danger', testid: 'kasa-remove', text: 'Remove',
          onclick: () => this.app.run(async () => {
            await this.app.api.removeKasa(this.app.home.id, d.device_id);
            await this.load();
            this.app.status.success(`${d.name} removed.`);
          }),
        }),
      ]))
      : [el('p', { className: 'muted', text: 'No Kasa devices added yet.' })]);
    this.box.replaceChildren(
      el('h3', { text: 'TP-Link Kasa' }),
      el('p', { className: 'muted', text: 'Add each device by its IP address (in the Kasa app: the device > Settings > Device info, or your router).' }),
      list,
      this.addForm(),
      this.loginForm(info.login),
    );
  }

  addForm() {
    const host = el('input', { type: 'text', testid: 'kasa-host', placeholder: '192.168.1.90', required: true });
    const note = formNote('kasa-note');
    const form = el('form', { className: 'row' }, [
      field('IP address', host), el('button', { type: 'submit', testid: 'kasa-add', text: 'Add device' }), note,
    ]);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      runWithNote(this.app, note, 'Asking the device…', async () => {
        const added = await this.app.api.addKasa(this.app.home.id, host.value.trim());
        await this.load();
        this.app.status.success(added.length > 1 ? `${added.length} outlets added.` : `${added[0].name} added.`);
      });
    });
    return form;
  }

  loginForm(current) {
    if (current) {
      return el('div', { className: 'row', testid: 'kasa-login' }, [
        el('p', { className: 'note', text: `TP-Link login saved (${current}).` }),
        el('button', {
          type: 'button', className: 'secondary', testid: 'kasa-login-remove', text: 'Remove login',
          onclick: () => this.app.run(async () => { await this.app.api.removeKasaLogin(this.app.home.id); await this.load(); }),
        }),
      ]);
    }
    const email = el('input', { type: 'email', testid: 'kasa-email', autocomplete: 'off', required: true });
    const password = el('input', { type: 'password', testid: 'kasa-password', autocomplete: 'off', required: true });
    const form = el('form', { className: 'row', testid: 'kasa-login' }, [
      el('p', { className: 'muted', text: 'Newer firmware asks for the TP-Link (Kasa app) account the device was set up with. It is stored encrypted and never sent to the devices.' }),
      field('TP-Link email', email), field('Password', password),
      el('button', { type: 'submit', testid: 'kasa-login-save', text: 'Save login' }),
    ]);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      this.app.run(async () => {
        await this.app.api.setKasaLogin(this.app.home.id, email.value.trim(), password.value);
        await this.load();
        this.app.status.success('TP-Link login saved.');
      });
    });
    return form;
  }
}

window.KasaPanel = KasaPanel;
