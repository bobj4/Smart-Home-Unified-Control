/**
 * Settings > Devices: rooms and groups at the top (create and delete), then
 * every device with its name, room and group; filter by type; one Save at
 * the top and the bottom for every changed row; Delete per device.
 */

const DEVICE_TYPE_LABELS = { light: 'Lights', plug: 'Plugs', tv: 'TVs', thermostat: 'Thermostats', water_heater: 'Water heaters', camera: 'Cameras', sensor: 'Sensors' };

class DeviceSettings {
  constructor(app) {
    this.app = app;
  }

  async render(container) {
    const admin = this.app.can('operator');
    const homeId = this.app.home.id;
    const [devices, groups, rooms] = await Promise.all([
      this.app.api.getDevices(homeId), this.app.api.getGroups(homeId), this.app.api.getRooms(homeId),
    ]);
    if (admin) await new GroupSettings(this.app).render(container, { rooms, groups });
    if (devices.length === 0) {
      container.append(el('p', { className: 'muted', text: 'No devices yet.' }));
      return;
    }
    const roomList = el('datalist', { id: 'room-options' }, rooms.map((r) => el('option', { value: r })));
    const memberOf = new Map(groups.flatMap((g) => g.device_ids.map((id) => [id, g.id])));
    const rows = el('div', { className: 'device-rows' }, devices.map((d) => this.deviceRow(d, admin, groups, memberOf.get(d.id) || '')));
    const types = [...new Set(devices.map((d) => d.type))];
    const filter = el('select', { testid: 'device-filter', 'aria-label': 'Show device type' }, [
      el('option', { value: '', text: 'All types' }),
      ...types.map((t) => el('option', { value: t, text: DEVICE_TYPE_LABELS[t] || t })),
    ]);
    filter.addEventListener('change', () => {
      rows.querySelectorAll('[data-testid="device-row"]').forEach((row) => {
        row.hidden = Boolean(filter.value) && row.dataset.deviceType !== filter.value;
      });
    });
    const tools = [field('Show', filter)];
    if (!admin) {
      container.append(roomList, el('div', { className: 'actions' }, tools), rows);
      return;
    }
    const saveAll = () => this.app.run(async () => {
      const changed = [...rows.querySelectorAll('[data-testid="device-row"]')].filter((row) => row.dataset.changed === 'true');
      for (const row of changed) {
        const name = row.querySelector('[data-testid="device-name"]').value.trim();
        const room = row.querySelector('[data-testid="device-room"]').value.trim();
        await this.app.api.updateDevice(homeId, row.dataset.deviceId, { name, room });
        const group = row.querySelector('[data-testid="device-group"]');
        if (group && group.value !== group.dataset.initial) {
          await this.app.api.setDeviceGroup(homeId, row.dataset.deviceId, group.value || null);
          group.dataset.initial = group.value;
        }
        row.dataset.changed = 'false';
      }
      this.app.status.success(changed.length ? `Saved ${changed.length} device${changed.length === 1 ? '' : 's'}.` : 'Nothing to save.');
    });
    const saveButton = (where) => el('button', { type: 'button', testid: `device-save-${where}`, text: 'Save changes', onclick: saveAll });
    container.append(
      roomList,
      el('div', { className: 'actions' }, [...tools, saveButton('top')]),
      rows,
      el('div', { className: 'actions' }, [saveButton('bottom')]),
    );
  }

  deviceRow(device, admin, groups, groupId) {
    const name = el('input', { type: 'text', testid: 'device-name', value: device.name, maxlength: '100', disabled: !admin });
    // Type a new room or pick one from the list.
    const room = el('input', { type: 'text', testid: 'device-room', value: device.room || '', maxlength: '50', disabled: !admin, list: 'room-options', placeholder: 'No room' });
    const fields = [field('Name', name), field('Room', room)];
    if (['light', 'plug'].includes(device.type)) {
      const group = el('select', { testid: 'device-group', disabled: !admin, 'aria-label': `Group for ${device.name}` }, [
        el('option', { value: '', text: 'No group' }),
        ...groups.map((g) => el('option', { value: g.id, text: g.name })),
      ]);
      group.value = groupId;
      group.dataset.initial = groupId;
      fields.push(field('Group', group));
    }
    const row = el('form', { className: 'device-row', testid: 'device-row', 'data-device-id': device.id, 'data-device-type': device.type }, [
      el('div', { className: 'grid-fields' }, fields),
      deviceInfoButton(device),
      el('span', { className: 'muted', text: typeLabel(device.type) }),
    ]);
    if (admin) {
      row.addEventListener('input', () => { row.dataset.changed = 'true'; });
      row.addEventListener('change', () => { row.dataset.changed = 'true'; });
      row.addEventListener('submit', (event) => event.preventDefault());
      const actions = el('div', { className: 'row' });
      const trash = el('button', { type: 'button', className: 'danger', testid: 'device-delete', text: 'Delete' });
      trash.addEventListener('click', () => actions.replaceChildren(
        el('span', { text: 'Delete?' }),
        el('button', {
          type: 'button', className: 'danger', testid: 'device-delete-confirm', text: 'Delete',
          onclick: () => this.app.run(async () => {
            await this.app.api.deleteDevice(this.app.home.id, device.id);
            row.remove();
            this.app.status.success(`${device.name} deleted.`);
          }),
        }),
        el('button', { type: 'button', className: 'secondary', text: 'Cancel', onclick: () => actions.replaceChildren(trash) }),
      ));
      actions.append(trash);
      row.append(actions);
    }
    return row;
  }
}

window.DeviceSettings = DeviceSettings;
