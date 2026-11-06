/**
 * Thermostat settings window (the Settings button under Schedule): the Cync
 * thermostat's own settings. Early On, the unit its screen shows and
 * daylight saving time can be switched; the installer settings are shown as
 * the thermostat reports them. Each setting is asked for by name, so
 * reading takes a few seconds; the result is kept for a few minutes.
 */

const THERMO_SWITCHES = [
  ['early_on', 'Early On', 'Starts heating or cooling early, so the room is at the scheduled temperature by the scheduled time.'],
  ['celsius', 'Show °C on the thermostat', 'The unit on the thermostat\'s own screen. This app keeps showing °F.'],
  ['auto_dst', 'Daylight saving time', 'The thermostat moves its clock for daylight saving time by itself.'],
];
const THERMO_INFO = [
  ['dehumidify', 'Dehumidify'], ['dehumidify_to', 'Dehumidify to (%)'], ['min_fan_runtime', 'Minimum fan run time'],
  ['temperature_offset', 'Temperature offset'], ['humidity_offset', 'Humidity offset'],
  ['auto_deadband', 'Auto mode gap (heat to cool)'], ['heat_pump_changeover', 'Heat pump changeover'],
];

function settingText(value) {
  if (value === null || value === undefined || value === '') return 'Not reported';
  if (value === true) return 'On';
  if (value === false) return 'Off';
  return String(value);
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

  body(data) {
    const { settings } = data;
    const canEdit = this.device.controllable;
    const rows = THERMO_SWITCHES.map(([key, label, help]) => {
      if (typeof settings[key] !== 'boolean') {
        return el('p', { className: 'muted', testid: `thermo-setting-${key}`, text: `${label}: not reported by this thermostat.` });
      }
      const toggle = switchInput(`thermo-setting-${key}`, settings[key], label);
      toggle.disabled = !canEdit;
      toggle.addEventListener('change', () => this.change(key, toggle));
      return settingRow(label, help, toggle);
    });
    const info = el('dl', { className: 'readings', testid: 'thermo-settings-info' }, THERMO_INFO.flatMap(([key, label]) => [
      el('dt', { text: label }), el('dd', { testid: `thermo-info-${key}`, text: settingText(settings[key]) }),
    ]));
    return el('div', { className: 'stack' }, [
      ...rows,
      canEdit ? null : el('p', { className: 'muted', text: 'The thermostat is offline or its integration is off: settings can be read, not changed.' }),
      el('h3', { text: 'Installer settings' }),
      el('p', { className: 'muted', text: 'As the thermostat reports them. Change these on the thermostat or in the Cync app.' }),
      info,
      (data.missing || []).length ? el('p', { className: 'warning', testid: 'thermo-settings-missing', text: `The thermostat did not answer for ${data.missing.length} of the settings; read again to ask once more.` }) : null,
    ]);
  }

  change(key, toggle) {
    const wanted = toggle.checked;
    this.overlay.querySelectorAll('input').forEach((input) => { input.disabled = true; });
    this.view.app.run(async () => {
      try {
        const data = await this.view.app.api.put(this.path(), { [key]: wanted });
        this.render(this.body(data));
        this.view.app.status.success('The thermostat took the change.');
      } catch (error) {
        toggle.checked = !wanted;
        this.overlay.querySelectorAll('input').forEach((input) => { input.disabled = !this.device.controllable; });
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
