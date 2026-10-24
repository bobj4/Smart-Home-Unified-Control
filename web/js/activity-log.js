/** Settings > Activity log (admins): the newest events first. */

class ActivityLog {
  constructor(app) {
    this.app = app;
  }

  async render(container) {
    const list = el('ul', { className: 'activity' });
    const refresh = el('button', {
      type: 'button', className: 'secondary', testid: 'activity-refresh', text: 'Refresh',
      onclick: () => this.app.run(() => this.fillActivity(list)),
    });
    container.append(el('div', { className: 'actions' }, [refresh]), list);
    await this.fillActivity(list);
  }

  async fillActivity(list) {
    const events = await this.app.api.getActivity(this.app.home.id, 50);
    list.replaceChildren(...events.map((e) => el('li', { testid: 'activity-row' }, [
      el('span', { className: 'event', text: e.event_type }),
      el('span', { text: e.user_email || 'system' }),
      el('span', { className: 'muted', text: [formatTime(e.created_at), e.ip_address].filter(Boolean).join(' · ') }),
    ])));
    if (events.length === 0) list.append(el('li', { className: 'muted', text: 'Nothing yet.' }));
  }
}

window.ActivityLog = ActivityLog;
