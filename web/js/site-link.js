/**
 * Admin > Home > Another site: link this home with a server at another
 * location (app/federation.py). Either way round:
 *  - on the main server: this home's devices are at another site; a pairing
 *    code for that site's server to use;
 *  - on a site's own server: link this home to the main server (its address
 *    and a pairing code from it); this server then connects to it.
 */

class SiteLinkPanel {
  constructor(app) {
    this.app = app;
    this.box = el('div', { className: 'subsection', testid: 'site-link' });
  }

  render() {
    this.load().catch((error) => this.app.handleError(error));
    return this.box;
  }

  async load() {
    const homeId = this.app.home.id;
    const [site, main] = await Promise.all([this.app.api.getSite(homeId), this.app.api.getMainServer(homeId)]);
    this.draw(site, main);
  }

  draw(site, main, code = null) {
    const parts = [el('h4', { text: 'Another site' })];
    if (main.linked) {
      parts.push(
        el('p', { testid: 'site-link-state', text: `This home is linked to the main server at ${main.main_url}${main.main_home_name ? ` (${main.main_home_name})` : ''}: ${main.connected ? 'connected' : 'not connected right now'}.` }),
        el('p', { className: 'muted', text: 'People use this home through the main server. Its devices and integrations stay here.' }),
        this.button('main-server-unlink', 'Unlink from the main server', () => this.app.api.unlinkMainServer(this.app.home.id), 'Unlinked from the main server.'),
      );
    } else if (site.linked) {
      parts.push(
        el('p', { testid: 'site-link-state', text: `This home's devices are at ${site.site_name || 'another site'}: ${site.connected ? 'its server is connected' : 'its server is not connected right now'}.` }),
        this.button('site-unlink', 'Unlink the other site', () => this.app.api.unlinkSite(this.app.home.id), 'The other site is unlinked: this home\'s devices are on this server again.'),
      );
    } else {
      parts.push(
        el('p', { className: 'muted', text: 'For a home at another location with a server of its own: link the two servers, then use that home from here.' }),
        el('div', { className: 'row' }, [
          el('button', { type: 'button', className: 'secondary', testid: 'site-pairing', text: 'Its devices are at another site', onclick: () => this.app.run(async () => {
            const made = await this.app.api.startSitePairing(this.app.home.id);
            this.draw(made, main, made);
          }) }),
        ]),
        code ? this.pairingNote(code) : null,
        el('h4', { text: 'Or: this server is at another site' }),
        this.linkForm(site),
      );
    }
    this.box.replaceChildren(...parts.filter(Boolean));
  }

  pairingNote(made) {
    return el('div', { className: 'note', testid: 'site-pairing-note' }, [
      el('p', {}, [
        'On the other site\'s server: Admin › Home › Another site › "this server is at another site", enter ',
        el('code', { testid: 'site-main-address', text: window.location.origin }),
        ' and this code within ', String(made.minutes), ' minutes:',
      ]),
      el('p', {}, [el('strong', { className: 'pairing-code', testid: 'site-pairing-code', text: made.code })]),
    ]);
  }

  linkForm(site) {
    const url = el('input', { type: 'url', testid: 'main-server-url', placeholder: 'https://main.example.com', required: true, maxlength: '300' });
    const code = el('input', { type: 'text', testid: 'main-server-code', placeholder: 'ABCD-EF12-3456', required: true, maxlength: '20', autocomplete: 'off' });
    const form = el('form', { testid: 'main-server-form' }, [
      el('div', { className: 'row' }, [field('Main server address', url), field('Pairing code', code)]),
      el('button', { type: 'submit', testid: 'main-server-link', text: 'Link to the main server' }),
    ]);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      this.app.run(async () => {
        const main = await this.app.api.linkMainServer(this.app.home.id, url.value.trim(), code.value.trim());
        this.draw(site, main);
        this.app.status.success('Linked: this server connects to the main server within half a minute.');
      });
    });
    return form;
  }

  button(testid, text, action, done) {
    return el('button', { type: 'button', className: 'secondary', testid, text, onclick: () => this.app.run(async () => {
      await action();
      await this.load();
      this.app.status.success(done);
    }) });
  }
}

window.SiteLinkPanel = SiteLinkPanel;
