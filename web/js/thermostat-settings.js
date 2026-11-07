/**
 * Thermostat settings window (the Settings button under Schedule): the Cync
 * thermostat's own settings, each changed on the thermostat and read back.
 * Each setting is asked for by name, so reading takes a few seconds; the
 * result is kept for a few minutes. A setting the thermostat does not
 * report is shown as such and cannot be changed.
 */

const THERMO_SWITCHES = [
  ['early_on', 'Early On', 'Starts heating or cooling early, so the room is at the scheduled temperature by the scheduled time.'],
  ['celsius', 'Show °C on the thermostat', 'The unit on the thermostat\'s own screen. This app keeps showing °F.'],
  ['auto_dst', 'Daylight saving time', 'The thermostat moves its clock for daylight saving time by itself.'],
];
const THERMO_INSTALLER_SWITCHES = [
  ['dehumidify', 'Dehumidify', 'Runs the air conditioning to bring the humidity down.'],
  ['heat_pump_changeover', 'Heat pump changeover', 'Which way the heat pump\'s valve is wired (O/B). The wrong setting swaps heating and cooling: change it only to match the wiring.'],
];
// [key, label, help, step, unit]
const THERMO_NUMBERS = [
  ['dehumidify_to', 'Dehumidify to', 'The humidity to bring the house down to.', 1, '%'],
  ['min_fan_runtime', 'Minimum fan run time', 'Minutes an hour the fan runs even when not heating or cooling.', 1, 'min'],
  ['temperature_offset', 'Temperature offset', 'Corrects the thermostat\'s reading (in its own unit).', 0.5, ''],
  ['humidity_offset', 'Humidity offset', 'Corrects the thermostat\'s humidity reading.', 0.5, '%'],
  ['auto_deadband', 'Auto mode gap', 'How far apart heating and cooling must be in Auto (in its own unit).', 0.5, ''],
];

// [key, label, help] for settings chosen from a list (choices come from the server).
const THERMO_CHOICES = [
  ['system_type', 'System type', 'The heating and cooling equipment the thermostat runs. The wrong type can damage it or make it run wrongly: change it only to match the equipment.'],
  ['furnace_type', 'Furnace type', 'Gas, electric or a boiler.'],
];
// Shown as the thermostat reports them (what its numbers mean is not known yet).
const THERMO_INFO = [['power_wires', 'Power wires', 'Rc, or Rc and Rh: change this in the Cync app.']];
// The installer settings in folded sub menus: [id, title, keys].
const THERMO_INSTALLER_GROUPS = [
  ['system', 'System', ['system_type', 'furnace_type', 'power_wires']],
  ['humidity', 'Humidity', ['dehumidify', 'dehumidify_to']],
  ['fan', 'Fan', ['min_fan_runtime']],
  ['calibration', 'Calibration', ['temperature_offset', 'humidity_offset']],
  ['heat-pump', 'Heat pump & Auto', ['heat_pump_changeover', 'auto_deadband']],
];

/** '-1.0F' -> -1; 3 -> 3; anything else -> null. */
function settingNumber(value) {
  if (typeof value === 'number') return value;
  const found = typeof value === 'string' ? value.match(/^(-?[0-9.]+)/) : null;
  return found ? Number(found[1]) : null;
}

class ThermostatSettingsPanel {
  constructor(view) {
    this.view = view;
    this.overlay = el('div', { className: 'overlay', hidden: true });
    this.overlay.addEventListener('click', (e) => { if (e.target === this.overlay) this.close(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !this.overlay.hidden) this.close(); });
    document.body.append(this.overlay);
  }

  path() {
    return `/homes/${encodeURIComponent(this.view.app.home.id)}/devices/${encodeURIComponent(this.device.id)}/settings`;
  }

  open(device) {
    this.device = device;
    this.opened = new Set(); // every sub menu starts folded
    this.overlay.hidden = false;
    this.load(false);
  }

  async load(refresh) {
    const { device } = this;
    this.render(el('p', { className: 'muted', testid: 'thermo-settings-loading', text: 'Asking the thermostat… this takes a few seconds.' }));
    try {
      const data = await this.view.app.api.get(`${this.path()}${refresh ? '?refresh=true' : ''}`);
      if (this.device !== device || this.overlay.hidden) return;
      this.render(this.body(data));
    } catch (error) {
      this.render(el('p', { className: 'warning', testid: 'thermo-settings-error', text: error.message }));
    }
  }

  switchRow(settings, canEdit, [key, label, help]) {
    if (typeof settings[key] !== 'boolean') {
      return el('p', { className: 'muted', testid: `thermo-setting-${key}`, text: `${label}: not reported by this thermostat.` });
    }
    const toggle = switchInput(`thermo-setting-${key}`, settings[key], label);
    toggle.disabled = !canEdit;
    toggle.addEventListener('change', () => this.change({ [key]: toggle.checked }, () => { toggle.checked = !toggle.checked; }));
    return settingRow(label, help, toggle);
  }

  numberRow(data, canEdit, [key, label, help, step, unit]) {
    const value = settingNumber(data.settings[key]);
    if (value === null) {
      return el('p', { className: 'muted', testid: `thermo-setting-${key}`, text: `${label}: not reported by this thermostat.` });
    }
    const [low, high] = (data.limits || {})[key] || [null, null];
    const input = el('input', {
      type: 'number', testid: `thermo-setting-${key}`, step: String(step), min: String(low), max: String(high), value: String(value),
      disabled: !canEdit, 'aria-label': label,
    });
    const save = el('button', {
      type: 'submit', className: 'secondary', testid: `thermo-save-${key}`, text: 'Save', disabled: !canEdit,
    });
    const form = el('form', { className: 'row' }, [input, unit ? el('span', { className: 'muted', text: unit }) : null, save]);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      this.change({ [key]: Number(input.value) }, () => { input.value = String(value); });
    });
    return settingRow(label, help, form);
  }

  choiceRow(data, canEdit, [key, label, help]) {
    const value = data.settings[key];
    const options = (data.choices || {})[key] || {};
    if (value === null || value === undefined) {
      return el('p', { className: 'muted', testid: `thermo-setting-${key}`, text: `${label}: not reported by this thermostat.` });
    }
    const select = el('select', { testid: `thermo-setting-${key}`, disabled: !canEdit, 'aria-label': label },
      Object.entries(options).map(([code, name]) => el('option', { value: code, text: name })));
    select.value = String(value);
    const save = el('button', { type: 'submit', className: 'secondary', testid: `thermo-save-${key}`, text: 'Save', disabled: !canEdit });
    const form = el('form', { className: 'row choice-row' }, [select, save]);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      if (Number(select.value) === value) return;
      this.change({ [key]: Number(select.value) }, () => { select.value = String(value); });
    });
    return el('div', { className: 'integration-row stacked' }, [el('div', {}, [el('strong', { text: label }), el('p', { className: 'muted', text: help })]), form]);
  }

  infoRow(data, [key, label, help]) {
    const value = data.settings[key];
    return settingRow(label, help, el('span', { testid: `thermo-setting-${key}`, text: value === null || value === undefined ? 'Not reported' : String(value) }));
  }

  /** One folded sub menu of installer settings; it stays open once opened
   * (while the window is open), also after a change redraws the window. */
  installerGroup(data, canEdit, [id, title, keys]) {
    const rows = keys.map((key) => {
      const pick = (list) => list.find(([k]) => k === key);
      if (pick(THERMO_INSTALLER_SWITCHES)) return this.switchRow(data.settings, canEdit, pick(THERMO_INSTALLER_SWITCHES));
      if (pick(THERMO_NUMBERS)) return this.numberRow(data, canEdit, pick(THERMO_NUMBERS));
      if (pick(THERMO_CHOICES)) return this.choiceRow(data, canEdit, pick(THERMO_CHOICES));
      return this.infoRow(data, pick(THERMO_INFO));
    });
    const box = el('details', { className: 'settings-group', testid: `thermo-group-${id}`, open: this.opened.has(id) }, [
      el('summary', { text: title }),
      ...rows,
    ]);
    box.addEventListener('toggle', () => { if (box.open) this.opened.add(id); else this.opened.delete(id); });
    return box;
  }

  body(data) {
    const { settings } = data;
    const canEdit = this.device.controllable;
    return el('div', { className: 'stack' }, [
      ...THERMO_SWITCHES.map((row) => this.switchRow(settings, canEdit, row)),
      canEdit ? null : el('p', { className: 'muted', text: 'The thermostat is offline or its integration is off: settings can be read, not changed.' }),
      el('h3', { text: 'Installer settings' }),
      el('p', { className: 'muted', text: 'Set when the thermostat was put in. Change them only if you know the system needs it.' }),
      ...THERMO_INSTALLER_GROUPS.map((group) => this.installerGroup(data, canEdit, group)),
      (data.missing || []).length ? el('p', { className: 'warning', testid: 'thermo-settings-missing', text: `The thermostat did not answer for ${data.missing.length} of the settings; read again to ask once more.` }) : null,
    ]);
  }

  /** Send one change; on failure put the control back (undo). */
  change(changes, undo) {
    this.overlay.querySelectorAll('input, button[type="submit"]').forEach((input) => { input.disabled = true; });
    this.view.app.run(async () => {
      try {
        const data = await this.view.app.api.put(this.path(), changes);
        this.render(this.body(data));
        this.view.app.status.success('The thermostat took the change.');
      } catch (error) {
        undo();
        this.overlay.querySelectorAll('input, button[type="submit"]').forEach((input) => { input.disabled = !this.device.controllable; });
        throw error;
      }
    });
  }

  render(body) {
    this.overlay.replaceChildren(el('div', { className: 'remote info-panel', testid: 'thermo-settings-panel', role: 'dialog', 'aria-label': `${this.device.name} settings` }, [
      el('div', { className: 'remote-head' }, [
        el('h2', { text: `${this.device.name} settings` }),
        el('button', { type: 'button', className: 'ghost', testid: 'thermo-settings-close', text: '✕', 'aria-label': 'Close', onclick: () => this.close() }),
      ]),
      body,
      el('button', { type: 'button', className: 'secondary', testid: 'thermo-settings-refresh', text: 'Read again', onclick: () => this.load(true) }),
    ]));
  }

  close() {
    this.overlay.hidden = true;
    this.overlay.replaceChildren();
  }
}

function thermostatSettingsPanel(view) {
  if (!view.thermostatSettingsPanel) view.thermostatSettingsPanel = new ThermostatSettingsPanel(view);
  return view.thermostatSettingsPanel;
}

window.thermostatSettingsPanel = thermostatSettingsPanel;
