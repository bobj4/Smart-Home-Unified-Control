/**
 * Water heater tile extras: status under the target, then schedule (with
 * home/away), today's usage, a Settings window (mode and details) and the
 * power button at the bottom. The temperature dial stays as it is.
 */

const HEATER_STATUS = { heating: 'Heating', idle: 'Idle', off: 'Off' };
const HEATER_MODES = {
  energy_saving: 'Energy saving', heat_pump_only: 'Heat pump only', heat_pump: 'Heat pump', high_demand: 'High demand',
  electric_mode: 'Electric', electric: 'Electric', gas: 'Gas', energy_saver: 'Energy saver', performance: 'Performance',
  vacation: 'Vacation', off: 'Off',
};

function heaterStatus(state) {
  if (state.status) return state.status;
  if (state.enabled === false) return 'off';
  return state.running ? 'heating' : 'idle';
}

function heaterExtras(view, device, state) {
  const status = heaterStatus(state);
  const off = status === 'off';
  const parts = [el('p', { className: `heater-status ${status}`, testid: 'heater-status', 'data-status': status, text: HEATER_STATUS[status] || status })];
  if (state.schedule || state.away !== undefined && state.away !== null) {
    const box = el('div', { className: 'heater-box', testid: 'heater-schedule' }, [el('strong', { text: 'Schedule' })]);
    if (state.schedule) box.append(el('p', { className: 'muted', text: state.schedule }));
    if (state.away !== undefined && state.away !== null) {
      box.append(el('button', {
        type: 'button', className: `toggle${state.away ? ' on' : ''}`, testid: 'heater-away', 'aria-pressed': String(Boolean(state.away)),
        disabled: !device.controllable, text: state.away ? 'Away' : 'Home',
        'aria-label': `${device.name}: home or away`, onclick: () => view.command(device, 'set_away', { away: !state.away }),
      }));
    }
    if (state.schedule && state.schedule !== 'Following Schedule') {
      box.append(el('button', {
        type: 'button', className: 'secondary', testid: 'heater-resume', text: 'Resume schedule', disabled: !device.controllable,
        onclick: () => view.command(device, 'resume_schedule'),
      }));
    }
    parts.push(box);
  }
  const usage = device.integration === 'rheem_econet' || typeof state.energy_today === 'number' || typeof state.water_today === 'number';
  if (usage && !view.app.isGuest()) { // the usage history: members and up
    const today = [];
    if (typeof state.energy_today === 'number') today.push(`${state.energy_today.toFixed(2)} ${energyUnit(state.energy_unit)}`);
    if (typeof state.water_today === 'number') today.push(`${Math.round(state.water_today)} gal`);
    parts.push(el('button', {
      type: 'button', className: 'secondary', testid: 'heater-usage', text: today.length ? `Usage · ${today.map((t) => `${t} today`).join(' · ')}` : 'Usage',
      onclick: () => usagePanel(view).open(device),
    }));
  }
  parts.push(el('button', { type: 'button', className: 'secondary', testid: 'heater-settings-open', text: 'Settings', onclick: () => heaterPanel(view).open(device) }));
  parts.push(el('button', {
    type: 'button', className: `toggle${off ? '' : ' on'}`, testid: 'heater-power', 'aria-pressed': String(!off),
    'aria-label': `${device.name} power`, disabled: !device.controllable, text: off ? 'Off' : 'On',
    onclick: () => view.command(device, off ? 'turn_on' : 'turn_off'),
  }));
  return parts;
}

class HeaterPanel {
  constructor(view) {
    this.view = view;
    this.overlay = el('div', { className: 'overlay', hidden: true });
    this.overlay.addEventListener('click', (e) => { if (e.target === this.overlay) this.close(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !this.overlay.hidden) this.close(); });
    document.body.append(this.overlay);
  }

  open(device) {
    const s = device.state || {};
    const modes = (s.modes || []).filter((m) => m !== 'off');
    const mode = el('select', { testid: 'heater-mode', disabled: !device.controllable || modes.length === 0, 'aria-label': 'Mode' },
      modes.map((m) => el('option', { value: m, text: HEATER_MODES[m] || m })));
    if (s.mode && s.mode !== 'off') mode.value = s.mode;
    mode.addEventListener('change', () => this.view.command(device, 'set_mode', { mode: mode.value }).then(() => this.close()));
    const line = (label, value) => el('div', { className: 'info-line' }, [el('dt', { text: label }), el('dd', { text: value })]);
    this.overlay.replaceChildren(el('div', { className: 'remote info-panel', testid: 'heater-panel', role: 'dialog', 'aria-label': `${device.name} settings` }, [
      el('div', { className: 'remote-head' }, [
        el('h2', { text: device.name }),
        el('button', { type: 'button', className: 'ghost', testid: 'heater-close', text: '✕', 'aria-label': 'Close', onclick: () => this.close() }),
      ]),
      modes.length ? field('Mode', mode) : el('p', { className: 'muted', text: 'This water heater has no modes to choose.' }),
      el('dl', {}, [
        line('Status', HEATER_STATUS[heaterStatus(s)] || '—'),
        line('Rheem reports', s.activity || 'nothing running'),
        line('Hot water available', typeof s.hot_water === 'number' ? `${s.hot_water}%` : 'not reported'),
        line('Allowed by the heater', s.min_set_point != null ? `${s.min_set_point}–${s.max_set_point} °F` : 'not reported'),
        line('Wi-Fi signal', s.wifi != null ? String(s.wifi) : 'not reported'),
        line('Alerts', String(s.alerts || 0)),
      ]),
    ]));
    this.overlay.hidden = false;
  }

  close() {
    this.overlay.hidden = true;
    this.overlay.replaceChildren();
  }
}

function heaterPanel(view) {
  if (!view.heaterPanel) view.heaterPanel = new HeaterPanel(view);
  return view.heaterPanel;
}

window.heaterExtras = heaterExtras;
