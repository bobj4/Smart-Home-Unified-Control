/**
 * Devices view: cards grouped by room. Lights and TVs get a power toggle;
 * thermostats and water heaters get a dial with up/down buttons that stay
 * inside the home's safety limits (the backend enforces them too).
 */

const TEMPERATURE_TYPES = new Set(['thermostat', 'water_heater']);
const POWER_TYPES = new Set(['light', 'plug', 'tv']);
const TYPE_LABEL = {
  light: 'Light', plug: 'Plug', tv: 'TV', thermostat: 'Thermostat', water_heater: 'Water heater',
  sensor: 'Sensor', camera: 'Camera',
};
// Simple line icons, 24x24.
const ICON_PATHS = {
  light: 'M9 18h6M10 21h4M12 3a6 6 0 0 0-4 10.5c.8.8 1 1.5 1 2.5h6c0-1 .2-1.7 1-2.5A6 6 0 0 0 12 3z',
  plug: 'M9 3v5M15 3v5M6 8h12v4a6 6 0 0 1-12 0zM12 18v3',
  tv: 'M3 6h18v11H3zM8 21h8M12 17v4',
  thermostat: 'M12 3a2 2 0 0 0-2 2v9.3a4 4 0 1 0 4 0V5a2 2 0 0 0-2-2zM12 9v7',
  water_heater: 'M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11z',
  sensor: 'M5 12a7 7 0 0 1 14 0M8 12a4 4 0 0 1 8 0M12 12v.01',
  camera: 'M3 7h4l2-3h6l2 3h4v12H3zM12 10a3 3 0 1 0 0 6 3 3 0 0 0 0-6z',
};

function icon(type) {
  return svg('svg', { viewBox: '0 0 24 24', className: 'icon', 'aria-hidden': 'true' }, [
    svg('path', { d: ICON_PATHS[type] || ICON_PATHS.sensor }),
  ]);
}

/** A 270-degree arc; the filled part shows where the target sits between the limits. */
function gauge(fraction, type) {
  const arc = 'M 26.1 93.9 A 48 48 0 1 1 93.9 93.9';
  const filled = Math.max(0, Math.min(1, fraction)) * 100;
  return svg('svg', { viewBox: '0 0 120 110', className: `gauge ${type}`, testid: 'temp-gauge', role: 'img', 'aria-label': 'Target temperature dial' }, [
    svg('path', { d: arc, className: 'gauge-track', pathLength: '100' }),
    svg('path', { d: arc, className: 'gauge-fill', pathLength: '100', 'stroke-dasharray': `${filled} 100` }),
  ]);
}

/** The colour a light shows: its RGB colour, or its colour temperature as a tint. */
function lightColor(state) {
  if (state.color_mode === 'rgb' && state.color) return state.color;
  const kelvin = state.color_temp || 2700;
  const warm = [255, 166, 77];
  const cool = [214, 230, 255];
  const t = Math.max(0, Math.min(1, (kelvin - 2000) / 4500));
  const mix = warm.map((w, i) => Math.round(w + (cool[i] - w) * t));
  return `rgb(${mix.join(', ')})`;
}

class DevicesView {
  constructor(app, root) {
    this.app = app;
    this.root = root;
    this.limits = {};
    this.integrationsOn = new Set();
    this.remote = new TvRemote(app);
    this.lightPanel = new LightPanel(app);
    this.groups = new GroupsUI(app);
    this.lastDevices = [];
  }

  async load() {
    const homeId = this.app.home.id;
    const [devices, limits, integrations, groups, display] = await Promise.all([
      this.app.api.getDevices(homeId),
      this.app.api.getSafetyLimits(homeId),
      this.app.api.getIntegrations(homeId),
      this.app.api.getGroups(homeId),
      this.app.api.getDisplay(homeId),
    ]);
    this.display = display;
    if (this.layoutHome !== homeId) { // each user's room order, read once per home
      try {
        this.roomOrder = (await this.app.api.getLayout(homeId)).room_order;
      } catch (error) {
        this.roomOrder = null; // the default order
      }
      this.layoutHome = homeId;
    }
    this.limits = Object.fromEntries(limits.map((l) => [l.device_type, l]));
    this.integrationsOn = new Set(integrations.filter((i) => i.enabled).map((i) => i.id));
    for (const device of devices) {
      device.integrationOn = this.integrationsOn.has(device.integration);
      device.controllable = Boolean(device.online) && device.integrationOn;
    }
    this.remote.refresh(devices);
    this.lastDevices = devices;
    this.groupList = groups;
    this.lightPanel.refresh([...devices, ...groups.map((g) => this.groupDevice(g))]);
    this.render(devices);
    this.groups.refresh(groups, devices);
  }

  render(devices) {
    if (devices.length === 0) {
      this.root.replaceChildren(el('p', { className: 'empty', testid: 'devices-empty', text: 'No devices yet. An admin can add them.' }));
      return;
    }
    const groupList = this.groupList || [];
    const apart = Boolean(this.display && this.display.show_grouped_devices);
    // Default: a group is one tile in its room, and its devices are not
    // listed there (open them with the group's ⋯ button).
    const grouped = apart ? new Set() : new Set(groupList.flatMap((g) => g.device_ids));
    const rooms = new Map();
    const add = (room, tile) => {
      if (!rooms.has(room)) rooms.set(room, []);
      rooms.get(room).push(tile);
    };
    if (!apart) groupList.forEach((g) => add(g.room || '', this.groupTile(g)));
    devices.filter((d) => !grouped.has(d.id)).forEach((d) => add(displayRoom(d), this.card(d)));
    const names = orderRooms([...rooms.keys()], this.roomOrder);
    const top = apart ? this.groups.section(groupList) : this.groups.hint(groupList);
    const layout = el('button', {
      type: 'button', className: 'secondary layout-open', testid: 'layout-open', text: 'Edit layout',
      onclick: () => {
        if (!this.layoutEditor) this.layoutEditor = new RoomLayoutEditor(this);
        this.layoutEditor.open(names);
      },
    });
    this.root.replaceChildren(el('div', { className: 'devices-top' }, [top, layout].filter(Boolean)), ...names.map((room) => el('section', { className: 'room', testid: 'room', 'data-room': room }, [
      el('h2', { text: room || 'No room' }),
      el('div', { className: 'device-grid' }, rooms.get(room)),
    ])));
  }

  /** A group as a device for the card and the light settings window. */
  groupDevice(group) {
    return {
      id: group.id, isGroup: true, group, name: group.name, room: group.room,
      type: group.has_lights ? 'light' : 'plug', online: group.online, controllable: group.online,
      integrationOn: true, state: group.state,
    };
  }

  /** A group's tile: works like a device's, plus ⋯ for each device. */
  groupTile(group) {
    const card = this.card(this.groupDevice(group));
    card.dataset.testid = 'group-card';
    card.dataset.groupId = group.id;
    card.classList.add('group-card');
    const count = group.device_ids.length;
    card.querySelector('.card-head .muted').textContent = `Group · ${count} device${count === 1 ? '' : 's'}${group.online ? '' : ' · offline'}`;
    card.querySelector('.card-head').append(el('button', {
      type: 'button', className: 'icon-button group-menu', testid: 'group-menu', text: '⋯',
      'aria-label': `${group.name}: each device`, title: 'Each device', onclick: () => this.groups.open(group),
    }));
    return card;
  }

  card(device) {
    // A disconnected device is drawn off (and dimmed by .offline) until it is
    // back online; then its real state shows again on the next refresh.
    const state = device.online ? (device.state || {}) : { ...(device.state || {}), on: false, status: 'off' };
    const on = Boolean(state.on);
    const card = el('article', {
      className: `device-card${on ? ' on' : ''}${device.online ? '' : ' offline'}`,
      testid: 'device-card',
      'data-device-id': device.id,
      'data-device-type': device.type,
      'data-online': String(Boolean(device.online)),
    }, [
      el('div', { className: 'card-head' }, [
        icon(device.type),
        el('div', {}, [
          el('h3', { text: device.name }),
          el('p', { className: 'muted', text: `${TYPE_LABEL[device.type] || device.type}${device.online ? '' : ' · offline'}` }),
        ]),
      ]),
    ]);
    if (!device.integrationOn) {
      card.append(el('p', { className: 'warning', testid: 'integration-off', text: 'This brand is turned off in Settings > Integrations.' }));
    }
    if (POWER_TYPES.has(device.type)) card.append(this.powerToggle(device, on));
    if (device.type === 'light') {
      card.append(el('button', {
        type: 'button', className: 'secondary', testid: 'light-settings-open', text: 'Light settings',
        disabled: !device.controllable, onclick: () => this.lightPanel.open(device),
      }));
    }
    if (device.type === 'light' && on) card.style.setProperty('--light', lightColor(state));
    if (device.type === 'tv') {
      card.append(el('button', {
        type: 'button', className: 'secondary', testid: 'tv-remote-open', text: 'Remote',
        disabled: !device.controllable, onclick: () => this.remote.open(device),
      }));
    }
    // A Cync thermostat (it reports a mode) draws its own dial: see thermostat.js.
    const ownDial = device.type === 'thermostat' && Boolean(state.mode);
    if (TEMPERATURE_TYPES.has(device.type) && !ownDial) card.append(this.dial(device, state));
    if (device.type === 'water_heater') card.append(...heaterExtras(this, device, state));
    if (device.type === 'thermostat') card.append(...thermostatExtras(this, device, state));
    if (device.type === 'sensor') card.append(this.readings(state));
    return card;
  }

  powerToggle(device, on) {
    return el('button', {
      type: 'button',
      className: `toggle${on ? ' on' : ''}`,
      testid: 'power-toggle',
      'aria-pressed': String(on),
      'aria-label': `${device.name} power`,
      disabled: !device.controllable,
      text: on ? 'On' : 'Off',
      onclick: () => this.command(device, on ? 'turn_off' : 'turn_on'),
    });
  }

  /** The home's limits for the device's type, narrowed by the device's own. */
  limitsFor(device) {
    const typeLimits = this.limits[device.type];
    const own = device.limits || {};
    return typeLimits && {
      ...typeLimits,
      min_temperature: own.min_temperature == null ? typeLimits.min_temperature : Math.max(typeLimits.min_temperature, own.min_temperature),
      max_temperature: own.max_temperature == null ? typeLimits.max_temperature : Math.min(typeLimits.max_temperature, own.max_temperature),
    };
  }

  dial(device, state) {
    const limits = this.limitsFor(device);
    const usable = Boolean(limits && limits.enabled) && device.controllable;
    const target = typeof state.target_temperature === 'number' ? state.target_temperature : null;
    const unit = (limits && limits.unit) || state.unit || '';
    const wrap = el('div', { className: 'dial' });
    const fraction = limits && target !== null
      ? (target - limits.min_temperature) / (limits.max_temperature - limits.min_temperature)
      : 0;
    wrap.append(el('div', { className: 'gauge-wrap' }, [
      gauge(fraction, device.type),
      el('div', { className: 'readout' }, [
        el('span', { className: 'target', testid: 'target-temp', text: target === null ? '--' : `${target} °${unit}` }),
        el('span', { className: 'muted', testid: 'target-label', text: 'target' }),
      ]),
    ]));
    if (limits && limits.enabled) {
      wrap.append(el('p', { className: 'muted', testid: 'temp-limits', text: `Allowed ${limits.min_temperature}–${limits.max_temperature} °${limits.unit}` }));
    } else {
      wrap.append(el('p', { className: 'warning', testid: 'limits-missing', text: 'Control is off until an admin sets safety limits.' }));
    }
    const start = target !== null ? target : (limits && limits.default_target) || (limits && limits.min_temperature);
    const step = (delta) => () => this.command(device, 'set_temperature', { temperature: start + delta });
    const atMin = !usable || (target !== null && target - 1 < limits.min_temperature);
    const atMax = !usable || (target !== null && target + 1 > limits.max_temperature);
    wrap.append(el('div', { className: 'dial-buttons' }, [
      el('button', { type: 'button', className: 'round', testid: 'temp-down', 'aria-label': `Lower ${device.name}`, text: '−', disabled: atMin, onclick: step(-1) }),
      el('button', { type: 'button', className: 'round', testid: 'temp-up', 'aria-label': `Raise ${device.name}`, text: '+', disabled: atMax, onclick: step(1) }),
    ]));
    return wrap;
  }

  readings(state) {
    const entries = Object.entries(state);
    if (entries.length === 0) return el('p', { className: 'muted', text: 'No readings yet' });
    return el('dl', { className: 'readings' }, entries.flatMap(([k, v]) => [
      el('dt', { text: k.replace(/_/g, ' ') }), el('dd', { text: String(v) }),
    ]));
  }

  command(device, name, payload = {}) {
    if (device.isGroup) return this.groups.command(device.group, name, payload);
    // A spinner at the card's bottom right until the change is applied.
    document.querySelectorAll(`.device-card[data-device-id="${CSS.escape(device.id)}"]`).forEach((card) => { card.dataset.busy = 'true'; });
    return this.app.run(async () => {
      try {
        await this.app.api.sendCommand(this.app.home.id, device.id, name, payload);
      } finally {
        await this.load(); // redraw first, so "done" means the screen is up to date
      }
      this.app.status.success(`${device.name}: done.`);
    });
  }
}

window.DevicesView = DevicesView;
