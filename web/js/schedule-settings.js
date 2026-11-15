/**
 * Settings > Admin > Schedules and Scenes: the home's time zone, its
 * location (for sunrise and sunset), who may make and change scenes and
 * schedules, and a switch pausing every schedule (going away, say).
 */

function sunClockText(iso) {
  return iso ? new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', timeZone: undefined }) : 'none today';
}

class ScheduleSettingsPanel {
  constructor(app) {
    this.app = app;
  }

  async render(container) {
    const data = await this.app.api.getAutomation(this.app.home.id).catch(() => null);
    if (!data) return; // at another site with its server not connected
    const s = data.settings;
    const browserZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const zones = typeof Intl.supportedValuesOf === 'function' ? Intl.supportedValuesOf('timeZone') : [];
    const names = [...new Set(['UTC', s.time_zone, browserZone, ...zones])].filter(Boolean);
    const zone = el('select', { testid: 'schedule-zone' }, names.map((z) => el('option', { value: z, text: z })));
    zone.value = s.time_zone === 'UTC' && browserZone ? browserZone : s.time_zone;
    const place = el('input', {
      type: 'text', testid: 'schedule-location', placeholder: 'e.g. 40.7128, -74.0060',
      value: s.latitude === null ? '' : `${s.latitude}, ${s.longitude}`, 'aria-label': 'Latitude, longitude',
    });
    const editors = stepChoice([['admin', 'Admins'], ['operator', 'Operators and admins'], ['member', 'Everyone (not guests)']], s.editors, 'schedule-editors');
    const paused = switchInput('schedule-paused', s.paused, 'Pause every schedule');
    const sun = s.sun_today
      ? el('p', { className: 'muted', testid: 'schedule-sun-today', text: `Today there: sunrise ${sunClockText(s.sun_today.sunrise)}, sunset ${sunClockText(s.sun_today.sunset)} (your device's time).` })
      : el('p', { className: 'muted', text: 'Set the location for sunrise and sunset schedules. In a map app, press and hold (or right-click) your home to copy its latitude and longitude.' });
    const note = formNote('schedule-settings-note');
    const form = el('form', { className: 'subpanel', testid: 'schedule-settings' }, [
      el('h3', { text: 'Schedules and Scenes' }),
      el('p', { className: 'muted', text: 'Schedules this server runs (the Schedules and Scenes tab), in this home\'s time zone.' }),
      el('div', { className: 'row' }, [field('Time zone', zone), field('Location (latitude, longitude)', place)]),
      sun,
      field('Who may make and change scenes and schedules', editors),
      settingRow('Pause every schedule', 'Going away, say. Scenes still run when pressed.', paused),
      note,
      el('button', { type: 'submit', testid: 'schedule-settings-save', text: 'Save' }),
    ]);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      const parts = place.value.split(/[,\s]+/).filter(Boolean).map(Number);
      if (place.value.trim() && (parts.length !== 2 || parts.some(Number.isNaN))) {
        note.dataset.kind = 'error';
        note.textContent = 'Write the location as latitude, longitude (e.g. 40.7128, -74.0060).';
        return;
      }
      const [latitude = null, longitude = null] = place.value.trim() ? parts : [];
      this.app.run(async () => {
        await this.app.api.setAutomationSettings(this.app.home.id, { time_zone: zone.value, latitude, longitude, editors: editors.value, paused: paused.checked });
        this.app.status.success('Schedule settings saved.');
        const fresh = el('div');
        await this.render(fresh);
        form.replaceWith(...fresh.childNodes);
      });
    });
    container.append(form);
  }
}

window.ScheduleSettingsPanel = ScheduleSettingsPanel;
