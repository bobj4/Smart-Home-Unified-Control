/**
 * Devices page room order, per user: the thermostats have their own room,
 * "Thermostats", at the top until moved. "Edit layout" opens a window to
 * move rooms up and down; the order is saved for this user only.
 */

const THERMOSTATS_ROOM = 'Thermostats';

/** Room names in the user's order; rooms not in it follow by name ("No room" last). */
function orderRooms(names, order) {
  const wanted = (order && order.length ? order : [THERMOSTATS_ROOM]).filter((n) => names.includes(n));
  const rest = names.filter((n) => !wanted.includes(n))
    .sort((a, b) => (a === '') - (b === '') || a.localeCompare(b));
  return [...wanted, ...rest];
}

/** The room a device is shown in. */
function displayRoom(device) {
  return device.type === 'thermostat' ? THERMOSTATS_ROOM : (device.room || '');
}

class RoomLayoutEditor {
  constructor(view) {
    this.view = view;
    this.overlay = el('div', { className: 'overlay', hidden: true });
    this.overlay.addEventListener('click', (e) => { if (e.target === this.overlay) this.close(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !this.overlay.hidden) this.close(); });
    document.body.append(this.overlay);
  }

  open(rooms) {
    this.rooms = [...rooms];
    this.overlay.hidden = false;
    this.draw();
  }

  move(index, by) {
    const to = index + by;
    if (to < 0 || to >= this.rooms.length) return;
    [this.rooms[index], this.rooms[to]] = [this.rooms[to], this.rooms[index]];
    this.draw();
    const buttons = this.overlay.querySelectorAll(`[data-testid="layout-${by < 0 ? 'up' : 'down'}"]`);
    if (buttons[to]) buttons[to].focus(); // keep the keyboard on the room being moved
  }

  draw() {
    const last = this.rooms.length - 1;
    const rows = this.rooms.map((room, i) => el('li', { className: 'layout-row', testid: 'layout-room', 'data-room': room }, [
      el('span', { text: room || 'No room' }),
      el('button', { type: 'button', className: 'ghost', testid: 'layout-up', text: '↑', 'aria-label': `Move ${room || 'No room'} up`, disabled: i === 0, onclick: () => this.move(i, -1) }),
      el('button', { type: 'button', className: 'ghost', testid: 'layout-down', text: '↓', 'aria-label': `Move ${room || 'No room'} down`, disabled: i === last, onclick: () => this.move(i, 1) }),
    ]));
    this.overlay.replaceChildren(el('div', { className: 'remote info-panel', testid: 'layout-panel', role: 'dialog', 'aria-label': 'Room order' }, [
      el('div', { className: 'remote-head' }, [
        el('h2', { text: 'Room order' }),
        el('button', { type: 'button', className: 'ghost', testid: 'layout-close', text: '✕', 'aria-label': 'Close', onclick: () => this.close() }),
      ]),
      el('p', { className: 'muted', text: 'Only your Devices page changes; everyone has their own order.' }),
      el('ol', { className: 'layout-list' }, rows),
      el('div', { className: 'row' }, [
        el('button', { type: 'button', testid: 'layout-save', text: 'Save', onclick: () => this.save(this.rooms) }),
        el('button', { type: 'button', className: 'secondary', testid: 'layout-reset', text: 'Reset', onclick: () => this.save([THERMOSTATS_ROOM]) }),
        el('button', { type: 'button', className: 'secondary', testid: 'layout-cancel', text: 'Cancel', onclick: () => this.close() }),
      ]),
    ]));
  }

  save(order) {
    const { app } = this.view;
    return app.run(async () => {
      const saved = await app.api.setLayout(app.home.id, order);
      this.view.roomOrder = saved.room_order;
      this.close();
      this.view.render(this.view.lastDevices);
      app.status.success('Room order saved.');
    });
  }

  close() {
    this.overlay.hidden = true;
    this.overlay.replaceChildren();
  }
}

window.orderRooms = orderRooms;
window.displayRoom = displayRoom;
window.RoomLayoutEditor = RoomLayoutEditor;
