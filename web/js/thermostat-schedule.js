/**
 * Thermostat schedule window: the weekly heating, cooling and auto schedules
 * stored on the thermostat, and which sensors it reads at each time of day;
 * each day can be edited (thermostat-schedule-edit.js). Reading asks the thermostat for 28 settings,
 * so it takes several seconds; the result is kept for a few minutes.
 */

const SCHEDULE_TABS = [['heat', 'Heating'], ['cool', 'Cooling'], ['auto', 'Auto'], ['sensors', 'Sensors']];
const SCHEDULE_DAYS = [['mon', 'Mon'], ['tue', 'Tue'], ['wed', 'Wed'], ['thu', 'Thu'], ['fri', 'Fri'], ['sat', 'Sat'], ['sun', 'Sun']];
const SENSOR_READS = { thermostat: 'Thermostat only', all: 'All sensors' };

function clockText(time) {
  const [h, m] = time.split(':').map(Number);
  return `${h % 12 || 12}:${String(m).padStart(2, '0')} ${h < 12 ? 'AM' : 'PM'}`;
}

function periodText(kind, period) {
  if (kind === 'sensors') return period.read === 'sensor' ? (period.label || 'Remote sensor') : (SENSOR_READS[period.read] || period.read);
  if (kind === 'auto') return `heat ${degrees(period.heat)} · cool ${degrees(period.cool)}`;
  return degrees(period[kind]);
}

class ThermostatSchedulePanel {
  constructor(view) {
    this.view = view;
    this.overlay = el('div', { className: 'overlay', hidden: true });
    this.overlay.addEventListener('click', (e) => { if (e.target === this.overlay) this.close(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !this.overlay.hidden) this.close(); });
    document.body.append(this.overlay);
  }

  open(device) {
    this.device = device;
    const mode = (device.state || {}).mode;
    this.tab = ['heat', 'cool', 'auto'].includes(mode) ? mode : 'heat';
    this.data = null;
    this.editing = null;
    this.overlay.hidden = false;
    this.load(false);
  }

  async load(refresh) {
    const { device } = this;
    this.render(el('p', { className: 'muted', testid: 'schedule-loading', text: 'Asking the thermostat… this can take half a minute.' }));
    try {
      const path = `/homes/${encodeURIComponent(this.view.app.home.id)}/devices/${encodeURIComponent(device.id)}/schedule${refresh ? '?refresh=true' : ''}`;
      const data = await this.view.app.api.get(path);
      if (this.device !== device || this.overlay.hidden) return;
      this.data = data;
      this.render(this.week());
    } catch (error) {
      this.render(el('p', { className: 'warning', testid: 'schedule-error', text: error.message }));
    }
  }

  week() {
    if (this.editing) return this.editor(this.editing);
    const days = this.data.week[this.tab] || {};
    const label = SCHEDULE_TABS.find(([k]) => k === this.tab)[1].toLowerCase();
    const set = SCHEDULE_DAYS.some(([d]) => (days[d] || []).length);
    const body = [];
    if (!set) {
      body.push(el('p', { className: 'muted', testid: 'schedule-empty', text: this.tab === 'sensors' ? 'No sensor schedule is set: the thermostat reads its sensors the same way all day.' : `No ${label} schedule is set on the thermostat.` }));
    }
    const canEdit = this.device.controllable;
    body.push(el('dl', { className: 'schedule-week', testid: 'schedule-week' }, SCHEDULE_DAYS.map(([day, name]) => {
      const periods = days[day] || [];
      return el('div', { className: 'schedule-day', testid: `schedule-${day}` }, [
        el('dt', { text: name }),
        el('dd', {}, periods.length
          ? periods.map((p) => el('span', { className: 'schedule-period', text: `${clockText(p.time)} → ${periodText(this.tab, p)}` }))
          : [el('span', { className: 'muted', text: 'Nothing set' })]),
        canEdit ? el('button', { type: 'button', className: 'ghost', testid: `schedule-edit-${day}`, text: 'Edit', 'aria-label': `Edit ${name}`, onclick: () => { this.editing = day; this.render(this.week()); } }) : null,
      ]);
    })));
    if ((this.data.missing || []).length) {
      body.push(el('p', { className: 'warning', testid: 'schedule-missing', text: `The thermostat did not answer for ${this.data.missing.length} of the days; refresh to ask again.` }));
    }
    return el('div', {}, body);
  }

  editor(day) {
    const kind = this.tab;
    const state = this.device.state || {};
    const sensors = (state.sensors || []).filter((x) => x.pin);
    return scheduleEditor({
      kind, day, sensors,
      periods: (this.data.week[kind] || {})[day] || [],
      limits: this.view.limitsFor(this.device),
      cancel: () => { this.editing = null; this.render(this.week()); },
      save: async (days, periods) => {
        const path = `/homes/${encodeURIComponent(this.view.app.home.id)}/devices/${encodeURIComponent(this.device.id)}/schedule/${kind}`;
        this.data = await this.view.app.api.put(path, { days, periods });
        this.editing = null;
        this.render(this.week());
        this.view.app.status.success('The thermostat stored the schedule.');
      },
    });
  }

  render(body) {
    const tabs = el('div', { className: 'segmented', role: 'group', 'aria-label': 'Schedule' }, SCHEDULE_TABS.map(([key, name]) => el('button', {
      type: 'button', className: key === this.tab ? 'on' : 'secondary', 'aria-pressed': String(key === this.tab), testid: `schedule-tab-${key}`, text: name,
      onclick: () => { this.tab = key; this.editing = null; if (this.data) this.render(this.week()); },
    })));
    this.overlay.replaceChildren(el('div', { className: 'remote info-panel', testid: 'schedule-panel', role: 'dialog', 'aria-label': `${this.device.name} schedule` }, [
      el('div', { className: 'remote-head' }, [
        el('h2', { text: `${this.device.name} schedule` }),
        el('button', { type: 'button', className: 'ghost', testid: 'schedule-close', text: '✕', 'aria-label': 'Close', onclick: () => this.close() }),
      ]),
      tabs,
      body,
      this.editing ? null : el('button', { type: 'button', className: 'secondary', testid: 'schedule-refresh', text: 'Read again', onclick: () => this.load(true) }),
    ]));
  }

  close() {
    this.overlay.hidden = true;
    this.overlay.replaceChildren();
  }
}

function thermostatSchedulePanel(view) {
  if (!view.thermostatSchedulePanel) view.thermostatSchedulePanel = new ThermostatSchedulePanel(view);
  return view.thermostatSchedulePanel;
}

window.thermostatSchedulePanel = thermostatSchedulePanel;
