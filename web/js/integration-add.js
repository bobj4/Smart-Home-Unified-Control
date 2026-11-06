/**
 * Settings > Integrations, top: "Add integration ▾" (owners). It lists only
 * the brands not turned on yet; picking one turns it on, redraws the page
 * and goes to its setup (account, bridge or devices).
 */

const SETUP_PANELS = {
  cync: 'cync-account', rheem_econet: 'rheem-account', frigate: 'frigate-server', samsung_tv: 'samsung-tvs',
  lg_tv: 'lg-tvs', roku_tv: 'roku-tvs', hue: 'hue', ratgdo: 'ratgdo-doors', kasa: 'kasa-devices',
};

function addIntegrationRow(view, rows) {
  if (!view.app.can('admin')) return null;
  const off = rows.filter((row) => !row.enabled && row.available);
  if (off.length === 0) return null;
  const select = el('select', { testid: 'integration-add', 'aria-label': 'Add integration' }, [
    el('option', { value: '', text: 'Add integration…' }),
    ...off.map((row) => el('option', { value: row.id, text: row.name })),
  ]);
  select.addEventListener('change', () => {
    const id = select.value;
    if (!id) return;
    view.app.run(async () => {
      const saved = await view.app.api.setIntegration(view.app.home.id, id, true);
      view.app.status.success(`${saved.name} turned on. Set it up below.`);
      view.app.settings.shown = null;
      await view.app.settings.load('integrations');
      const target = byTestId(SETUP_PANELS[id] || '') || document.querySelector(`[data-testid="integration-row"][data-integration="${CSS.escape(id)}"]`);
      if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });
  return el('div', { className: 'row add-integration', testid: 'integration-add-row' }, [select]);
}

window.addIntegrationRow = addIntegrationRow;
