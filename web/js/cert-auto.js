/**
 * Settings > Admin > HTTPS: take the certificate the server's web server
 * (Apache, nginx, Caddy or certbot) uses. Switching it on (or "Fetch now")
 * asks the server to import at once; a popup waits for its answer.
 */

const CERT_RESULT_TEXT = {
  changed: 'Imported. The app is restarting to use it: reload this page in a minute.',
  same: 'Done: the app already has this certificate.',
  off: 'Automatic import is off.',
  not_found: 'No web server certificate was found on the server.',
  refused: 'The app refused the certificate.',
  unknown: 'The server answered, but not in a way the app understands.',
};

const CERT_NO_ANSWER = 'The server has not answered. On the server, run once: deploy/linux/smarthome update (it sets up the import), then press Try again. Or import by hand: deploy/linux/smarthome cert-import';

class CertImportPopup {
  constructor(app) {
    this.app = app;
    this.overlay = el('div', { className: 'overlay', testid: 'cert-popup-overlay', hidden: true });
    document.body.append(this.overlay);
  }

  /** Wait for the server's answer to a request just made. Anything but
   * success offers "Try again", which asks the server once more. */
  async wait(started, onDone) {
    this.closed = false;
    const round = (this.round || 0) + 1;
    this.round = round;
    const text = el('p', { testid: 'cert-popup-text', role: 'status', text: 'Asking the server to fetch the certificate…' });
    const retry = el('button', {
      type: 'button', testid: 'cert-popup-retry', text: 'Try again', hidden: true,
      onclick: () => this.app.run(async () => this.wait(await this.app.api.requestHttpsImport(), onDone)),
    });
    const close = el('button', { type: 'button', className: 'secondary', testid: 'cert-popup-close', text: 'Close', onclick: () => this.close() });
    this.overlay.replaceChildren(el('div', { className: 'remote', testid: 'cert-popup', role: 'dialog', 'aria-label': 'Web server certificate' }, [
      el('h2', { text: 'Web server certificate' }), text, el('div', { className: 'row' }, [retry, close]),
    ]));
    this.overlay.hidden = false;
    const failed = (message) => { text.textContent = message; retry.hidden = false; };
    if (!started.pending) {
      failed('The app could not leave the request for the server. Import on the server instead: deploy/linux/smarthome cert-import');
      return;
    }
    const deadline = Date.now() + (this.app.certWaitMs || 45000);
    // A newer try (or Close) ends this one's waiting.
    while (!this.closed && this.round === round && Date.now() < deadline) {
      await new Promise((resolve) => { setTimeout(resolve, this.app.certPollMs || 2000); });
      let auto;
      try {
        auto = await this.app.api.getHttpsAutoImport();
      } catch (error) {
        continue; // the app restarts after an import
      }
      if (auto.last_check && !auto.pending) {
        const { status, message } = auto.last_check;
        text.textContent = status === 'changed' || status === 'same' || !message
          ? CERT_RESULT_TEXT[status] || CERT_RESULT_TEXT.unknown
          : `${CERT_RESULT_TEXT[status] || ''} ${message}`.trim();
        text.dataset.result = status;
        retry.hidden = status === 'changed' || status === 'same';
        onDone(auto);
        return;
      }
    }
    if (!this.closed && this.round === round) failed(CERT_NO_ANSWER);
  }

  close() {
    this.closed = true;
    this.overlay.hidden = true;
    this.overlay.replaceChildren();
  }
}

/** The setting's row: the switch, what was imported, and "Fetch now". */
function certAutoImportRow(app) {
  const box = el('div', { testid: 'https-auto' });
  app.certPopup = app.certPopup || new CertImportPopup(app);
  const ask = (started) => { app.certPopup.wait(started, draw); draw(started); };
  function draw(auto) {
    const toggle = switchInput('https-auto-import', Boolean(auto.on), "Take the certificate from this server's web server");
    toggle.addEventListener('change', () => app.run(async () => {
      let saved;
      try {
        saved = await app.api.setHttpsAutoImport(toggle.checked);
      } catch (error) {
        toggle.checked = !toggle.checked;
        throw error;
      }
      if (saved.on) ask(saved);
      else {
        draw(saved);
        app.status.success('Off. The certificate stays as it is.');
      }
    }));
    const status = auto.imported_at
      ? `Imported from ${auto.source || 'the web server'} on ${new Date(auto.imported_at).toLocaleString()}. Checked again every 6 hours and after each renewal.`
      : 'Not imported yet.';
    box.replaceChildren(
      settingRow("Use the web server's certificate", 'For a server running Apache (httpd), nginx, Caddy or certbot: the app takes the same certificate and picks up renewals by itself.', toggle),
      auto.on ? el('div', { className: 'row' }, [
        el('p', { className: 'muted', testid: 'https-auto-status', text: status }),
        el('button', {
          type: 'button', className: 'secondary', testid: 'https-auto-fetch', text: 'Fetch now',
          onclick: () => app.run(async () => ask(await app.api.requestHttpsImport())),
        }),
      ]) : '',
    );
  }
  app.api.getHttpsAutoImport().then(draw).catch((error) => app.handleError(error));
  return box;
}

window.certAutoImportRow = certAutoImportRow;
