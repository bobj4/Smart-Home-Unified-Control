/**
 * Settings > Integrations > Google Nest: the Device Access project and
 * Google Cloud OAuth client (admins), signing in with Google (its page
 * opens in a new tab; paste back the address it lands on), and finding the
 * devices. Like SmartThings, Google charges for API access: a one-time,
 * non-refundable US$5 Device Access registration. See docs/NEST.md.
 *
 * Also the card line of a Nest camera or doorbell (what it last saw).
 */

const NEST_SEEN = { person: 'Person', motion: 'Motion', sound: 'Sound', doorbell: 'Doorbell rang' };

/** "Person · 3:42 PM" on a Nest camera or doorbell card. */
function cameraSeen(state) {
  const last = state.last_event;
  if (!last) return el('p', { className: 'muted', testid: 'camera-seen', text: 'Nothing seen yet' });
  const when = new Date(last.at);
  const today = when.toDateString() === new Date().toDateString();
  const time = when.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
  const day = today ? '' : `${when.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}, `;
  return el('p', { className: 'muted', testid: 'camera-seen', text: `${NEST_SEEN[last.kind] || last.kind} · ${day}${time}` });
}

class NestPanel {
  constructor(app) {
    this.app = app;
  }

  async render(container) {
    this.box = el('div', { className: 'subpanel', testid: 'nest' });
    container.append(this.box);
    await this.load();
  }

  async load() {
    let info;
    try {
      info = await this.app.api.getNest(this.app.home.id);
    } catch (error) {
      info = { configured: false, connected: false, problem: error.message };
    }
    this.draw(info);
  }

  draw(info) {
    const admin = this.app.can('admin');
    this.box.replaceChildren(
      el('h3', { text: 'Google Nest' }),
      el('p', { className: 'warning', testid: 'nest-paid', text: 'Google charges for this: Nest devices can only be reached through Google\'s Device Access, which needs a one-time, non-refundable US$5 registration (a personal Google account, not Workspace). Without it, Nest cannot be connected.' }),
      info.problem ? el('p', { className: 'error', testid: 'nest-problem', text: info.problem }) : '',
      el('p', { className: 'muted', testid: 'nest-state', text: info.connected ? `Signed in (Device Access project ${info.project_id}).${info.subscription ? ' Camera and doorbell events: on.' : ' Camera and doorbell events: off (no Pub/Sub subscription).'}` : 'Not signed in yet.' }),
      info.connected && this.app.can('operator') ? el('button', { type: 'button', className: 'secondary', testid: 'nest-sync', text: 'Find devices', onclick: () => this.sync() }) : '',
      admin ? this.setupForm(info) : '',
      admin && info.configured ? this.finishForm() : '',
      admin && info.configured ? el('button', { type: 'button', className: 'ghost', testid: 'nest-disconnect', text: 'Disconnect', onclick: () => this.disconnect() }) : '',
    );
  }

  sync() {
    return this.app.run(async () => {
      const found = await this.app.api.syncNest(this.app.home.id);
      this.app.status.success(`Google Nest: ${found.created} new, ${found.updated} updated.`);
    });
  }

  disconnect() {
    return this.app.run(async () => {
      await this.app.api.disconnectNest(this.app.home.id);
      this.app.status.success('Google Nest disconnected (its devices stay until removed).');
      await this.load();
    });
  }

  /** The project, the OAuth client and the events subscription; then Google's page. */
  setupForm(info) {
    const input = (testid, value, attrs = {}) => el('input', { type: 'text', testid, value: value || '', autocomplete: 'off', ...attrs });
    const project = input('nest-project', info.project_id, { required: true, maxlength: '64', pattern: '[A-Za-z0-9\\-]+' });
    const client = input('nest-client-id', info.client_id, { required: true, maxlength: '200' });
    const secret = el('input', { type: 'password', testid: 'nest-client-secret', autocomplete: 'off', maxlength: '200', required: !info.configured, placeholder: info.configured ? 'Kept: leave empty' : '' });
    const subscription = input('nest-subscription', info.subscription, { maxlength: '300', placeholder: 'projects/my-cloud-project/subscriptions/nest-events' });
    const link = (href, text) => el('a', { href, target: '_blank', rel: 'noopener noreferrer', text });
    const form = el('form', { testid: 'nest-setup' }, [
      el('details', { className: 'muted' }, [
        el('summary', { text: 'How to set it up (about 15 minutes)' }),
        el('ol', { className: 'steps' }, [
          el('li', {}, ['Register at ', link('https://console.nest.google.com/device-access', 'console.nest.google.com/device-access'), ' (the US$5 fee).']),
          el('li', {}, ['In ', link('https://console.cloud.google.com/apis/credentials', 'Google Cloud > Credentials'), ', make an OAuth client ID: Web application, authorized redirect URI https://www.google.com. Enable the Smart Device Management API. On the OAuth consent screen, publish the app (In production), or the sign-in stops after 7 days.']),
          el('li', { text: 'Back in Device Access, create a project with that client ID; copy its Project ID.' }),
          el('li', { text: 'Optional, for camera and doorbell alerts: in the same Google Cloud project, make a Pub/Sub topic, give sdm-publisher@googlegroups.com the Pub/Sub Publisher role on it, enter it in the Device Access project, and make a pull subscription on it. Its full name goes below.' }),
          el('li', { text: 'Press Sign in with Google, choose the home and devices to share, then paste the address Google lands on (https://www.google.com/?code=...) below.' }),
        ]),
      ]),
      field('Device Access project ID', project),
      field('OAuth client ID', client),
      field('OAuth client secret', secret),
      field('Pub/Sub subscription (optional, for camera and doorbell events)', subscription),
      el('button', { type: 'submit', testid: 'nest-sign-in', text: info.connected ? 'Sign in with Google again' : 'Sign in with Google' }),
    ]);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      // The tab opens now, while the press still counts as the person's.
      const tab = window.open('', '_blank');
      this.app.run(async () => {
        try {
          const result = await this.app.api.startNest(this.app.home.id, {
            project_id: project.value.trim(), client_id: client.value.trim(),
            client_secret: secret.value.trim(), subscription: subscription.value.trim(),
          });
          if (tab) tab.location.href = result.authorize_url;
          else window.open(result.authorize_url, '_blank', 'noopener');
          this.app.status.success('Sign in on Google\'s page, then paste the address it lands on here.');
          this.draw(result);
        } catch (error) {
          if (tab) tab.close();
          throw error;
        }
      });
    });
    return form;
  }

  finishForm() {
    const address = el('input', { type: 'url', testid: 'nest-address', required: true, autocomplete: 'off', placeholder: 'https://www.google.com/?code=...' });
    const form = el('form', { testid: 'nest-finish' }, [
      field('Address Google sent you to', address),
      el('button', { type: 'submit', testid: 'nest-finish-submit', text: 'Finish signing in' }),
    ]);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      this.app.run(async () => {
        const result = await this.app.api.finishNest(this.app.home.id, address.value.trim());
        this.app.status.success(`Google Nest signed in: ${result.created} new, ${result.updated} updated.`);
        this.draw(result);
      });
    });
    return form;
  }
}
