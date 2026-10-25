/**
 * Settings > Integrations > Frigate (owner): the server's address and,
 * for Frigate's login port, a username and password (checked with Frigate,
 * stored encrypted, the password never shown again).
 */

class FrigatePanel {
  constructor(app) {
    this.app = app;
  }

  async render(container) {
    const box = el('div', { className: 'subpanel', testid: 'frigate-server' });
    container.append(box);
    await this.fill(box);
  }

  async fill(box) {
    const server = await this.app.api.getFrigateServer(this.app.home.id);
    const url = el('input', { type: 'text', inputmode: 'url', autocomplete: 'off', testid: 'frigate-url', required: true, placeholder: 'https://192.168.1.20:8971', value: server.url || '' });
    const username = el('input', { type: 'text', testid: 'frigate-username', autocomplete: 'off', value: server.username || '' });
    const password = el('input', { type: 'password', testid: 'frigate-password', autocomplete: 'new-password' });
    const verify = el('input', { type: 'checkbox', testid: 'frigate-verify', checked: server.verify_tls });
    const form = el('form', { className: 'subpanel' }, [
      el('div', { className: 'grid-fields' }, [
        field('Frigate address', url), field('Username (blank for port 5000)', username), field('Password', password),
      ]),
      el('label', { className: 'check' }, [verify, el('span', { text: 'Check its HTTPS certificate (untick for Frigate\'s own self-signed certificate)' })]),
      el('button', { type: 'submit', testid: 'frigate-save', text: 'Save and test' }),
      formNote('frigate-note'),
    ]);
    const note = form.lastChild;
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      runWithNote(this.app, note, `Connecting to ${url.value.trim()}…`, async () => {
        const body = { url: url.value.trim(), verify_tls: verify.checked };
        if (username.value.trim()) {
          body.username = username.value.trim();
          body.password = password.value;
        }
        try {
          await this.app.api.saveFrigateServer(this.app.home.id, body);
        } finally {
          password.value = '';
        }
        await this.fill(box);
        this.app.status.success('Frigate connected.');
      });
    });
    box.replaceChildren(
      el('h3', { text: 'Frigate server' }),
      el('p', { className: 'muted', testid: 'frigate-configured', text: server.configured ? `Connected to ${server.url}${server.username ? ` as ${server.username}` : ''}` : 'Not set up yet.' }),
      form,
    );
    if (server.configured) {
      box.append(el('button', {
        type: 'button', className: 'danger', testid: 'frigate-forget', text: 'Remove',
        onclick: () => this.app.run(async () => {
          await this.app.api.removeFrigateServer(this.app.home.id);
          await this.fill(box);
          this.app.status.success('Frigate settings removed.');
        }),
      }));
    }
  }
}

window.FrigatePanel = FrigatePanel;
