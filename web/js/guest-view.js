/**
 * The Devices page for a guest: only the devices their access allows (the
 * server decides and enforces it), and, if the admin chose so, the others
 * greyed out with no controls and no state.
 */

/** [devices, limits, integrations, groups, display] like DevicesView.load reads them. */
async function guestDevicesData(app, homeId) {
  const page = await app.api.getGuestPage(homeId);
  app.guestAccess = page.access;
  const integrations = page.integrations_on.map((id) => ({ id, enabled: true }));
  return [page.devices, page.limits, integrations, [], { show_grouped_devices: false }];
}

/** Whether this control is shown: always for members and up; for a guest,
 * only with that permission (the server refuses it otherwise anyway). */
function guestMay(app, permission) {
  return !app.isGuest() || Boolean(app.guestAccess && app.guestAccess[permission]);
}

/** A device a guest may not use. */
function blockedCard(device) {
  return el('article', {
    className: 'device-card offline blocked', testid: 'device-card', 'data-device-id': device.id,
    'data-device-type': device.type, 'data-blocked': 'true',
  }, [
    el('div', { className: 'card-head' }, [
      icon(device.type),
      el('div', {}, [
        el('h3', { text: device.name }),
        el('p', { className: 'muted', testid: 'device-blocked', text: `${typeLabel(device.type)} · not available to you` }),
      ]),
    ]),
  ]);
}

window.guestDevicesData = guestDevicesData;
window.blockedCard = blockedCard;
window.guestMay = guestMay;
