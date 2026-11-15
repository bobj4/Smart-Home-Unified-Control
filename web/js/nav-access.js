/**
 * Which of the top tabs show. Cameras: operators and up (and guests allowed
 * to see them), while Frigate is on. Schedules and Scenes: everyone in the
 * home but guests, and guests allowed to run scenes.
 */

async function guestAccess(app) {
  try {
    return await app.api.getGuestPage(app.home.id);
  } catch (error) {
    return null;
  }
}

async function camerasAvailable(app) {
  let on = false;
  if (app.isGuest()) {
    const page = await guestAccess(app);
    on = Boolean(page && page.access.cameras && page.integrations_on.includes('frigate'));
  } else if (app.can('operator')) {
    try {
      const integrations = await app.api.getIntegrations(app.home.id);
      on = integrations.some((i) => i.id === 'frigate' && i.enabled);
    } catch (error) {
      on = false;
    }
  }
  byTestId('nav-cameras').hidden = !on;
  return on;
}

async function schedulesAvailable(app) {
  let on = Boolean(app.home);
  if (on && app.isGuest()) {
    const page = await guestAccess(app);
    on = Boolean(page && page.access.scenes);
  }
  byTestId('nav-schedules').hidden = !on;
  return on;
}

window.camerasAvailable = camerasAvailable;
window.schedulesAvailable = schedulesAvailable;
