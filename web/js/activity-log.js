/**
 * Settings > Activity log (admins): the newest events first, and the
 * verbose logging switch (off by default): while on, integration detail is
 * recorded too (events starting "verbose_", shown with their details).
 */

/** "path: /api/v1/… · status: 200 · ms: 41" for a verbose event. */
function eventDetails(details) {
  return Object.entries(details || {})
    .filter(([, value]) => value !== null && value !== undefined && value !== '')
    .map(([key, value]) => `${key}: ${typeof value === 'object' ? JSON.stringify(value) : value}`)
    .join(' · ');
}

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
    const { enabled } = await this.app.api.getVerbose();
    const toggle = el('input', {
      type: 'checkbox', role: 'switch', className: 'switch', testid: 'verbose-toggle', checked: enabled, 'aria-label': 'Verbose logging',
    });
    toggle.addEventListener('change', () => this.app.run(async () => {
      try {
        const saved = await this.app.api.setVerbose(toggle.checked);
        this.app.status.success(`Verbose logging turned ${saved.enabled ? 'on' : 'off'}.`);
        await this.fillActivity(list);
      } catch (error) {
        toggle.checked = !toggle.checked;
        throw error;
      }
    }));
    const verbose = el('div', { className: 'integration-row', testid: 'verbose-row' }, [
      el('div', {}, [
        el('strong', { text: 'Verbose logging' }),
        el('p', { className: 'muted', text: 'Also record integration detail: each change request and its result, commands sent to Cync, Rheem and Samsung, background reads, and devices going offline or back online. For every home; turn it off when done, as it adds many rows.' }),
      ]),
      toggle,
    ]);
    container.append(verbose, el('div', { className: 'actions' }, [refresh]), list);
    await this.fillActivity(list);
  }

  async fillActivity(list) {
    const events = await this.app.api.getActivity(this.app.home.id, 50);
    list.replaceChildren(...events.map((e) => {
      const isVerbose = e.event_type.startsWith('verbose_');
      const row = el('li', { testid: 'activity-row', className: isVerbose ? 'verbose' : '' }, [
        el('span', { className: 'event', text: e.event_type }),
        el('span', { text: e.user_email || 'system' }),
        el('span', { className: 'muted', text: [formatTime(e.created_at), e.ip_address].filter(Boolean).join(' · ') }),
      ]);
      if (isVerbose) row.append(el('span', { className: 'muted activity-details', testid: 'activity-details', text: eventDetails(e.details) }));
      return row;
    }));
    if (events.length === 0) list.append(el('li', { className: 'muted', text: 'Nothing yet.' }));
  }
}

window.ActivityLog = ActivityLog;
