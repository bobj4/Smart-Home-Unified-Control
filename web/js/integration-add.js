/**
 * Settings > Integrations (owners): only the brands in use are listed, each
 * with "Remove integration"; the rest are in "Add integration ▾" at the top.
 * Picking one turns it on, redraws the page and goes to its setup (account,
 * bridge or devices); removing one turns it off and puts it back in the list.
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
      await view.app.camerasAvailable(); // the Cameras link follows Frigate
      const target = byTestId(SETUP_PANELS[id] || '') || document.querySelector(`[data-testid="integration-row"][data-integration="${CSS.escape(id)}"]`);
      if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });
  return el('div', { className: 'row add-integration', testid: 'integration-add-row' }, [select]);
}

/** Turn an integration off (asks first): it goes back to "Add integration". */
function integrationRemoveButton(view, row) {
  const box = el('div', { className: 'row' });
  const ask = el('button', {
    type: 'button', className: 'secondary', testid: 'integration-remove', text: 'Remove integration',
    onclick: () => box.replaceChildren(
      el('span', { text: row.id === 'simulated' ? 'Remove? Its demo devices are deleted.' : 'Remove? It accepts no commands until added again.' }),
      el('button', {
        type: 'button', className: 'danger', testid: 'integration-remove-confirm', text: 'Remove',
        onclick: () => view.app.run(async () => {
          const saved = await view.app.api.setIntegration(view.app.home.id, row.id, false);
          view.app.status.success(`${saved.name} removed. Add it again from "Add integration".`);
          view.app.settings.shown = null;
          await view.app.settings.load('integrations');
          await view.app.camerasAvailable();
        }),
      }),
      el('button', { type: 'button', className: 'secondary', testid: 'integration-remove-cancel', text: 'Cancel', onclick: () => box.replaceChildren(ask) }),
    ),
  });
  box.append(ask);
  return box;
}

window.addIntegrationRow = addIntegrationRow;
window.integrationRemoveButton = integrationRemoveButton;
