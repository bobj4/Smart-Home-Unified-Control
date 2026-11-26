/**
 * Settings > Devices: the alert bell beside each device's description.
 * Light grey: its alerts are on; red with a line through: off. A plain bell
 * only turns them on and off (a light, say); a bell with a plus opens the
 * device's alert settings (garage doors, water heaters, thermostats).
 * Each person still picks which alerts reach them in My Account > Alerts.
 */

const ALERT_FIELDS = {
  garage_door: [
    ['open_minutes', 'minutes', 'Alert when open longer than (minutes, 0: never)'],
    ['auto_close_minutes', 'minutes', 'Then close it after (minutes, 0: never)'],
    ['obstruction', 'bool', 'Something in the door\'s way'],
    ['offline_minutes', 'minutes', 'Offline longer than (minutes, 0: never)'],
  ],
  water_heater: [
    ['problems', 'bool', 'It reports a problem'],
    ['offline_minutes', 'minutes', 'Offline longer than (minutes, 0: never)'],
  ],
  camera: [ // Google Nest cameras and doorbells
    ['person', 'bool', 'It sees a person'],
    ['motion', 'bool', 'It sees motion'],
    ['sound', 'bool', 'It hears a sound'],
    ['doorbell', 'bool', 'The doorbell rings'],
    ['offline_minutes', 'minutes', 'Offline longer than (minutes, 0: never)'],
  ],
  thermostat: [
    ['too_cold', 'degrees', 'Too cold: below (°, empty: never)'],
    ['too_hot', 'degrees', 'Too hot: above (°, empty: never)'],
    ['offline_minutes', 'minutes', 'Offline longer than (minutes, 0: never)'],
  ],
};

function bellIcon(on, plus) {
  return svg('svg', { viewBox: '0 0 24 24', class: `device-bell-icon${on ? ' on' : ' off'}`, 'aria-hidden': 'true' }, [
    svg('path', { d: 'M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z' }),
    svg('path', { d: 'M10 20a2 2 0 0 0 4 0' }),
    on ? null : svg('path', { class: 'slash', d: 'M4 3l16 18' }),
    plus ? svg('circle', { class: 'plus-dot', cx: '19', cy: '19', r: '4.5' }) : null,
    plus ? svg('path', { class: 'plus', d: 'M19 16.6v4.8M16.6 19h4.8' }) : null,
  ]);
}

function deviceAlertBell(app, device, cfg, canEdit) {
  const button = el('button', {
    type: 'button', className: 'ghost device-bell', testid: 'device-alert-bell', disabled: !canEdit,
    'data-on': String(cfg.enabled), 'data-popup': String(cfg.popup),
  });
  const draw = (current) => {
    Object.assign(cfg, current);
    button.dataset.on = String(cfg.enabled);
    const state = cfg.enabled ? 'on' : 'off';
    button.setAttribute('aria-label', `${device.name} alerts ${state}${cfg.popup ? ': settings' : ''}`);
    button.title = cfg.popup ? `Alerts ${state}: settings` : `Alerts ${state}: click to turn ${cfg.enabled ? 'off' : 'on'}`;
    button.replaceChildren(bellIcon(cfg.enabled, cfg.popup));
  };
  draw(cfg);
  button.addEventListener('click', (event) => {
    event.preventDefault();
    if (!cfg.popup) {
      app.run(async () => {
        draw(await app.api.setDeviceAlerts(app.home.id, device.id, { enabled: !cfg.enabled }));
        app.status.success(`${device.name}: alerts ${cfg.enabled ? 'on' : 'off'}.`);
      });
      return;
    }
    openDeviceAlerts(app, device, cfg, draw);
  });
  return button;
}

function openDeviceAlerts(app, device, cfg, draw) {
  const overlay = el('div', { className: 'overlay', testid: 'device-alerts-overlay' });
  const close = () => overlay.remove();
  overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
  const master = switchInput('device-alerts-master', cfg.enabled, `${device.name} alerts`);
  const inputs = {};
  const rows = (ALERT_FIELDS[device.type] || []).map(([key, kind, label]) => {
    const value = cfg.settings[key];
    if (kind === 'bool') {
      inputs[key] = switchInput(`device-alert-${key}`, Boolean(value), label);
      return settingRow(label, '', inputs[key]);
    }
    inputs[key] = el('input', { type: 'number', testid: `device-alert-${key}`, min: kind === 'minutes' ? '0' : '-20', max: kind === 'minutes' ? '1440' : '120', step: '1', value: value === null || value === undefined ? '' : String(value) });
    return field(label, inputs[key]);
  });
  const settings = el('div', { className: 'grid' }, rows);
  const follow = () => { settings.classList.toggle('dimmed', !master.checked); };
  master.addEventListener('change', follow);
  follow();
  const note = formNote('device-alerts-note');
  const form = el('form', { className: 'remote info-panel', testid: 'device-alerts', role: 'dialog', 'aria-label': `Alerts for ${device.name}` }, [
    el('div', { className: 'remote-head' }, [
      el('h2', { text: `Alerts: ${device.name}` }),
      el('button', { type: 'button', className: 'ghost', testid: 'device-alerts-close', text: '✕', 'aria-label': 'Close', onclick: close }),
    ]),
    settingRow('Alerts for this device', 'Off: nothing about it is sent, whatever is set below.', master),
    settings,
    el('p', { className: 'muted', text: 'Who gets them, and how: each person in My Account > Alerts.' }),
    note,
    el('button', { type: 'submit', testid: 'device-alerts-save', text: 'Save' }),
  ]);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const body = { enabled: master.checked, settings: {} };
    for (const [key, kind] of (ALERT_FIELDS[device.type] || [])) {
      const input = inputs[key];
      if (kind === 'bool') body.settings[key] = input.checked;
      else if (kind === 'degrees') body.settings[key] = input.value.trim() === '' ? null : Number.parseInt(input.value, 10);
      else body.settings[key] = Number.parseInt(input.value || '0', 10);
    }
    try {
      draw(await app.api.setDeviceAlerts(app.home.id, device.id, body));
      close();
      app.status.success(`${device.name}: alert settings saved.`);
    } catch (error) {
      note.dataset.kind = 'error';
      note.textContent = error.message;
    }
  });
  overlay.append(form);
  document.addEventListener('keydown', function escape(e) {
    if (e.key === 'Escape') { close(); document.removeEventListener('keydown', escape); }
  });
  document.body.append(overlay);
  master.focus();
}

window.deviceAlertBell = deviceAlertBell;
