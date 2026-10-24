/**
 * Water heater usage window: energy or water use as a bar chart, by hour
 * for today or by day for the last 7 or 30 days, as Rheem reports it.
 * Tap or hover a bar for its value; "Show as table" lists every value.
 */

const USAGE_RANGES = [[1, 'Today'], [7, '7 days'], [30, '30 days']];
const USAGE_KINDS = [['energy', 'Energy'], ['water', 'Water']];
const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

function energyUnit(unit) {
  return !unit || unit.toLowerCase() === 'kwh' ? 'kWh' : unit;
}

function hourLabel(hour) {
  const h = Number(hour);
  return `${h % 12 || 12} ${h < 12 ? 'AM' : 'PM'}`;
}

function dayLabel(iso, long) {
  const date = new Date(`${iso}T12:00:00`);
  return long ? `${WEEKDAYS[date.getDay()]} ${date.getMonth() + 1}/${date.getDate()}` : `${date.getMonth() + 1}/${date.getDate()}`;
}

/** A bar with a rounded top and a flat bottom on the baseline. */
function barPath(x, y, w, base) {
  const r = Math.min(4, w / 2, base - y);
  if (r <= 0) return `M ${x} ${base} H ${x + w} Z`;
  return `M ${x} ${base} V ${y + r} Q ${x} ${y} ${x + r} ${y} H ${x + w - r} Q ${x + w} ${y} ${x + w} ${y + r} V ${base} Z`;
}

class UsagePanel {
  constructor(view) {
    this.view = view;
    this.days = 1;
    this.kind = 'energy';
    this.overlay = el('div', { className: 'overlay', hidden: true });
    this.overlay.addEventListener('click', (e) => { if (e.target === this.overlay) this.close(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !this.overlay.hidden) this.close(); });
    document.body.append(this.overlay);
  }

  open(device) {
    this.device = device;
    this.overlay.hidden = false;
    this.load();
  }

  async load() {
    const { device } = this;
    this.render(el('p', { className: 'muted', testid: 'usage-loading', text: 'Asking Rheem…' }));
    try {
      const path = `/homes/${encodeURIComponent(this.view.app.home.id)}/devices/${encodeURIComponent(device.id)}/usage?days=${this.days}`;
      this.data = await this.view.app.api.get(path);
      if (this.device === device && !this.overlay.hidden) this.render(this.chart());
    } catch (error) {
      this.render(el('p', { className: 'warning', testid: 'usage-error', text: error.message }));
    }
  }

  switcher(options, current, pick, name) {
    return el('div', { className: 'segmented', role: 'group', 'aria-label': name }, options.map(([value, label]) => el('button', {
      type: 'button', className: value === current ? 'on' : 'secondary', 'aria-pressed': String(value === current),
      testid: `usage-${value}`, text: label, onclick: () => pick(value),
    })));
  }

  render(body) {
    this.overlay.replaceChildren(el('div', { className: 'remote info-panel usage-panel', testid: 'usage-panel', role: 'dialog', 'aria-label': `${this.device.name} usage` }, [
      el('div', { className: 'remote-head' }, [
        el('h2', { text: `${this.device.name} usage` }),
        el('button', { type: 'button', className: 'ghost', testid: 'usage-close', text: '✕', 'aria-label': 'Close', onclick: () => this.close() }),
      ]),
      this.switcher(USAGE_KINDS, this.kind, (k) => { this.kind = k; if (this.data) this.render(this.chart()); }, 'What to show'),
      this.switcher(USAGE_RANGES, this.days, (d) => { this.days = d; this.load(); }, 'Period'),
      body,
    ]));
  }

  chart() {
    const points = this.data[this.kind];
    const unit = this.kind === 'energy' ? energyUnit(this.data.energy_unit) : 'gal';
    if (!points) return el('p', { className: 'muted', testid: 'usage-none', text: `This water heater does not report ${this.kind} use.` });
    const label = (p, long) => (this.data.days === 1 ? hourLabel(p.label) : dayLabel(p.label, long));
    const digits = this.kind === 'energy' ? 2 : 0;
    const total = points.reduce((sum, p) => sum + p.value, 0);
    const readout = el('p', { className: 'usage-readout', testid: 'usage-readout', 'aria-live': 'polite' });
    const showTotal = () => { readout.textContent = `${total.toFixed(digits)} ${unit} in total`; };
    showTotal();
    const max = Math.max(...points.map((p) => p.value), 0) || 1;
    const W = 320; const H = 150; const base = 128; const top = 14;
    const slot = W / Math.max(points.length, 1);
    const gap = 2;
    const bars = points.map((p, i) => {
      const y = base - (p.value / max) * (base - top);
      const text = `${label(p, true)}: ${p.value.toFixed(digits)} ${unit}`;
      const show = () => { readout.textContent = text; };
      return svg('g', { className: 'usage-bar' }, [
        svg('path', { d: barPath(i * slot + gap / 2, y, Math.max(slot - gap, 1), base), className: 'usage-fill' }),
        // The hit area is the whole column, bigger than the bar.
        svg('rect', { x: String(i * slot), y: '0', width: String(slot), height: String(H), className: 'usage-hit', tabindex: '0', 'aria-label': text, onpointerenter: show, onfocus: show, onclick: show }),
      ]);
    });
    const every = this.data.days === 1 ? 6 : this.data.days === 7 ? 1 : 7;
    const ticks = points.flatMap((p, i) => (i % every === 0
      ? [svg('text', {
        x: String(i === 0 ? 0 : i * slot + slot / 2), y: String(H - 4), className: 'usage-tick', 'text-anchor': i === 0 ? 'start' : 'middle',
        text: this.data.days === 7 ? WEEKDAYS[new Date(`${p.label}T12:00:00`).getDay()] : label(p, false),
      })]
      : []));
    const chart = svg('svg', { viewBox: `0 0 ${W} ${H}`, className: 'usage-chart', testid: 'usage-chart', role: 'img', 'aria-label': `${this.kind} use chart` }, [
      svg('text', { x: '0', y: '10', className: 'usage-tick', text: `${max.toFixed(digits)} ${unit}` }),
      svg('line', { x1: '0', x2: String(W), y1: String(top), y2: String(top), className: 'usage-grid' }),
      svg('line', { x1: '0', x2: String(W), y1: String(base), y2: String(base), className: 'usage-axis' }),
      ...bars, ...ticks,
    ]);
    chart.addEventListener('pointerleave', showTotal);
    const table = el('details', { className: 'usage-table' }, [
      el('summary', { text: 'Show as table' }),
      el('dl', {}, points.map((p) => el('div', { className: 'info-line' }, [el('dt', { text: label(p, true) }), el('dd', { text: `${p.value.toFixed(digits)} ${unit}` })]))),
    ]);
    return el('div', { className: 'usage-body' }, [readout, chart, table]);
  }

  close() {
    this.overlay.hidden = true;
    this.overlay.replaceChildren();
  }
}

function usagePanel(view) {
  if (!view.usagePanel) view.usagePanel = new UsagePanel(view);
  return view.usagePanel;
}

window.usagePanel = usagePanel;
window.energyUnit = energyUnit;
