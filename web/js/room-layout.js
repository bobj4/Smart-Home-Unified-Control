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
    const grid = this.view.grid || { columns: 1, sizes: {} };
    this.columns = grid.columns;
    this.sizes = { ...grid.sizes };
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
      this.wide() ? this.widthSelect(room) : null,
      el('button', { type: 'button', className: 'ghost', testid: 'layout-up', text: '↑', 'aria-label': `Move ${room || 'No room'} up`, disabled: i === 0, onclick: () => this.move(i, -1) }),
      el('button', { type: 'button', className: 'ghost', testid: 'layout-down', text: '↓', 'aria-label': `Move ${room || 'No room'} down`, disabled: i === last, onclick: () => this.move(i, 1) }),
    ]));
    this.overlay.replaceChildren(el('div', { className: 'remote info-panel', testid: 'layout-panel', role: 'dialog', 'aria-label': 'Room order' }, [
      el('div', { className: 'remote-head' }, [
        el('h2', { text: 'Layout' }),
        el('button', { type: 'button', className: 'ghost', testid: 'layout-close', text: '✕', 'aria-label': 'Close', onclick: () => this.close() }),
      ]),
      el('p', { className: 'muted', text: `Only your Devices page on ${this.view.layoutScreen === 'phone' ? 'phones' : 'larger screens'} changes; everyone has their own order.` }),
      this.wide() ? this.columnsChoice() : null,
      el('ol', { className: 'layout-list' }, rows),
      this.thermostatsChoice(),
      el('div', { className: 'row' }, [
        el('button', { type: 'button', testid: 'layout-save', text: 'Save', onclick: () => this.save(this.rooms) }),
        el('button', { type: 'button', className: 'secondary', testid: 'layout-reset', text: 'Reset', onclick: () => { this.columns = this.wide() ? 2 : 1; this.sizes = {}; this.save([THERMOSTATS_ROOM]); } }),
        el('button', { type: 'button', className: 'secondary', testid: 'layout-cancel', text: 'Cancel', onclick: () => this.close() }),
      ]),
    ]));
  }

  wide() {
    return this.view.layoutScreen !== 'phone';
  }

  /** Larger screens: rooms side by side, in this many columns. */
  columnsChoice() {
    const select = el('select', { testid: 'layout-columns', 'aria-label': 'Columns' },
      [1, 2, 3, 4].map((n) => el('option', { value: String(n), text: n === 1 ? '1 (rooms one under another)' : `${n} side by side` })));
    select.value = String(this.columns);
    select.addEventListener('change', () => { this.columns = Number(select.value); this.draw(); });
    return field('Columns', select);
  }

  /** How many columns a room is wide. */
  widthSelect(room) {
    const select = el('select', { testid: 'layout-width', 'aria-label': `Width of ${room || 'No room'}`, disabled: this.columns === 1 },
      Array.from({ length: this.columns }, (_, i) => el('option', { value: String(i + 1), text: i + 1 === this.columns ? 'Full width' : `${i + 1} column${i ? 's' : ''}` })));
    select.value = String(Math.min(this.sizes[room] || 1, this.columns));
    select.addEventListener('change', () => { this.sizes[room] = Number(select.value); });
    return select;
  }

  /** Only for homes with thermostats: keep them on their own page. */
  thermostatsChoice() {
    this.apart = null;
    if (!(this.view.lastDevices || []).some((d) => d.type === 'thermostat')) return null;
    this.apart = el('input', { type: 'checkbox', testid: 'layout-thermostats-apart', checked: Boolean(this.view.thermostatsApart) });
    return el('label', { className: 'check' }, [this.apart, ' Thermostats only on their own page (the Thermostats link)']);
  }

  save(order) {
    const { app } = this.view;
    return app.run(async () => {
      const apart = this.apart ? this.apart.checked : this.view.thermostatsApart;
      const layout = { room_order: order, screen: this.view.layoutScreen, thermostats_apart: apart };
      if (this.wide()) {
        const sizes = Object.fromEntries(Object.entries(this.sizes).filter(([room, span]) => order.includes(room) && span > 1));
        layout.grid = { columns: this.columns, sizes };
      }
      const saved = await app.api.setLayout(app.home.id, layout);
      this.view.grid = saved.grid;
      this.view.roomOrder = saved.room_order;
      this.view.thermostatsApart = saved.thermostats_apart;
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
    view.thermostatsApart = Boolean(layout.thermostats_apart);
    view.grid = layout.grid || null;
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
  const section = el('section', { className: `room${shut ? ' collapsed' : ''}`, testid: 'room', 'data-room': room }, [toggle, grid]);
  const span = view.grid && view.grid.sizes ? view.grid.sizes[room] : null;
  if (span) section.style.gridColumn = `span ${Math.min(span, view.grid.columns)}`;
  return section;
}

/** Rooms side by side: the columns chosen in Edit layout (one on phones). */
function roomsGrid(view, sections) {
  const columns = (view.grid && view.grid.columns) || 1;
  const box = el('div', { className: 'rooms-grid', testid: 'rooms-grid', 'data-columns': String(columns) }, sections);
  box.style.setProperty('--room-columns', String(columns));
  return box;
}

window.loadLayout = loadLayout;
window.roomSection = roomSection;
window.roomsGrid = roomsGrid;
window.orderRooms = orderRooms;
window.displayRoom = displayRoom;
window.RoomLayoutEditor = RoomLayoutEditor;
