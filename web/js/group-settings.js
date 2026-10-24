/**
 * Settings > Devices, top (operators and admins): rooms and groups — create,
 * delete, and choose a group's room. Which group a device is in is chosen on
 * the device's own row. Changes stay in this app (nothing is sent to Cync).
 */

class GroupSettings {
  constructor(app) {
    this.app = app;
  }

  async render(container, { rooms, groups }) {
    this.box = el('div', { className: 'subpanel', testid: 'group-settings' });
    container.append(this.box);
    this.fill(rooms, groups);
  }

  async reload() {
    const [rooms, groups] = await Promise.all([this.app.api.getRooms(this.app.home.id), this.app.api.getGroups(this.app.home.id)]);
    this.fill(rooms, groups);
    this.app.settings.shown = null; // redraw the device rows' room and group lists
    await this.app.settings.load('devices');
  }

  fill(rooms, groups) {
    const homeId = this.app.home.id;
    const newRoom = el('input', { type: 'text', testid: 'room-new-name', maxlength: '50', placeholder: 'Kitchen', 'aria-label': 'New room' });
    const newGroup = el('input', { type: 'text', testid: 'group-new-name', maxlength: '100', placeholder: 'Ceiling lights', 'aria-label': 'New group' });
    const roomSelect = (value, testid) => {
      const select = el('select', { testid }, [el('option', { value: '', text: 'No room' }), ...rooms.map((r) => el('option', { value: r, text: r }))]);
      select.value = value || '';
      return select;
    };
    const newGroupRoom = roomSelect('', 'group-new-room');
    this.box.replaceChildren(
      el('h3', { text: 'Rooms' }),
      el('div', { className: 'chip-list' }, rooms.map((r) => el('span', { className: 'chip', testid: 'room-row', 'data-room': r }, [
        el('span', { text: r }),
        el('button', { type: 'button', className: 'icon-button', testid: 'room-delete', text: '✕', 'aria-label': `Delete room ${r}`,
          onclick: () => this.app.run(async () => { await this.app.api.deleteRoom(homeId, r); await this.reload(); this.app.status.success(`Room ${r} deleted; its devices have no room now.`); }) }),
      ]))),
      el('div', { className: 'row' }, [newRoom, el('button', { type: 'button', testid: 'room-create', text: 'Create room',
        onclick: () => this.app.run(async () => {
          if (!newRoom.value.trim()) throw new Error('Type a name for the room.');
          await this.app.api.createRoom(homeId, newRoom.value.trim());
          await this.reload();
          this.app.status.success('Room created.');
        }) })]),
      el('h3', { text: 'Groups' }),
      el('p', { className: 'muted', text: 'Lights and plugs switched together. Choose each device\'s group on its row below.' }),
      ...groups.map((g) => {
        const name = el('input', { type: 'text', testid: 'group-name', maxlength: '100', value: g.name, 'aria-label': 'Group name' });
        const room = roomSelect(g.room, 'group-room');
        return el('div', { className: 'row', testid: 'group-row', 'data-group-id': g.id }, [
          name, room, el('span', { className: 'muted', text: `${g.device_ids.length} device${g.device_ids.length === 1 ? '' : 's'}${g.source === 'cync' ? ' · from Cync' : ''}` }),
          el('button', { type: 'button', className: 'secondary', testid: 'group-save', text: 'Save',
            onclick: () => this.app.run(async () => { await this.app.api.changeGroup(homeId, g.id, { name: name.value.trim(), room: room.value }); await this.reload(); this.app.status.success(`${name.value.trim()} saved.`); }) }),
          el('button', { type: 'button', className: 'danger', testid: 'group-delete', text: 'Delete',
            onclick: () => this.app.run(async () => { await this.app.api.deleteGroup(homeId, g.id); await this.reload(); this.app.status.success(`${g.name} deleted.`); }) }),
        ]);
      }),
      el('div', { className: 'row', testid: 'group-new' }, [newGroup, newGroupRoom, el('button', { type: 'button', testid: 'group-create', text: 'Create group',
        onclick: () => this.app.run(async () => {
          if (!newGroup.value.trim()) throw new Error('Type a name for the group.');
          await this.app.api.createGroup(homeId, { name: newGroup.value.trim(), room: newGroupRoom.value || null, device_ids: [] });
          await this.reload();
          this.app.status.success('Group created. Choose its devices on their rows below.');
        }) })]),
    );
  }
}

window.GroupSettings = GroupSettings;
