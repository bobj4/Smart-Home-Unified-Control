/**
 * Settings > Safety Settings: who may change thermostat installer settings
 * (system type, furnace, power wires, thresholds, calibration...). Shown
 * while the home has a thermostat; only admins change it.
 */

const INSTALLER_ROLES = [
  ['admin', 'Admins only'],
  ['operator', 'Operators and admins'],
  ['member', 'Every member (not guests)'],
];

async function thermostatAccessBox(app) {
  const access = await app.api.get(`/homes/${encodeURIComponent(app.home.id)}/thermostat-access`);
  const select = el('select', { testid: 'thermostat-installer-role', 'aria-label': 'Who may change thermostat installer settings', disabled: !app.can('admin') },
    INSTALLER_ROLES.map(([value, text]) => el('option', { value, text })));
  select.value = access.installer_role;
  select.addEventListener('change', () => app.run(async () => {
    try {
      const saved = await app.api.put(`/homes/${encodeURIComponent(app.home.id)}/thermostat-access`, { installer_role: select.value });
      select.value = saved.installer_role;
      app.status.success(`Thermostat installer settings: ${INSTALLER_ROLES.find(([v]) => v === saved.installer_role)[1].toLowerCase()}.`);
    } catch (error) {
      select.value = access.installer_role;
      throw error;
    }
  }));
  return el('div', { className: 'limits', testid: 'thermostat-access' }, [
    el('h3', { text: 'Thermostat installer settings' }),
    settingRow(
      'Who may change them',
      'System type, furnace, power wires, thresholds, calibration, humidity, fan and heat pump settings in a thermostat\'s Settings. Early On, the screen\'s unit and daylight saving time stay open to every member.',
      select,
    ),
  ]);
}

window.thermostatAccessBox = thermostatAccessBox;
