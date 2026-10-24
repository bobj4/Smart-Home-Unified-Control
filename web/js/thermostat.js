/**
 * Cync thermostat tile extras, under the dial: the room's temperature and
 * humidity, what the system is doing, mode, fan, Auto's cooling set point,
 * the sensors, and a Settings window with the rest. Demo thermostats (no
 * mode) only have the dial.
 */

const THERMO_MODES = { off: 'Off', heat: 'Heat', cool: 'Cool', auto: 'Auto', eco: 'Eco', emergency: 'Emergency heat' };
const THERMO_STATUS = { heating: 'Heating', cooling: 'Cooling', idle: 'Idle', off: 'Off' };
const THERMO_HOLDS = { schedule: 'Following the schedule', permanent: 'Permanent hold', temporary: 'Temporary hold' };

function degrees(value) {
  return typeof value === 'number' ? `${Number.isInteger(value) ? value : value.toFixed(1)} °F` : '—';
}

function sensorText(s) {
  const parts = [degrees(s.temperature)];
  if (typeof s.humidity === 'number') parts.push(`${s.humidity}%`);
  if (s.battery) parts.push(`battery ${s.battery} V`);
  return parts.join(' · ');
}

const HEAT_MODES = new Set(['heat', 'auto', 'emergency']);
const COOL_MODES = new Set(['cool', 'auto']);

/** Whether the dial shows, and what it sets: Off and Eco have no set point to change. */
function thermostatDialInfo(state) {
  if (!state.mode) return { show: true, label: 'target' }; // demo thermostat
  if (state.mode === 'cool') return { show: true, label: 'cool to' };
  return { show: HEAT_MODES.has(state.mode), label: 'heat to' };
}

function thermostatExtras(view, device, state) {
  if (!state.mode) return [];
  const status = state.status || 'idle';
  const parts = [el('p', { className: `heater-status ${status}`, testid: 'thermo-status', 'data-status': status, text: THERMO_STATUS[status] || status })];
  const now = [];
  if (typeof state.current_temperature === 'number') now.push(`Inside ${degrees(state.current_temperature)}`);
  if (typeof state.humidity === 'number') now.push(`${state.humidity}% humidity`);
  if (now.length) parts.push(el('p', { className: 'muted', testid: 'thermo-now', text: now.join(' · ') }));
  if (state.mode === 'eco') parts.push(el('p', { className: 'muted', testid: 'thermo-eco', text: 'Eco mode: the thermostat keeps its own energy-saving range. Change the mode to set a temperature.' }));

  const mode = el('select', { testid: 'thermo-mode', disabled: !device.controllable, 'aria-label': `${device.name} mode` },
    (state.modes || []).map((m) => el('option', { value: m, text: THERMO_MODES[m] || m })));
  mode.value = state.mode;
  mode.addEventListener('change', () => view.command(device, 'set_mode', { mode: mode.value }));
  const box = el('div', { className: 'heater-box', testid: 'thermo-controls' }, [field('Mode', mode)]);
  if (state.mode === 'auto') {
    const cool = typeof state.cool_setpoint === 'number' ? state.cool_setpoint : null;
    const step = (delta) => () => view.command(device, 'set_cool_temperature', { temperature: (cool || 75) + delta });
    box.append(el('div', { className: 'thermo-cool' }, [
      el('span', { testid: 'thermo-cool', text: `Cool to ${degrees(cool)}` }),
      el('button', { type: 'button', className: 'round', testid: 'thermo-cool-down', text: '−', 'aria-label': 'Lower cooling set point', disabled: !device.controllable, onclick: step(-1) }),
      el('button', { type: 'button', className: 'round', testid: 'thermo-cool-up', text: '+', 'aria-label': 'Raise cooling set point', disabled: !device.controllable, onclick: step(1) }),
    ]));
  }
  if (state.fan) {
    const fanOn = state.fan === 'on';
    box.append(el('button', {
      type: 'button', className: `toggle${fanOn ? ' on' : ''}`, testid: 'thermo-fan', 'aria-pressed': String(fanOn),
      disabled: !device.controllable, text: fanOn ? 'Fan: on' : 'Fan: auto', 'aria-label': `${device.name} fan`,
      onclick: () => view.command(device, 'set_fan', { fan: fanOn ? 'auto' : 'on' }),
    }));
  }
  parts.push(box);
  const sensors = (state.sensors || []).filter((s) => typeof s.temperature === 'number');
  if (sensors.length) {
    parts.push(el('div', { className: 'heater-box', testid: 'thermo-sensors' }, [
      el('strong', { text: 'Sensors' }),
      ...sensors.map((s) => el('p', { className: 'muted', text: `${s.name}: ${sensorText(s)}` })),
    ]));
  }
  parts.push(el('button', { type: 'button', className: 'secondary', testid: 'thermo-settings-open', text: 'Settings', onclick: () => thermostatPanel(view).open(device) }));
  return parts;
}

class ThermostatPanel {
  constructor(view) {
    this.view = view;
    this.overlay = el('div', { className: 'overlay', hidden: true });
    this.overlay.addEventListener('click', (e) => { if (e.target === this.overlay) this.close(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !this.overlay.hidden) this.close(); });
    document.body.append(this.overlay);
  }

  open(device) {
    const s = device.state || {};
    const line = (label, value) => el('div', { className: 'info-line' }, [el('dt', { text: label }), el('dd', { text: value })]);
    const rows = [
      ['Mode', THERMO_MODES[s.mode]],
      ['Doing now', THERMO_STATUS[s.status]],
      ['Heat to', HEAT_MODES.has(s.mode) && typeof s.heat_setpoint === 'number' ? degrees(s.heat_setpoint) : null],
      ['Cool to', COOL_MODES.has(s.mode) && typeof s.cool_setpoint === 'number' ? degrees(s.cool_setpoint) : null],
      ['Inside', typeof s.current_temperature === 'number' ? degrees(s.current_temperature) : null],
      ['Humidity', typeof s.humidity === 'number' ? `${s.humidity}%` : null],
      ['Fan', s.fan ? (s.fan === 'on' ? 'On' : 'Auto') : null],
      ['Schedule', THERMO_HOLDS[s.hold]],
      ['System', s.system],
      ['Filter use', s.filter_hours != null ? `${s.filter_hours} h${s.filter_reset ? ` since ${s.filter_reset}` : ''}` : null],
      ['Firmware', s.firmware],
      ['Wi-Fi signal', s.wifi],
    ].filter(([, value]) => value);  // only what the thermostat reports and uses now
    this.overlay.replaceChildren(el('div', { className: 'remote info-panel', testid: 'thermo-panel', role: 'dialog', 'aria-label': `${device.name} settings` }, [
      el('div', { className: 'remote-head' }, [
        el('h2', { text: device.name }),
        el('button', { type: 'button', className: 'ghost', testid: 'thermo-close', text: '✕', 'aria-label': 'Close', onclick: () => this.close() }),
      ]),
      el('dl', {}, rows.map(([label, value]) => line(label, value))),
      el('p', { className: 'muted', text: 'Schedules and installer settings are changed in the Cync app.' }),
    ]));
    this.overlay.hidden = false;
  }

  close() {
    this.overlay.hidden = true;
    this.overlay.replaceChildren();
  }
}

function thermostatPanel(view) {
  if (!view.thermostatPanel) view.thermostatPanel = new ThermostatPanel(view);
  return view.thermostatPanel;
}

window.thermostatExtras = thermostatExtras;
window.thermostatDialInfo = thermostatDialInfo;
