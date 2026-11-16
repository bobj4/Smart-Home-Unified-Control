/**
 * The Energy window (Devices page, "⚡ … W"): power now and use today from
 * plugs that measure it (Kasa), and water heaters' use today (Rheem). The
 * button shows only while some device reports power.
 */

function energyRows(devices) {
  const plugs = devices.filter((d) => d.state && typeof d.state.power_w === 'number');
  const heaters = devices.filter((d) => d.type === 'water_heater' && d.state && typeof d.state.energy_today === 'number');
  return { plugs, heaters, total: plugs.reduce((sum, d) => sum + (d.online === false ? 0 : d.state.power_w), 0) };
}

function energyButton(view, devices) {
  const { plugs, total } = energyRows(devices);
  if (!plugs.length) return null;
  return el('button', {
    type: 'button', className: 'secondary', testid: 'energy-open', text: `⚡ ${Math.round(total)} W now`,
    'aria-label': `Energy: ${Math.round(total)} watts now`, onclick: () => openEnergy(view, devices),
  });
}

function openEnergy(view, devices) {
  const { plugs, heaters, total } = energyRows(devices);
  const overlay = el('div', { className: 'overlay', testid: 'energy-overlay' });
  const close = () => overlay.remove();
  overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
  const line = (name, value, testid) => el('div', { className: 'info-line', testid }, [el('dt', { text: name }), el('dd', { text: value })]);
  const today = plugs.reduce((sum, d) => sum + (d.state.today_kwh || 0), 0);
  overlay.append(el('div', { className: 'remote info-panel', role: 'dialog', 'aria-label': 'Energy' }, [
    el('div', { className: 'remote-head' }, [
      el('h2', { text: 'Energy' }),
      el('button', { type: 'button', className: 'ghost', testid: 'energy-close', text: '✕', 'aria-label': 'Close', onclick: close }),
    ]),
    el('dl', {}, [
      line('Now (plugs that measure)', `${total.toFixed(1)} W`, 'energy-total'),
      line('Today', `${today.toFixed(2)} kWh`, 'energy-today'),
    ]),
    el('h3', { text: 'Plugs' }),
    el('dl', {}, plugs.sort((a, b) => b.state.power_w - a.state.power_w).map((d) => line(
      d.name, d.online === false ? 'offline' : `${d.state.power_w.toFixed(1)} W${typeof d.state.today_kwh === 'number' ? ` · ${d.state.today_kwh.toFixed(2)} kWh today` : ''}`, 'energy-plug',
    ))),
    heaters.length ? el('h3', { text: 'Water heaters' }) : '',
    heaters.length ? el('dl', {}, heaters.map((d) => line(d.name, `${d.state.energy_today} ${(d.state.energy_unit || 'kWh').toLowerCase().replace('kwh', 'kWh').replace('kbtu', 'kBTU')} today`, 'energy-heater'))) : '',
  ]));
  document.addEventListener('keydown', function escape(e) {
    if (e.key === 'Escape') { close(); document.removeEventListener('keydown', escape); }
  });
  document.body.append(overlay);
}

window.energyButton = energyButton;
