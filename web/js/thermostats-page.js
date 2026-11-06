/**
 * Thermostats on a page of their own (#/devices/thermostats, the
 * "Thermostats" link). Each person can also keep them off the Devices page
 * (Edit layout > "Thermostats only on their own page").
 */

/** Draw the thermostats page instead of the Devices page; false when not on it. */
function drawThermostatsPage(view, devices) {
  const thermostats = devices.filter((d) => d.type === 'thermostat');
  const link = byTestId('nav-thermostats');
  link.hidden = thermostats.length === 0;
  const onPage = view.app.currentRoute()[1] === 'thermostats';
  link.classList.toggle('active', onPage);
  byTestId('nav-devices').classList.toggle('active', !onPage);
  if (!onPage) return false;
  view.root.replaceChildren(thermostats.length
    ? el('section', { className: 'room', testid: 'thermostats-page' }, [
      el('h2', { text: 'Thermostats' }),
      el('div', { className: 'device-grid' }, thermostats.map((d) => view.card(d))),
    ])
    : el('p', { className: 'empty', testid: 'thermostats-empty', text: 'This home has no thermostats.' }));
  return true;
}

/** The devices for the Devices page itself. */
function devicesPageDevices(view, devices) {
  return view.thermostatsApart ? devices.filter((d) => d.type !== 'thermostat') : devices;
}

window.drawThermostatsPage = drawThermostatsPage;
window.devicesPageDevices = devicesPageDevices;
