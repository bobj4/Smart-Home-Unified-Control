/**
 * After HTTPS is switched on or off (Settings > Admin > HTTPS): a popup
 * offering "Restart now" (the app stops and Docker starts it again with
 * the new setting) or "Restart later". It does not cover the page.
 */

class HttpsRestartPopup {
  constructor(app) {
    this.app = app;
    this.box = el('div', { className: 'remote restart-popup', testid: 'restart-popup', role: 'dialog', 'aria-label': 'Restart to apply', hidden: true });
    document.body.append(this.box);
  }

  async open(https) {
    let available = false;
    try {
      available = (await this.app.api.get('/admin/https/restart')).available;
    } catch (error) {
      available = false;
    }
    const what = https.enabled ? 'HTTPS is on' : 'HTTPS is off';
    const text = el('p', { testid: 'restart-popup-text', text: available
      ? `${what} from the next restart. Restart now? Everyone is disconnected for a few seconds.`
      : `${what} from the next restart. On the server, run: deploy/linux/smarthome restart` });
    const now = el('button', { type: 'button', testid: 'restart-now', text: 'Restart now', hidden: !available, onclick: () => this.restart(https, text, now, later) });
    const later = el('button', { type: 'button', className: 'secondary', testid: 'restart-later', text: 'Restart later', onclick: () => this.close() });
    this.box.replaceChildren(el('h2', { text: 'Restart to apply' }), text, el('div', { className: 'row' }, [now, later]));
    this.box.hidden = false;
    (available ? now : later).focus();
  }

  restart(https, text, now, later) {
    this.app.run(async () => {
      await this.app.api.post('/admin/https/restart', {});
      now.hidden = true;
      later.hidden = true;
      const scheme = https.enabled ? 'https:' : 'http:';
      if (window.location.protocol !== scheme) {
        // The address changes (http <-> https): go there once it is back.
        const target = `${scheme}//${window.location.host}${window.location.pathname}#/settings/admin`;
        text.replaceChildren('Restarting… this page moves to ', el('a', { className: 'link', href: target, testid: 'restart-target', text: target }), ' in a few seconds.');
        setTimeout(() => window.location.assign(target), this.app.restartMoveMs || 10000);
        return;
      }
      text.textContent = 'Restarting… the page reloads when the app is back.';
      await this.waitAndReload();
    });
  }

  /** Wait until the app answers again (after it has gone), then reload. */
  async waitAndReload() {
    const pause = (ms) => new Promise((resolve) => { setTimeout(resolve, ms); });
    await pause(this.app.restartPauseMs || 3000);
    for (let i = 0; i < 60; i += 1) {
      try {
        const r = await fetch('/health', { cache: 'no-store' });
        if (r.ok) break;
      } catch (error) {
        // still restarting
      }
      await pause(1000);
    }
    window.location.reload();
  }

  close() {
    this.box.hidden = true;
    this.box.replaceChildren();
  }
}

function httpsRestartPopup(app) {
  if (!app.httpsRestart) app.httpsRestart = new HttpsRestartPopup(app);
  return app.httpsRestart;
}

window.httpsRestartPopup = httpsRestartPopup;
