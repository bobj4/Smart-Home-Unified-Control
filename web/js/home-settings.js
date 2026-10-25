/**
 * Settings that belong to the current home: safety limits, devices,
 * integrations and the activity log.
 */

const LIMIT_TYPES = [
  ['thermostat', 'Thermostat'],
  ['water_heater', 'Water heater'],
];

function numberOrNull(input) {
  return input.value.trim() === '' ? null : Number(input.value);
}

class HomeSettings {
  constructor(app) {
    this.app = app;
  }

  // ------------------------------------------------------------ safety limits

  async renderSafety(container) {
    const owner = this.app.can('admin');
    const [rows, devices] = await Promise.all([
      this.app.api.getSafetyLimits(this.app.home.id),
      this.app.api.getDevices(this.app.home.id),
    ]);
    const byType = Object.fromEntries(rows.map((r) => [r.device_type, r]));
    container.querySelectorAll('.limits, .actions, .empty').forEach((n) => n.remove());
    // Only the device types this home has.
    const present = new Set(devices.map((d) => d.type));
    const types = LIMIT_TYPES.filter(([type]) => present.has(type));
    if (types.length === 0) {
      container.append(el('p', { className: 'muted empty', testid: 'limits-none', text: 'No thermostats or water heaters yet.' }));
      return;
    }
    const list = el('div', { className: 'limits' }, types.map(([type, label]) => this.limitsRow(type, label, byType[type], owner)));
    container.append(list);
    // Each thermostat and water heater can have narrower limits of its own.
    const limited = devices.filter((d) => types.some(([type]) => type === d.type));
    container.append(el('div', { className: 'limits' }, [
      el('h3', { text: 'Per device (optional, inside the limits above)' }),
      ...limited.map((d) => this.deviceLimitsRow(d, byType[d.type], owner)),
    ]));
    if (owner) {
      container.append(el('div', { className: 'actions' }, [
        el('button', {
          type: 'button', className: 'secondary', testid: 'limits-recommended',
          text: 'Use recommended limits',
          onclick: () => this.app.run(async () => {
            await this.app.api.useRecommendedLimits(this.app.home.id);
            await this.renderSafety(container);
            this.app.status.success('Recommended limits saved.');
          }),
        }),
      ]));
    }
  }

  deviceLimitsRow(device, typeLimits, admin) {
    const own = device.limits || {};
    const unit = (typeLimits && typeLimits.unit) || 'F';
    const input = (testid, value, label) => el('input', {
      type: 'number', step: '0.5', testid, value: value == null ? '' : String(value), disabled: !admin,
      placeholder: 'same as above', 'aria-label': `${label} for ${device.name}`,
    });
    const min = input('device-limits-min', own.min_temperature, 'Lowest');
    const max = input('device-limits-max', own.max_temperature, 'Highest');
    const row = el('form', { className: 'limits-row', testid: 'device-limits-row', 'data-device-id': device.id }, [
      el('strong', { text: device.name }),
      el('div', { className: 'grid-fields' }, [field(`Lowest (°${unit})`, min), field(`Highest (°${unit})`, max)]),
    ]);
    if (admin) {
      row.append(el('button', { type: 'submit', testid: 'device-limits-save', text: 'Save' }));
      row.addEventListener('submit', (event) => {
        event.preventDefault();
        const number = (box) => (box.value.trim() === '' ? null : Number(box.value));
        this.app.run(async () => {
          await this.app.api.setDeviceLimits(this.app.home.id, device.id, { min_temperature: number(min), max_temperature: number(max) });
          this.app.status.success(`Limits saved for ${device.name}.`);
        });
      });
    }
    return row;
  }

  limitsRow(type, label, limits, owner) {
    const value = (key) => (limits && limits[key] !== null && limits[key] !== undefined ? limits[key] : '');
    const number = (testid, key) => el('input', { type: 'number', step: '0.5', testid, value: String(value(key)), disabled: !owner });
    const unit = el('select', { testid: 'limits-unit', disabled: !owner }, ['F', 'C'].map((u) => el('option', { value: u, text: `°${u}` })));
    unit.value = (limits && limits.unit) || 'F';
    const min = number('limits-min', 'min_temperature');
    const max = number('limits-max', 'max_temperature');
    const target = number('limits-default', 'default_target');
    const enabled = el('input', { type: 'checkbox', testid: 'limits-enabled', checked: Boolean(limits && limits.enabled), disabled: !owner });
    const row = el('form', { className: 'limits-row', testid: 'limits-row', 'data-device-type': type }, [
      el('h3', { text: label }),
      el('div', { className: 'grid-fields' }, [
        field('Lowest', min), field('Highest', max), field('Default target', target), field('Unit', unit),
      ]),
      el('label', { className: 'check' }, [enabled, el('span', { text: 'Allow control' })]),
    ]);
    if (owner) {
      row.append(el('button', { type: 'submit', testid: 'limits-save', text: 'Save' }));
      row.addEventListener('submit', (event) => {
        event.preventDefault();
        this.app.run(async () => {
          if (min.value === '' || max.value === '') throw new Error('Enter the lowest and highest temperature.');
          await this.app.api.setSafetyLimits(this.app.home.id, type, {
            unit: unit.value,
            min_temperature: Number(min.value),
            max_temperature: Number(max.value),
            default_target: numberOrNull(target),
            enabled: enabled.checked,
          });
          this.app.status.success(`${label} limits saved.`);
        });
      });
    }
    return row;
  }

  // ------------------------------------------------------------ devices

  renderDevices(container) {
    return new DeviceSettings(this.app).render(container);
  }

  // ------------------------------------------------------------ activity log

  renderActivity(container) {
    return new ActivityLog(this.app).render(container);
  }

  /** One device under its integration, with a delete button (admin and owner). */
  integrationDevice(device) {
    const item = el('div', { className: 'integration-device', testid: 'integration-device', 'data-device-id': device.id }, [
      el('span', { text: `${device.name}${device.room ? ` · ${device.room}` : ''}` }),
    ]);
    const info = deviceInfoButton(device);
    if (!this.app.can('operator')) {
      item.append(info);
      return item;
    }
    const actions = el('div', { className: 'row' }, [info]);
    const trash = el('button', {
      type: 'button', className: 'icon-button', testid: 'integration-device-delete', 'aria-label': `Delete ${device.name}`, title: 'Delete',
      onclick: () => actions.replaceChildren(
        el('span', { text: 'Delete?' }),
        el('button', {
          type: 'button', className: 'danger', testid: 'integration-device-delete-confirm', text: 'Delete',
          onclick: () => this.app.run(async () => {
            await this.app.api.deleteDevice(this.app.home.id, device.id);
            item.remove();
            this.app.status.success(`${device.name} deleted.`);
          }),
        }),
        el('button', { type: 'button', className: 'secondary', text: 'Cancel', onclick: () => actions.replaceChildren(info, trash) }),
      ),
    }, [svg('svg', { viewBox: '0 0 24 24', 'aria-hidden': 'true' }, [svg('path', { d: 'M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6' })])]);
    actions.append(trash);
    item.append(actions);
    return item;
  }

  // ------------------------------------------------------------ integrations

  async renderIntegrations(container) {
    const owner = this.app.can('admin');
    const rows = await this.app.api.getIntegrations(this.app.home.id);
    const devices = await this.app.api.getDevices(this.app.home.id);
    const problems = this.app.can('operator') ? await this.app.api.getIntegrationProblems(this.app.home.id) : {};
    container.append(el('div', { className: 'integration-list' }, rows.flatMap((row) => {
      const toggle = el('input', {
        type: 'checkbox', role: 'switch', className: 'switch', testid: 'integration-toggle',
        checked: row.enabled, disabled: !owner, 'aria-label': `${row.name} on or off`,
      });
      toggle.addEventListener('change', () => this.app.run(async () => {
        try {
          const saved = await this.app.api.setIntegration(this.app.home.id, row.id, toggle.checked);
          if (['rheem_econet', 'samsung_tv', 'frigate', 'cync'].includes(saved.id)) {
            this.app.settings.shown = null; // redraw to show or hide the account panel
            this.app.route();
          }
          this.app.status.success(`${saved.name} turned ${saved.enabled ? 'on' : 'off'}.`);
        } catch (error) {
          toggle.checked = !toggle.checked;
          throw error;
        }
      }));
      const rowEl = el('div', { className: 'integration-row', testid: 'integration-row', 'data-integration': row.id, 'data-available': String(row.available) }, [
        el('div', {}, [
          el('strong', { text: row.name }),
          row.available ? null : el('span', { className: 'badge', text: 'Not built yet' }),
          el('p', { className: 'muted', text: row.description }),
          row.enabled && problems[row.id]
            ? el('p', { className: 'error', testid: 'integration-problem', text: `Connection problem: ${problems[row.id].reason}` })
            : null,
        ]),
        toggle,
      ]);
      const own = devices.filter((d) => d.integration === row.id);
      if (own.length === 0) return [rowEl];
      return [rowEl, el('div', { className: 'integration-devices', testid: 'integration-devices', 'data-integration': row.id },
        own.map((d) => this.integrationDevice(d)))];
    })));
    const rheemRow = rows.find((row) => row.id === 'rheem_econet');
    if (rheemRow && rheemRow.enabled && this.app.can('operator')) {
      await new RheemPanel(this.app).render(container);
    }
    const cyncRow = rows.find((row) => row.id === 'cync');
    if (cyncRow && cyncRow.enabled && this.app.can('operator')) {
      await new CyncPanel(this.app).render(container);
    }
    const frigateRow = rows.find((row) => row.id === 'frigate');
    if (frigateRow && frigateRow.enabled && this.app.can('admin')) {
      await new FrigatePanel(this.app).render(container);
    }
    const samsungRow = rows.find((row) => row.id === 'samsung_tv');
    if (samsungRow && samsungRow.enabled && this.app.can('operator')) {
      await new SamsungPanel(this.app).render(container);
    }

  }

}

window.HomeSettings = HomeSettings;
