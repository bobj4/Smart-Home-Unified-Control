/**
 * Settings > Integrations > Samsung TV, below the TVs: an optional
 * SmartThings link. With a token, each TV can be linked to its SmartThings
 * device, and its remote then lists the TV's inputs by name ("PlayStation"
 * rather than HDMI 2) and picks one directly.
 */

class SmartThingsPanel {
  constructor(app) {
    this.app = app;
  }

  async render(container) {
    this.box = el('div', { className: 'subpanel', testid: 'smartthings' });
    container.append(this.box);
    await this.load();
  }

  async load() {
    const homeId = this.app.home.id;
    let info;
    try {
      info = await this.app.api.getSmartThings(homeId);
    } catch (error) {
      // A token that stopped working: say so, and let a new one be added.
      info = { connected: false, tvs: [], links: {}, problem: error.message };
    }
    this.draw(info, await this.app.api.getTvs(homeId));
  }

  draw(info, tvs) {
    const intro = el('p', { className: 'muted', text: 'Optional. Lets each TV\'s remote list its inputs by name and switch to one directly.' });
    const problem = info.problem ? el('p', { className: 'error', testid: 'smartthings-problem', text: info.problem }) : null;
    if (!info.connected) {
      const token = el('input', { type: 'password', testid: 'smartthings-token', autocomplete: 'off', required: true, minlength: '10', maxlength: '200' });
      const form = el('form', {}, [
        field('Personal access token', token),
        el('p', { className: 'muted' }, ['Make one at ', el('a', { href: 'https://account.smartthings.com/tokens', target: '_blank', rel: 'noopener', text: 'account.smartthings.com/tokens' }), ' with the Devices permissions (list, see and control).']),
        el('button', { type: 'submit', testid: 'smartthings-connect', text: 'Connect SmartThings' }),
      ]);
      form.addEventListener('submit', (event) => {
        event.preventDefault();
        this.app.run(async () => {
          const saved = await this.app.api.connectSmartThings(this.app.home.id, token.value.trim());
          this.draw(saved, tvs);
          this.app.status.success(`SmartThings connected: ${saved.tvs.length} TV${saved.tvs.length === 1 ? '' : 's'} found.`);
        });
      });
      this.box.replaceChildren(el('h3', { text: 'SmartThings (TV inputs by name)' }), intro, problem, form);
      return;
    }
    const rows = tvs.map((tv) => {
      const select = el('select', { testid: 'smartthings-link', 'data-device-id': tv.device_id, 'aria-label': `${tv.name} in SmartThings` }, [
        el('option', { value: '', text: 'Not linked' }),
        ...info.tvs.map((st) => el('option', { value: st.id, text: st.name })),
      ]);
      select.value = info.links[tv.device_id] || '';
      select.addEventListener('change', () => this.app.run(async () => {
        await this.app.api.linkTv(this.app.home.id, tv.device_id, select.value || null);
        this.app.status.success(select.value ? `${tv.name} linked.` : `${tv.name} unlinked.`);
      }));
      return field(tv.name, select);
    });
    this.box.replaceChildren(
      el('h3', { text: 'SmartThings (TV inputs by name)' }),
      el('p', { className: 'note', testid: 'smartthings-connected', text: 'Connected. Choose which SmartThings TV each TV is.' }),
      rows.length ? el('div', { className: 'grid-fields' }, rows) : el('p', { className: 'muted', text: 'Add a TV above first.' }),
      el('button', {
        type: 'button', className: 'secondary', testid: 'smartthings-disconnect', text: 'Disconnect SmartThings',
        onclick: () => this.app.run(async () => {
          this.draw(await this.app.api.disconnectSmartThings(this.app.home.id), tvs);
          this.app.status.success('SmartThings disconnected.');
        }),
      }),
    );
  }
}

window.SmartThingsPanel = SmartThingsPanel;
