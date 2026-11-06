/**
 * Message of the day. After login everyone sees the admin's message once
 * per visit: "Close" hides it until the next login, "Don't show again"
 * dismisses it for good (a new message shows again). Admins set it in
 * Settings > Admin.
 */

let motdClosed = 0; // the version closed in this visit

function showMotd(app) {
  const motd = app.account && app.account.motd;
  if (!motd || motd.version <= motdClosed || document.querySelector('[data-testid="motd"]')) return;
  const overlay = el('div', { className: 'overlay' });
  const close = () => {
    motdClosed = motd.version;
    overlay.remove();
  };
  overlay.append(el('div', { className: 'remote info-panel', testid: 'motd', role: 'dialog', 'aria-label': 'Message' }, [
    el('div', { className: 'remote-head' }, [el('h2', { text: 'Message' })]),
    el('p', { className: 'motd-text', testid: 'motd-text', text: motd.text }),
    el('div', { className: 'row' }, [
      el('button', { type: 'button', testid: 'motd-close', text: 'Close', onclick: close }),
      el('button', {
        type: 'button', className: 'secondary', testid: 'motd-dismiss', text: "Don't show again",
        onclick: () => app.run(async () => {
          await app.api.dismissMotd(motd.version);
          app.account.motd = null;
          close();
        }),
      }),
    ]),
  ]));
  document.body.append(overlay);
  overlay.querySelector('[data-testid="motd-close"]').focus();
}

/** Settings > Admin > Message of the day. */
class MotdPanel {
  constructor(app) {
    this.app = app;
  }

  async render(container) {
    const current = await this.app.api.getMotd();
    const text = el('textarea', { testid: 'motd-input', rows: '4', maxlength: '2000', 'aria-label': 'Message of the day' });
    text.value = current.text || '';
    const save = (value) => this.app.run(async () => {
      const saved = await this.app.api.setMotd(value);
      text.value = saved.text || '';
      this.app.status.success(saved.text ? 'Message saved: everyone sees it at their next login.' : 'Message removed.');
    });
    container.append(el('div', { className: 'subpanel', testid: 'motd-settings' }, [
      el('h3', { text: 'Message of the day' }),
      el('p', { className: 'muted', text: 'Shown to everyone after they log in, until they choose "Don\'t show again". Changing it shows it again to everyone. Blank = none.' }),
      text,
      el('div', { className: 'row' }, [
        el('button', { type: 'button', testid: 'motd-save', text: 'Save message', onclick: () => save(text.value.trim() || null) }),
        el('button', { type: 'button', className: 'secondary', testid: 'motd-clear', text: 'Remove', onclick: () => save(null) }),
      ]),
    ]));
  }
}

window.showMotd = showMotd;
window.MotdPanel = MotdPanel;
