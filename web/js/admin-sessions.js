/**
 * Admin > 2 Factor Login: everyone's logged-in devices (beside their
 * approved devices, trusted-devices.js), whose each one is, and Log out.
 */

class AdminSessionsList {
  constructor(app) {
    this.app = app;
    this.box = el('div', { className: 'sessions', testid: 'admin-sessions' });
  }

  async render(container) {
    container.append(this.box);
    await this.load();
  }

  async load() {
    const sessions = await this.app.api.getAllSessions();
    if (!sessions.length) {
      this.box.replaceChildren(el('p', { className: 'muted', text: 'Nobody is logged in.' }));
      return;
    }
    this.box.replaceChildren(...sessions.map((s) => this.row(s)));
  }

  row(s) {
    const who = s.user_name || s.user;
    const where = s.current ? 'This device' : (s.ip_address || 'Unknown address');
    const row = el('div', { className: 'session-row', testid: 'admin-session', 'data-current': String(s.current) }, [
      el('div', {}, [
        el('strong', { text: `${who} · ${where}` }),
        el('p', { className: 'muted', text: `Last active ${formatTime(s.last_activity)} · since ${formatTime(s.created_at)}` }),
      ]),
    ]);
    if (!s.current) {
      row.append(el('button', {
        type: 'button', className: 'secondary', testid: 'admin-session-end', text: 'Log out',
        onclick: () => this.app.run(async () => {
          await this.app.api.endAnySession(s.id);
          await this.load();
          this.app.status.success(`${who} was logged out there.`);
        }),
      }));
    }
    return row;
  }
}

window.AdminSessionsList = AdminSessionsList;
