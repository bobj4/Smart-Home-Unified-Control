/**
 * Cync thermostat tile: the temperature it works from in the dial,
 * what the system is doing, the mode with the set points that mode uses
 * under it, then the fan, the hold button and the schedule, the sensors,
 * and an Info window with the rest. Demo
 * thermostats (no mode) keep the plain target dial from devices.js.
 */

const THERMO_MODES = { off: 'Off', heat: 'Heat', cool: 'Cool', auto: 'Auto', eco: 'Eco', emergency: 'Emergency heat' };
const THERMO_STATUS = { heating: 'Heating', cooling: 'Cooling', idle: 'Idle', off: 'Off' };
const THERMO_HOLDS = { schedule: 'Following schedule', temporary: 'Temporary hold', permanent: 'Permanent hold' };
const HOLD_ORDER = ['schedule', 'temporary', 'permanent']; // the hold button cycles in this order
const HEAT_MODES = new Set(['heat', 'auto', 'emergency']);
const COOL_MODES = new Set(['cool', 'auto']);

function degrees(value) {
  return typeof value === 'number' ? `${Number.isInteger(value) ? value : value.toFixed(1)} °F` : '—';
}

function sensorText(s) {
  const parts = [degrees(s.temperature)];
  if (typeof s.humidity === 'number') parts.push(`${s.humidity}%`);
  if (s.battery) parts.push(`battery ${s.battery} V`);
  return parts.join(' · ');
}

/** The dial: the temperature the thermostat works from (the sensors its schedule uses now). */
function thermostatDial(state, limits) {
  const now = typeof state.current_temperature === 'number' ? state.current_temperature : null;
  const fraction = limits && now !== null ? (now - limits.min_temperature) / (limits.max_temperature - limits.min_temperature) : 0;
  const dial = gauge(fraction, 'thermostat');
  dial.setAttribute('aria-label', 'Temperature');
  return el('div', { className: 'dial' }, [el('div', { className: 'gauge-wrap' }, [
    dial,
    el('div', { className: 'readout' }, [
      el('span', { className: 'target', testid: 'thermo-temp', text: now === null ? '--' : degrees(now) }),
    ]),
  ])]);
}

/** One set point with − and +, kept inside the safety limits. */
function setPointRow(view, device, kind, value, command, limits) {
  const usable = Boolean(limits && limits.enabled) && device.controllable;
  const start = typeof value === 'number' ? value : (limits && limits.default_target) || 70;
  const send = (delta) => () => view.command(device, command, { temperature: start + delta });
  const label = kind === 'heat' ? 'Heat to' : 'Cool to';
  return el('div', { className: 'thermo-setpoint', testid: `thermo-${kind}` }, [
    el('span', { testid: `thermo-${kind}-value`, text: `${label} ${degrees(value)}` }),
    el('button', { type: 'button', className: 'round', testid: `thermo-${kind}-down`, text: '−', 'aria-label': `Lower ${label.toLowerCase()}`, disabled: !usable || start - 1 < limits.min_temperature, onclick: send(-1) }),
    el('button', { type: 'button', className: 'round', testid: `thermo-${kind}-up`, text: '+', 'aria-label': `Raise ${label.toLowerCase()}`, disabled: !usable || start + 1 > limits.max_temperature, onclick: send(1) }),
  ]);
}

function thermostatExtras(view, device, state) {
  if (!state.mode) return [];
  const limits = view.limitsFor(device);
  const status = state.status || 'idle';
  const parts = [
    thermostatDial(state, limits),
    el('p', { className: `heater-status ${status}`, testid: 'thermo-status', 'data-status': status, text: THERMO_STATUS[status] || status }),
  ];
  if (typeof state.humidity === 'number') parts.push(el('p', { className: 'muted', testid: 'thermo-humidity', text: `${state.humidity}% humidity` }));

  const mode = el('select', { testid: 'thermo-mode', disabled: !device.controllable, 'aria-label': `${device.name} mode` },
    (state.modes || []).map((m) => el('option', { value: m, text: THERMO_MODES[m] || m })));
  mode.value = state.mode;
  mode.addEventListener('change', () => view.command(device, 'set_mode', { mode: mode.value }));
  const box = el('div', { className: 'heater-box', testid: 'thermo-controls' }, [field('Mode', mode)]);
  // Only the set points this mode uses: Heat one, Cool one, Auto both, Off and Eco none.
  if (HEAT_MODES.has(state.mode)) box.append(setPointRow(view, device, 'heat', state.heat_setpoint, 'set_temperature', limits));
  if (COOL_MODES.has(state.mode)) {
    const command = state.mode === 'auto' ? 'set_cool_temperature' : 'set_temperature';
    box.append(setPointRow(view, device, 'cool', state.cool_setpoint, command, limits));
  }
  if (HEAT_MODES.has(state.mode) || COOL_MODES.has(state.mode)) {
    box.append(limits && limits.enabled
      ? el('p', { className: 'muted', testid: 'temp-limits', text: `Allowed ${limits.min_temperature}–${limits.max_temperature} °${limits.unit}` })
      : el('p', { className: 'warning', testid: 'limits-missing', text: 'Control is off until an admin sets safety limits.' }));
  }
  if (state.fan) {
    const fanOn = state.fan === 'on';
    box.append(el('button', {
      type: 'button', className: `toggle${fanOn ? ' on' : ''}`, testid: 'thermo-fan', 'aria-pressed': String(fanOn),
      disabled: !device.controllable, text: fanOn ? 'Fan: on' : 'Fan: auto', 'aria-label': `${device.name} fan`,
      onclick: () => view.command(device, 'set_fan', { fan: fanOn ? 'auto' : 'on' }),
    }));
  }
  if (THERMO_HOLDS[state.hold]) {
    const next = HOLD_ORDER[(HOLD_ORDER.indexOf(state.hold) + 1) % HOLD_ORDER.length];
    box.append(el('button', {
      type: 'button', className: `toggle${state.hold === 'schedule' ? '' : ' on'}`, testid: 'thermo-hold', 'data-hold': state.hold,
      disabled: !device.controllable, text: THERMO_HOLDS[state.hold], title: `Change to: ${THERMO_HOLDS[next]}`,
      'aria-label': `${device.name}: ${THERMO_HOLDS[state.hold]}. Change to ${THERMO_HOLDS[next]}`,
      onclick: () => view.command(device, 'set_hold', { hold: next }),
    }));
  }
  // The schedule sits right under the hold button: the hold decides whether it is followed.
  if (device.integration === 'cync') {
    box.append(el('button', { type: 'button', className: 'secondary', testid: 'thermo-schedule-open', text: 'Schedule', onclick: () => thermostatSchedulePanel(view).open(device) }));
  }
  if (state.mode === 'eco') box.append(el('p', { className: 'muted', testid: 'thermo-eco', text: 'Eco mode: the thermostat keeps its own energy-saving range. Change the mode to set a temperature.' }));
  parts.push(box);
  const sensors = (state.sensors || []).filter((s) => typeof s.temperature === 'number');
  if (sensors.length) {
    parts.push(el('div', { className: 'heater-box', testid: 'thermo-sensors' }, [
      el('strong', { text: 'Sensors' }),
      ...sensors.map((s) => el('p', { className: 'muted', text: `${s.name}: ${sensorText(s)}` })),
    ]));
  }
  parts.push(el('button', { type: 'button', className: 'secondary', testid: 'thermo-info-open', text: 'Info', onclick: () => thermostatPanel(view).open(device) }));
  return parts;
}

/** Info window: what the tile does not already show. */
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
      ['System', s.system],
      ['Filter use', s.filter_hours != null ? `${s.filter_hours} h${s.filter_reset ? ` since ${s.filter_reset}` : ''}` : null],
      ['Firmware', s.firmware],
      ['Wi-Fi signal', s.wifi],
    ].filter(([, value]) => value); // only what the thermostat reports
    this.overlay.replaceChildren(el('div', { className: 'remote info-panel', testid: 'thermo-panel', role: 'dialog', 'aria-label': `${device.name} info` }, [
      el('div', { className: 'remote-head' }, [
        el('h2', { text: `${device.name} info` }),
        el('button', { type: 'button', className: 'ghost', testid: 'thermo-close', text: '✕', 'aria-label': 'Close', onclick: () => this.close() }),
      ]),
      rows.length ? el('dl', {}, rows.map(([label, value]) => line(label, value))) : el('p', { className: 'muted', text: 'The thermostat reports nothing more.' }),
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
