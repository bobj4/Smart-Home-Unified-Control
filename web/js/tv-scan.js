/**
 * Settings > Integrations: "Find TVs on my network" (operators and up).
 * Searches the home network for Samsung, LG and Roku TVs and adds one with
 * a click (turning its brand on first, for owners).
 */

const TV_BRANDS = { samsung: 'Samsung', lg: 'LG', roku: 'Roku' };

function tvScanPanel(view) {
  const app = view.app;
  if (!app.can('operator')) return null;
  const network = el('input', { type: 'text', testid: 'tv-scan-network', placeholder: 'this network (e.g. 192.168.1.0/24)', 'aria-label': 'Network to search' });
  const results = el('div', { className: 'member-list', testid: 'tv-scan-results' });
  const note = formNote('tv-scan-note');
  const add = (tv) => app.run(async () => {
    if (!tv.enabled) await app.api.setIntegration(app.home.id, tv.integration, true);
    if (tv.brand === 'samsung') await app.api.addTv(app.home.id, { name: tv.name, host: tv.host, protocol: 'tizen', ...(tv.mac ? { mac: tv.mac } : {}) });
    else if (tv.brand === 'roku') await app.api.addRoku(app.home.id, { host: tv.host });
    else await app.api.addLgTv(app.home.id, { name: tv.name.replace(' (probably)', ''), host: tv.host });
    tv.added = true;
    tv.enabled = true;
    app.status.success(`${tv.name} added.${tv.brand === 'roku' ? '' : ' Pair it below.'}`);
    app.settings.shown = null;
    await app.settings.load('integrations');
  });
  const row = (tv) => el('div', { className: 'member-row', testid: 'tv-scan-row', 'data-host': tv.host }, [
    el('div', {}, [
      el('strong', { text: tv.name }),
      el('p', { className: 'muted', text: `${TV_BRANDS[tv.brand]} · ${tv.host}${tv.model ? ` · ${tv.model}` : ''}` }),
    ]),
    tv.added
      ? el('span', { className: 'badge', text: 'Added' })
      : el('button', {
        type: 'button', testid: 'tv-scan-add', disabled: !tv.enabled && !app.can('admin'),
        text: tv.enabled ? 'Add' : `Turn on ${TV_BRANDS[tv.brand]} TV and add`,
        title: !tv.enabled && !app.can('admin') ? 'An admin turns brands on' : '', onclick: () => add(tv),
      }),
  ]);
  // Kept on the app, so the page updating itself does not lose them.
  const show = (found) => {
    app.tvScanFound = found;
    results.replaceChildren(...(found.tvs.length
      ? found.tvs.map(row)
      : [el('p', { className: 'muted', testid: 'tv-scan-none', text: `No TVs found on ${found.network}. Is each TV on (or in standby with network wake-up on)?` })]));
  };
  const search = el('button', {
    type: 'button', className: 'secondary', testid: 'tv-scan', text: 'Find TVs',
    onclick: () => runWithNote(app, note, 'Searching your network (a few seconds)…', async () => {
      show({ ...(await app.api.findTvs(app.home.id, network.value.trim() || null)), home: app.home.id });
    }),
  });
  if (app.tvScanFound && app.tvScanFound.home === app.home.id) show(app.tvScanFound);
  return el('div', { className: 'subpanel', testid: 'tv-scan-panel' }, [
    el('h3', { text: 'Find TVs on my network' }),
    el('p', { className: 'muted', text: 'Looks for Samsung, LG and Roku TVs. Leave the network blank to search the one this device is on.' }),
    el('div', { className: 'row' }, [network, search]),
    note,
    results,
  ]);
}

window.tvScanPanel = tvScanPanel;
