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

function thermostatExtras(view, device, state) {
  if (!state.mode) return [];
  const status = state.status || 'idle';
  const now = [`Inside ${degrees(state.current_temperature)}`];
  if (typeof state.humidity === 'number') now.push(`${state.humidity}% humidity`);
  const parts = [
    el('p', { className: `heater-status ${status}`, testid: 'thermo-status', 'data-status': status, text: THERMO_STATUS[status] || status }),
    el('p', { className: 'muted', testid: 'thermo-now', text: now.join(' · ') }),
  ];
  if (state.mode === 'eco') parts.push(el('p', { className: 'muted', testid: 'thermo-eco', text: 'Eco mode: set points are locked until you change the mode.' }));

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
  const sensors = state.sensors || [];
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
    const filter = s.filter_hours != null ? `${s.filter_hours} h${s.filter_reset ? ` since ${s.filter_reset}` : ''}` : 'not reported';
    this.overlay.replaceChildren(el('div', { className: 'remote info-panel', testid: 'thermo-panel', role: 'dialog', 'aria-label': `${device.name} settings` }, [
      el('div', { className: 'remote-head' }, [
        el('h2', { text: device.name }),
        el('button', { type: 'button', className: 'ghost', testid: 'thermo-close', text: '✕', 'aria-label': 'Close', onclick: () => this.close() }),
      ]),
      el('dl', {}, [
        line('Mode', THERMO_MODES[s.mode] || '—'),
        line('Doing now', THERMO_STATUS[s.status] || '—'),
        line('Heat to', degrees(s.heat_setpoint)),
        line('Cool to', degrees(s.cool_setpoint)),
        line('Schedule', THERMO_HOLDS[s.hold] || 'not reported'),
        line('System', s.system || 'not reported'),
        line('Filter use', filter),
        line('Firmware', s.firmware || 'not reported'),
        line('Wi-Fi signal', s.wifi || 'not reported'),
      ]),
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
