/**
 * Settings > Integrations > Samsung TV, below the TVs: an optional
 * SmartThings link. Each TV can then be linked to its SmartThings device, and
 * its remote lists the TV's inputs by name ("PlayStation" rather than HDMI 2)
 * and picks one directly.
 *
 * Connected by signing in (OAuth: a SmartApp's client ID and secret; it
 * renews itself) or with a personal token (lasts 24 hours). The sign-in comes
 * back to /?smartthings=connected (or ?smartthings_error=...) on this page.
 */

const SMARTTHINGS_CALLBACK = '/api/v1/smartthings/callback';

class SmartThingsPanel {
  constructor(app) {
    this.app = app;
  }

  async render(container) {
    this.box = el('div', { className: 'subpanel', testid: 'smartthings' });
    container.append(this.box);
    this.signInResult();
    await this.load();
  }

  /** Back from signing in: say how it went, then tidy the address. */
  signInResult() {
    const query = new URLSearchParams(window.location.search);
    if (!query.has('smartthings') && !query.has('smartthings_error')) return;
    if (query.get('smartthings') === 'connected') this.app.status.success('SmartThings connected. It renews itself from now on.');
    else this.app.status.error(`SmartThings: ${query.get('smartthings_error')}`);
    window.history.replaceState(null, '', `${window.location.pathname}${window.location.hash}`);
  }

  /** Send the person to SmartThings to sign in (saved ID and secret if left empty). */
  signIn(clientId = '', clientSecret = '') {
    return this.app.run(async () => {
      const redirect = `${window.location.origin}${SMARTTHINGS_CALLBACK}`;
      const { authorize_url: url } = await this.app.api.startSmartThingsSignIn(this.app.home.id, { client_id: clientId, client_secret: clientSecret, redirect_uri: redirect });
      window.location.assign(url);
    });
  }

  /** The SmartApp's details and "Sign in with SmartThings". */
  signInForm() {
    const redirect = `${window.location.origin}${SMARTTHINGS_CALLBACK}`;
    const id = el('input', { type: 'text', testid: 'smartthings-client-id', autocomplete: 'off', required: true, maxlength: '100', pattern: '[A-Za-z0-9-]+' });
    const secret = el('input', { type: 'password', testid: 'smartthings-client-secret', autocomplete: 'off', required: true, maxlength: '200', pattern: '[A-Za-z0-9-]+' });
    const form = el('form', { testid: 'smartthings-oauth' }, [
      el('p', { className: 'muted' }, [
        'Keeps itself connected. Once: make an OAuth-In SmartApp with the SmartThings CLI (',
        el('code', { text: 'smartthings apps:create' }),
        '), with the scopes r:devices:* and x:devices:* and this redirect URI:',
      ]),
      el('p', {}, [el('code', { testid: 'smartthings-redirect', text: redirect })]),
      redirect.startsWith('https://') ? null : el('p', { className: 'error', text: 'SmartThings only sends you back to an https:// address: open this page over HTTPS first.' }),
      el('div', { className: 'row' }, [field('Client ID', id), field('Client secret', secret)]),
      el('button', { type: 'submit', testid: 'smartthings-signin', text: 'Sign in with SmartThings' }),
    ]);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      this.signIn(id.value.trim(), secret.value.trim());
    });
    return form;
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
      this.box.replaceChildren(
        el('h3', { text: 'SmartThings (TV inputs by name)' }), intro, problem, this.signInForm(),
        el('h4', { text: 'Or a personal token (stops working after 24 hours)' }), form,
      );
      return;
    }
    if (info.problem) {  // a sign-in that lapsed: sign in again with the saved app
      this.box.replaceChildren(
        el('h3', { text: 'SmartThings (TV inputs by name)' }),
        el('p', { className: 'error', testid: 'smartthings-problem', text: info.problem }),
        el('button', { type: 'button', testid: 'smartthings-reconnect', text: 'Sign in with SmartThings again', onclick: () => this.signIn() }),
        this.disconnectButton(tvs),
      );
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
      el('p', { className: 'muted', testid: 'smartthings-method', text: info.method === 'oauth'
        ? 'Signed in: renews itself every 12 hours.'
        : 'With a personal token: it stops working after 24 hours. Disconnect and sign in with SmartThings to keep it connected.' }),
      rows.length ? el('div', { className: 'grid-fields' }, rows) : el('p', { className: 'muted', text: 'Add a TV above first.' }),
      this.disconnectButton(tvs),
    );
  }

  disconnectButton(tvs) {
    return el('button', {
      type: 'button', className: 'secondary', testid: 'smartthings-disconnect', text: 'Disconnect SmartThings',
      onclick: () => this.app.run(async () => {
        this.draw(await this.app.api.disconnectSmartThings(this.app.home.id), tvs);
        this.app.status.success('SmartThings disconnected.');
      }),
    });
  }
}

window.SmartThingsPanel = SmartThingsPanel;
