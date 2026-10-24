/**
 * Settings > Integrations > Samsung TV (admin and owner): add a TV by its
 * address on the home network, pair it (someone presses Allow on the TV),
 * remove it. Older TVs (2010-2013) use the legacy protocol; 2014-2015 TVs
 * (H and J series) use the encrypted one and pair with a PIN shown on the TV.
 */

class SamsungPanel {
  constructor(app) {
    this.app = app;
  }

  async render(container) {
    this.list = el('div', { className: 'member-list' });
    container.append(el('div', { className: 'subpanel', testid: 'samsung-tvs' }, [
      el('h3', { text: 'Samsung TVs' }),
      this.list,
      this.addForm(),
    ]));
    await this.load();
  }

  async load() {
    const tvs = await this.app.api.getTvs(this.app.home.id);
    this.list.replaceChildren(...tvs.map((tv) => this.row(tv)));
    if (tvs.length === 0) this.list.append(el('p', { className: 'muted', text: 'No TVs added yet.' }));
  }

  row(tv) {
    const kind = { legacy: 'legacy protocol', encrypted: '2014-2015, PIN pairing' }[tv.protocol] || '2016 or newer';
    const pinBox = el('div', { className: 'row', testid: 'samsung-pin-box', hidden: true });
    return el('div', { className: 'member-row', testid: 'samsung-tv-row', 'data-device-id': tv.device_id }, [
      el('div', {}, [
        el('strong', { text: tv.name }),
        el('p', { className: 'muted', text: `${tv.host} · ${kind}` }),
        el('p', { className: 'muted', testid: 'samsung-paired', text: tv.paired ? 'Paired' : 'Not paired yet' }),
      ]),
      el('div', { className: 'row' }, [
        el('button', {
          type: 'button', className: 'secondary', testid: 'samsung-pair', text: tv.paired ? 'Pair again' : 'Pair',
          onclick: () => this.app.run(async () => {
            this.app.status.show(tv.protocol === 'encrypted' ? 'Asking the TV to show a PIN…' : 'Press Allow on the TV now…', 'pending');
            const result = await this.app.api.pairTv(this.app.home.id, tv.device_id);
            if (result.pin_required) {
              this.showPinForm(pinBox, tv);
              this.app.status.show('Type the PIN shown on the TV.', 'success');
              return;
            }
            await this.load();
            this.app.status.success(`${tv.name} is paired.`);
          }),
        }),
        el('button', {
          type: 'button', className: 'danger', testid: 'samsung-remove', text: 'Remove',
          onclick: () => this.app.run(async () => {
            await this.app.api.removeTv(this.app.home.id, tv.device_id);
            await this.load();
            this.app.status.success(`${tv.name} was removed.`);
          }),
        }),
      ]),
      pinBox,
    ]);
  }

  showPinForm(box, tv) {
    const pin = el('input', { type: 'text', testid: 'samsung-pin', inputmode: 'numeric', pattern: '[0-9]{4}', maxlength: '4', required: true, autocomplete: 'off', 'aria-label': 'PIN shown on the TV' });
    const form = el('form', { className: 'row' }, [
      field('PIN shown on the TV', pin),
      el('button', { type: 'submit', testid: 'samsung-pin-submit', text: 'Pair' }),
    ]);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      this.app.run(async () => {
        await this.app.api.sendTvPin(this.app.home.id, tv.device_id, pin.value.trim());
        await this.load();
        this.app.status.success(`${tv.name} is paired.`);
      });
    });
    box.replaceChildren(form);
    box.hidden = false;
    pin.focus();
  }

  addForm() {
    const name = el('input', { type: 'text', testid: 'samsung-name', maxlength: '100', required: true });
    const host = el('input', { type: 'text', testid: 'samsung-host', placeholder: '192.168.1.50', required: true });
    const mac = el('input', { type: 'text', testid: 'samsung-mac', placeholder: 'optional, for turning on' });
    const legacy = el('input', { type: 'checkbox', testid: 'samsung-legacy' });
    const encrypted = el('input', { type: 'checkbox', testid: 'samsung-encrypted' });
    legacy.addEventListener('change', () => { if (legacy.checked) encrypted.checked = false; });
    encrypted.addEventListener('change', () => { if (encrypted.checked) legacy.checked = false; });
    const form = el('form', { className: 'subpanel' }, [
      el('h3', { text: 'Add a TV' }),
      el('div', { className: 'grid-fields' }, [field('Name', name), field('IP address', host), field('MAC address', mac)]),
      el('label', { className: 'check' }, [legacy, el('span', { text: 'Older TV (2010-2013): use the legacy protocol' })]),
      el('label', { className: 'check' }, [encrypted, el('span', { text: '2014-2015 TV (H or J series): pair with a PIN' })]),
      el('button', { type: 'submit', testid: 'samsung-add', text: 'Add TV' }),
    ]);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      this.app.run(async () => {
        const tv = { name: name.value.trim(), host: host.value.trim(), protocol: legacy.checked ? 'legacy' : (encrypted.checked ? 'encrypted' : 'tizen') };
        if (mac.value.trim()) tv.mac = mac.value.trim();
        await this.app.api.addTv(this.app.home.id, tv);
        form.reset();
        await this.load();
        this.app.status.success(tv.protocol === 'encrypted'
          ? `${tv.name} added. Press Pair, then type the PIN the TV shows.`
          : `${tv.name} added. Press Pair, then Allow on the TV.`);
      });
    });
    return form;
  }
}

window.SamsungPanel = SamsungPanel;
