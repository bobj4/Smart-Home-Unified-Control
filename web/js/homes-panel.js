/**
 * Admin > Home: this home's name, address and icon (a built-in one, or a
 * picture of one's own), then every home of yours in your order (the top
 * one opens first on a first login; afterwards the last one viewed), with
 * "Add a Home" at the bottom.
 */

class HomesPanel {
  constructor(app) {
    this.app = app;
  }

  render() {
    this.box = el('div', { className: 'subpanel', testid: 'homes-panel' });
    this.draw();
    return this.box;
  }

  draw() {
    this.box.replaceChildren(
      el('h3', { text: 'Home' }),
      this.detailsForm(),
      el('h4', { text: 'Your homes' }),
      el('div', { className: 'homes-list', testid: 'homes-list' }, this.app.account.homes.map((h, i, all) => this.row(h, i, all))),
      this.addArea(),
    );
  }

  /** The icon choices: the built-in icons as buttons, the chosen one pressed. */
  iconChoices(chosen, onPick) {
    const buttons = Object.entries(HOME_ICONS).map(([id, [label]]) => el('button', {
      type: 'button', className: `icon-choice${id === chosen ? ' on' : ''}`, testid: 'home-icon-choice',
      'data-icon': id, title: label, 'aria-label': label, 'aria-pressed': String(id === chosen),
      onclick: () => {
        buttons.forEach((b) => {
          const on = b.dataset.icon === id;
          b.className = `icon-choice${on ? ' on' : ''}`;
          b.setAttribute('aria-pressed', String(on));
        });
        onPick(id);
      },
    }, [homeIcon({ icon: id })]));
    return el('div', { className: 'icon-choices', role: 'group', 'aria-label': 'Icon' }, buttons);
  }

  detailsForm() {
    const home = this.app.home;
    let icon = home.icon || 'house';
    const name = el('input', { type: 'text', testid: 'home-name-input', maxlength: '100', required: true, value: home.name });
    const address = el('input', { type: 'text', testid: 'home-address-input', maxlength: '300', value: home.address || '', placeholder: 'Optional', autocomplete: 'street-address' });
    const picture = el('input', { type: 'file', testid: 'home-picture-input', accept: 'image/png,image/jpeg,image/webp', 'aria-label': 'Picture of your own' });
    picture.addEventListener('change', () => {
      const file = picture.files && picture.files[0];
      if (!file) return;
      this.app.run(async () => {
        await this.app.api.setHomePicture(home.id, await shrinkPicture(file));
        await this.refresh('Picture saved: it shows at the top right.');
      });
    });
    const removePicture = home.icon_image ? el('button', {
      type: 'button', className: 'secondary', testid: 'home-picture-remove', text: 'Remove picture',
      onclick: () => this.app.run(async () => {
        await this.app.api.removeHomePicture(home.id);
        await this.refresh('Picture removed: the icon shows again.');
      }),
    }) : null;
    const form = el('form', { testid: 'home-details' }, [
      el('div', { className: 'row' }, [field('Home name', name), field('Address', address)]),
      el('p', { className: 'muted', text: 'Icon (top right):' }),
      this.iconChoices(icon, (picked) => { icon = picked; }),
      el('div', { className: 'row' }, [field('Or a picture of your own', picture), removePicture]),
      el('button', { type: 'submit', testid: 'home-name-save', text: 'Save' }),
    ]);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      this.app.run(async () => {
        const saved = await this.app.api.changeHome(home.id, { name: name.value.trim(), address: address.value.trim(), icon });
        byTestId('home-name').textContent = saved.name;
        await this.refresh(saved.name === home.name ? 'Home saved.' : `Home renamed to ${saved.name}.`);
      });
    });
    return form;
  }

  row(home, index, all) {
    const current = home.id === this.app.home.id;
    const move = (step) => this.app.run(async () => {
      const ids = all.map((h) => h.id);
      ids.splice(index, 1);
      ids.splice(index + step, 0, home.id);
      await this.app.api.setHomeOrder(ids);
      await this.refresh('Order saved.');
    });
    return el('div', { className: `home-row${current ? ' current' : ''}`, testid: 'home-row', 'data-home-id': home.id }, [
      homeIcon(home),
      el('div', {}, [
        el('strong', { text: current ? `${home.name} (this home)` : home.name }),
        el('p', { className: 'muted', text: [home.address, home.role].filter(Boolean).join(' · ') }),
      ]),
      el('div', { className: 'row' }, [
        current ? null : el('button', { type: 'button', className: 'secondary', testid: 'home-open', text: 'Open', onclick: () => this.app.selectHome(home.id) }),
        el('button', { type: 'button', className: 'ghost', testid: 'home-up', text: '↑', title: 'Move up', 'aria-label': `Move ${home.name} up`, disabled: index === 0, onclick: () => move(-1) }),
        el('button', { type: 'button', className: 'ghost', testid: 'home-down', text: '↓', title: 'Move down', 'aria-label': `Move ${home.name} down`, disabled: index === all.length - 1, onclick: () => move(1) }),
      ]),
    ]);
  }

  /** "Add a Home" at the bottom, opening a short form. */
  addArea() {
    const area = el('div', { testid: 'home-add-area' });
    const open = el('button', { type: 'button', testid: 'home-add', text: 'Add a Home' });
    open.addEventListener('click', () => {
      let icon = 'house';
      const name = el('input', { type: 'text', testid: 'home-add-name', maxlength: '100', required: true });
      const address = el('input', { type: 'text', testid: 'home-add-address', maxlength: '300', placeholder: 'Optional' });
      const form = el('form', { className: 'subpanel', testid: 'home-add-form' }, [
        el('h4', { text: 'Add a Home' }),
        el('div', { className: 'row' }, [field('Name', name), field('Address', address)]),
        this.iconChoices(icon, (picked) => { icon = picked; }),
        el('div', { className: 'row' }, [
          el('button', { type: 'submit', testid: 'home-add-save', text: 'Add home' }),
          el('button', { type: 'button', className: 'secondary', text: 'Cancel', onclick: () => area.replaceChildren(open) }),
        ]),
      ]);
      form.addEventListener('submit', (event) => {
        event.preventDefault();
        this.app.run(async () => {
          const added = await this.app.api.addHome({ name: name.value.trim(), address: address.value.trim() || null, icon });
          await this.app.loadAccount();
          this.app.selectHome(added.id);
          this.app.status.success(`${added.name} added. You are its admin; it is open now.`);
        });
      });
      area.replaceChildren(form);
      name.focus();
    });
    area.append(open);
    return area;
  }

  /** Re-read the homes (names, icons, order) and redraw. */
  async refresh(message) {
    await this.app.loadAccount();
    this.draw();
    this.app.status.success(message);
  }
}

window.HomesPanel = HomesPanel;
