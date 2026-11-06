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
      el('p', { className: 'muted', text: `Only your Devices page on ${this.view.layoutScreen === 'phone' ? 'phones' : 'larger screens'} changes; everyone has their own order.` }),
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
      const saved = await app.api.setLayout(app.home.id, { room_order: order, screen: this.view.layoutScreen });
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

/** Phones get a layout of their own (order and folded rooms). */
const PHONE_SCREEN = window.matchMedia('(max-width: 700px)');
const screenType = () => (PHONE_SCREEN.matches ? 'phone' : 'wide');

/** The user's layout for this home and screen type, read once (again when either changes). */
async function loadLayout(view, homeId) {
  if (!view.watchingScreen) {
    view.watchingScreen = true;
    PHONE_SCREEN.addEventListener('change', () => { if (view.app.home) view.load().catch((e) => view.app.handleError(e)); });
  }
  const screen = screenType();
  if (view.layoutHome === homeId && view.layoutScreen === screen) return;
  try {
    const layout = await view.app.api.getLayout(homeId, screen);
    view.roomOrder = layout.room_order;
    view.collapsed = new Set(layout.collapsed || []);
    view.layoutFilters = layout.filters;
  } catch (error) {
    view.roomOrder = null; // the default order
    view.collapsed = new Set();
    view.layoutFilters = null;
  }
  if (view.filters) view.filters.use(view.layoutFilters);
  view.layoutHome = homeId;
  view.layoutScreen = screen;
}

/** A room on the Devices page; its heading folds it shut or open (remembered). */
function roomSection(view, room, tiles) {
  const shut = view.collapsed ? view.collapsed.has(room) : false;
  const label = room || 'No room';
  const grid = el('div', { className: 'device-grid', hidden: shut });
  grid.append(...tiles);
  const toggle = el('button', {
    type: 'button', className: 'room-toggle', testid: 'room-toggle', 'aria-expanded': String(!shut),
    title: shut ? `Show ${label}` : `Hide ${label}`,
  }, [el('span', { className: 'room-caret', text: '▾', 'aria-hidden': 'true' }), el('h2', { text: label }), shut ? el('span', { className: 'muted room-count', text: `${tiles.length}` }) : null]);
  toggle.addEventListener('click', () => {
    if (!view.collapsed) view.collapsed = new Set();
    if (view.collapsed.has(room)) view.collapsed.delete(room);
    else view.collapsed.add(room);
    view.render(view.lastDevices);
    view.app.api.setLayout(view.app.home.id, { collapsed: [...view.collapsed], screen: view.layoutScreen })
      .catch((error) => view.app.handleError(error));
  });
  return el('section', { className: `room${shut ? ' collapsed' : ''}`, testid: 'room', 'data-room': room }, [toggle, grid]);
}

window.loadLayout = loadLayout;
window.roomSection = roomSection;
window.orderRooms = orderRooms;
window.displayRoom = displayRoom;
window.RoomLayoutEditor = RoomLayoutEditor;
