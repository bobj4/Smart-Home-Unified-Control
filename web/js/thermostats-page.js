/**
 * Pages of their own for some kinds of device, each with a link beside
 * "Devices": Thermostats (#/devices/thermostats, with water heaters: anything
 * set by temperature) and Doors (#/devices/doors: remote doors such as
 * garage doors). A link shows only while the home has such a device from an
 * integration that is on. Each person can also keep them off the Devices
 * page (Edit layout > "... only on their own page").
 */

const THERMOSTAT_PAGE_TYPES = ['thermostat', 'water_heater'];
const DOOR_PAGE_TYPES = ['garage_door'];

const DEVICE_PAGES = [
  {
    id: 'thermostats', title: 'Thermostats', types: THERMOSTAT_PAGE_TYPES, apart: 'thermostatsApart',
    empty: 'This home has no thermostats or water heaters.',
  },
  {
    id: 'doors', title: 'Doors', types: DOOR_PAGE_TYPES, apart: 'doorsApart',
    empty: 'This home has no remote doors (or their integration is off).',
  },
];

/** The page's devices: of its types, from integrations that are on. */
function pageDevices(page, devices) {
  return devices.filter((d) => page.types.includes(d.type) && d.integrationOn !== false);
}

/** Draw a device page instead of the Devices page; false when not on one. */
function drawThermostatsPage(view, devices) {
  const sub = view.app.currentRoute()[1];
  let drawn = null;
  for (const page of DEVICE_PAGES) {
    const own = pageDevices(page, devices);
    const link = byTestId(`nav-${page.id}`);
    link.hidden = own.length === 0;
    link.classList.toggle('active', sub === page.id);
    if (sub === page.id) drawn = { page, own };
  }
  byTestId('nav-devices').classList.toggle('active', !drawn);
  if (!drawn) return false;
  const { page, own } = drawn;
  view.root.replaceChildren(own.length
    ? el('section', { className: 'room', testid: `${page.id}-page` }, [
      el('h2', { text: page.title }),
      el('div', { className: 'device-grid' }, own.map((d) => view.card(d))),
    ])
    : el('p', { className: 'empty', testid: `${page.id}-empty`, text: page.empty }));
  return true;
}

/** The devices for the Devices page itself. */
function devicesPageDevices(view, devices) {
  const away = DEVICE_PAGES.filter((page) => view[page.apart]).flatMap((page) => page.types);
  return away.length ? devices.filter((d) => !away.includes(d.type)) : devices;
}

window.drawThermostatsPage = drawThermostatsPage;
window.devicesPageDevices = devicesPageDevices;
