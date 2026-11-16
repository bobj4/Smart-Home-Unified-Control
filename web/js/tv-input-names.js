/**
 * A TV tile's ⋯ menu (operators and admins): Name inputs (any TV) and
 * Quick apps (2016+ Samsung TVs, quick-apps.js). Named inputs (HDMI 2 =
 * "PlayStation") show in the remote's Input list when SmartThings does not
 * name them; choosing one switches by remote key, on the home network.
 */

const NAMED_INPUTS = [['hdmi1', 'HDMI 1'], ['hdmi2', 'HDMI 2'], ['hdmi3', 'HDMI 3'], ['hdmi4', 'HDMI 4'], ['usb', 'USB']];

/** [id, shown] for the remote: "PlayStation (HDMI 2)" once named. */
function namedTvInputs(device) {
  const names = (device && device.input_names) || {};
  return TV_INPUTS.map(([id, label]) => [id, names[id] ? `${names[id]} (${label})` : label]);
}

class TvMenu {
  constructor(app, quickApps) {
    this.app = app;
    this.quickApps = quickApps;
    this.device = null;
    this.overlay = el('div', { className: 'overlay', hidden: true });
    this.overlay.addEventListener('click', (e) => { if (e.target === this.overlay) this.close(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && this.device) this.close(); });
    document.body.append(this.overlay);
  }

  /** The ⋯ button for a TV tile's head (operators and admins), else null. */
  menuButton(device) {
    if (device.type !== 'tv' || !this.app.can('operator')) return null;
    return el('button', {
      type: 'button', className: 'icon-button group-menu', testid: 'tv-quick-menu', text: '⋯',
      'aria-label': `${device.name}: settings`, title: 'TV settings', onclick: () => this.open(device),
    });
  }

  dialog(device, title, children) {
    this.device = device;
    this.overlay.replaceChildren(el('div', { className: 'remote tv-menu', testid: 'tv-menu', role: 'dialog', 'aria-label': `${device.name}: ${title}` }, [
      el('div', { className: 'remote-head' }, [
        el('h2', { text: title }),
        el('button', { type: 'button', className: 'ghost', testid: 'tv-menu-close', text: '✕', 'aria-label': 'Close', onclick: () => this.close() }),
      ]),
      ...children,
    ]));
    this.overlay.hidden = false;
  }

  open(device) {
    const quick = device.integration === 'samsung_tv' && device.protocol === 'tizen';
    this.dialog(device, device.name, [
      el('button', { type: 'button', className: 'secondary', testid: 'tv-menu-input-names', text: 'Name inputs', onclick: () => this.inputNames(device) }),
      quick ? el('button', {
        type: 'button', className: 'secondary', testid: 'tv-menu-quick-apps', text: 'Quick apps',
        onclick: () => { this.close(); this.quickApps.open(device); },
      }) : '',
    ]);
  }

  inputNames(device) {
    const names = device.input_names || {};
    const boxes = NAMED_INPUTS.map(([id, label]) => [id, label, el('input', {
      type: 'text', maxlength: '30', testid: `input-name-${id}`, value: names[id] || '', placeholder: label, 'aria-label': `Name for ${label}`,
    })]);
    const form = el('form', { className: 'input-names', testid: 'input-names-form' }, [
      el('p', { className: 'muted', text: `What is on each of ${device.name}'s inputs (e.g. HDMI 2: PlayStation), for its remote. Blank: just its number.` }),
      el('div', { className: 'grid-fields' }, boxes.map(([, label, box]) => field(label, box))),
      el('button', { type: 'submit', testid: 'input-names-save', text: 'Save' }),
    ]);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      this.app.run(async () => {
        await this.app.api.setInputNames(this.app.home.id, device.id, Object.fromEntries(boxes.map(([id, , box]) => [id, box.value])));
        this.close();
        this.app.status.success(`${device.name}: input names saved.`);
        await this.app.devices.load();
      });
    });
    this.dialog(device, 'Name inputs', [form]);
    boxes[0][2].focus();
  }

  close() {
    this.device = null;
    this.overlay.hidden = true;
    this.overlay.replaceChildren();
  }
}

window.namedTvInputs = namedTvInputs;
window.TvMenu = TvMenu;
