/**
 * Thermostat History window (the History button on a Cync thermostat's
 * tile): the temperature with the heat and cool set points, and the hours
 * it heated or cooled each day, from the readings the app keeps (from when
 * it started keeping them, for up to a month).
 */

const HISTORY_RANGES = [[1, 'Day'], [7, 'Week'], [30, 'Month']];

function historyTime(iso, days) {
  const at = new Date(iso);
  return days <= 1
    ? at.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
    : at.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric' });
}

/** Temperature (solid) and set points (dashed) over time. */
function historyChart(points, days) {
  const W = 320;
  const H = 150;
  const values = points.flatMap((p) => [p.temperature, p.heat, p.cool]).filter((v) => typeof v === 'number');
  if (values.length === 0) return el('p', { className: 'muted', testid: 'history-empty', text: 'No readings in this time yet.' });
  const low = Math.floor(Math.min(...values)) - 1;
  const high = Math.ceil(Math.max(...values)) + 1;
  const start = new Date(points[0].at).getTime();
  const span = Math.max(new Date(points[points.length - 1].at).getTime() - start, 1);
  const x = (p) => ((new Date(p.at).getTime() - start) / span) * W;
  const y = (v) => H - ((v - low) / (high - low)) * H;
  const line = (key, className) => {
    const d = points.filter((p) => typeof p[key] === 'number').map((p, i) => `${i ? 'L' : 'M'}${x(p).toFixed(1)},${y(p[key]).toFixed(1)}`).join('');
    return d ? svg('path', { d, className }) : null;
  };
  // Shaded where it was heating or cooling.
  const bands = points.map((p, i) => {
    if (p.status !== 'heating' && p.status !== 'cooling') return null;
    const next = points[i + 1];
    const width = Math.max((next ? x(next) : W) - x(p), 1);
    return svg('rect', { x: x(p).toFixed(1), y: '0', width: width.toFixed(1), height: String(H), className: `history-band ${p.status}` });
  });
  const readout = el('p', { className: 'muted', testid: 'history-readout', 'aria-live': 'polite', text: `${low + 1}–${high - 1} °F` });
  const chart = svg('svg', { viewBox: `0 0 ${W} ${H}`, className: 'history-chart', testid: 'history-chart', role: 'img', 'aria-label': 'Temperature and set points' }, [
    ...bands.filter(Boolean), line('heat', 'history-heat'), line('cool', 'history-cool'), line('temperature', 'history-temp'),
  ]);
  chart.addEventListener('pointermove', (event) => {
    const box = chart.getBoundingClientRect();
    const at = start + ((event.clientX - box.left) / box.width) * span;
    const near = points.reduce((a, b) => (Math.abs(new Date(b.at).getTime() - at) < Math.abs(new Date(a.at).getTime() - at) ? b : a));
    readout.textContent = `${historyTime(near.at, days)}: ${near.temperature != null ? `${near.temperature} °F` : '—'}`
      + `${near.heat != null ? ` · heat to ${near.heat}` : ''}${near.cool != null ? ` · cool to ${near.cool}` : ''}${near.status ? ` · ${near.status}` : ''}`;
  });
  return el('div', {}, [chart, readout]);
}

/** Heating and cooling hours, one row per day (newest first). */
function runTable(runHours) {
  if (runHours.length === 0) return el('p', { className: 'muted', testid: 'history-run-none', text: 'No heating or cooling in this time.' });
  const hours = (h) => (h >= 1 ? `${h.toFixed(1)} h` : `${Math.round(h * 60)} min`);
  return el('dl', { className: 'readings', testid: 'history-run' }, [...runHours].reverse().flatMap((day) => [
    el('dt', { text: new Date(`${day.date}T12:00:00Z`).toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' }) }),
    el('dd', { text: [day.heating ? `heating ${hours(day.heating)}` : '', day.cooling ? `cooling ${hours(day.cooling)}` : ''].filter(Boolean).join(' · ') || '—' }),
  ]));
}

class ThermostatHistoryPanel {
  constructor(view) {
    this.view = view;
    this.overlay = el('div', { className: 'overlay', hidden: true });
    this.overlay.addEventListener('click', (e) => { if (e.target === this.overlay) this.close(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !this.overlay.hidden) this.close(); });
    document.body.append(this.overlay);
  }

  open(device) {
    this.device = device;
    this.days = 1;
    this.overlay.hidden = false;
    this.load();
  }

  async load() {
    const { device, days } = this;
    this.render(el('p', { className: 'muted', text: 'Loading…' }));
    try {
      const data = await this.view.app.api.get(`/homes/${encodeURIComponent(this.view.app.home.id)}/devices/${encodeURIComponent(device.id)}/history?days=${days}`);
      if (this.device !== device || this.days !== days || this.overlay.hidden) return;
      this.render(el('div', { className: 'stack' }, [
        historyChart(data.points, days),
        el('div', { className: 'history-key muted' }, [
          el('span', { className: 'key-temp', text: 'Temperature' }), el('span', { className: 'key-heat', text: 'Heat to' }),
          el('span', { className: 'key-cool', text: 'Cool to' }), el('span', { className: 'key-run', text: 'Shaded: running' }),
        ]),
        el('h3', { text: 'Heating and cooling' }),
        runTable(data.run_hours),
        el('p', { className: 'muted', testid: 'history-since', text: data.since ? `Kept since ${new Date(data.since).toLocaleDateString()}, for up to a month.` : 'The app keeps readings from now on.' }),
      ]));
    } catch (error) {
      this.render(el('p', { className: 'warning', text: error.message }));
    }
  }

  render(body) {
    const ranges = el('div', { className: 'segmented', role: 'group', 'aria-label': 'Time' }, HISTORY_RANGES.map(([value, label]) => el('button', {
      type: 'button', className: value === this.days ? 'on' : 'secondary', 'aria-pressed': String(value === this.days), testid: `history-range-${value}`, text: label,
      onclick: () => { this.days = value; this.load(); },
    })));
    this.overlay.replaceChildren(el('div', { className: 'remote info-panel', testid: 'history-panel', role: 'dialog', 'aria-label': `${this.device.name} history` }, [
      el('div', { className: 'remote-head' }, [
        el('h2', { text: `${this.device.name} history` }),
        el('button', { type: 'button', className: 'ghost', testid: 'history-close', text: '✕', 'aria-label': 'Close', onclick: () => this.close() }),
      ]),
      ranges,
      body,
    ]));
  }

  close() {
    this.overlay.hidden = true;
    this.overlay.replaceChildren();
  }
}

function thermostatHistoryPanel(view) {
  if (!view.thermostatHistoryPanel) view.thermostatHistoryPanel = new ThermostatHistoryPanel(view);
  return view.thermostatHistoryPanel;
}

window.thermostatHistoryPanel = thermostatHistoryPanel;
