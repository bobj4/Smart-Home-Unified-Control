/**
 * Schedules and Scenes (the tab after Thermostats): schedules this server
 * runs at a time, or at sunrise or sunset, then scenes to run with one
 * press. Devices' own schedules (thermostats, water heaters) stay on
 * their own cards. Guests allowed to run scenes see only the scenes.
 */

function whenText(s) {
  const days = s.days.length === 7 ? 'Every day'
    : s.days.join() === '0,1,2,3,4' ? 'Weekdays'
      : s.days.join() === '5,6' ? 'Weekends'
        : s.days.map((d) => AUTOMATION_DAYS[d]).join(', ');
  const t = s.trigger;
  if (t.kind === 'time') {
    const [h, m] = t.at.split(':').map(Number);
    return `${days} at ${new Date(2000, 0, 1, h, m).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`;
  }
  const sunName = t.kind === 'sunrise' ? 'sunrise' : 'sunset';
  if (!t.offset) return `${days} at ${sunName}`;
  return `${days}, ${Math.abs(t.offset)} min ${t.offset < 0 ? 'before' : 'after'} ${sunName}`;
}

function nextText(s) {
  if (!s.enabled) return 'Off';
  if (s.paused) return 'Paused';
  if (!s.next_run_at) return `Waiting: ${s.waiting || 'no run planned'}`;
  const when = new Date(s.next_run_at);
  return `Next: ${when.toLocaleString([], { weekday: 'short', hour: 'numeric', minute: '2-digit' })}`;
}

class SchedulesView {
  constructor(app, root) {
    this.app = app;
    this.root = root;
    this.editor = new AutomationEditor(this);
  }

  async load() {
    const home = this.app.home.id;
    if (this.app.isGuest()) {
      const scenes = await this.app.api.getGuestScenes(home);
      this.root.replaceChildren(this.scenesPanel(scenes, false));
      return;
    }
    const [data, devices, groups, hueScenes] = await Promise.all([
      this.app.api.getAutomation(home),
      this.app.api.getDevices(home),
      this.app.api.getGroups(home),
      this.app.api.getHueScenes(home).catch(() => []), // Hue off or not paired: none
    ]);
    Object.assign(this, { data, devices, groups, hueScenes });
    this.root.replaceChildren(
      el('p', { className: 'muted', text: 'Run here, by this server. Thermostat and water heater schedules stay on their own cards.' }),
      data.settings.paused ? el('p', { className: 'notice', testid: 'schedules-paused', text: 'All schedules are paused (Settings > Admin > Schedules and Scenes).' }) : '',
      this.schedulesPanel(data.schedules, data.can_edit),
      this.scenesPanel(data.scenes, data.can_edit),
    );
  }

  act(work, done) {
    return this.app.run(async () => {
      const result = await work();
      const failed = result && (Array.isArray(result.failed) ? result.failed.length : result.failed);
      if (done) this.app.status[failed ? 'error' : 'success'](done(result));
      await this.load();
    });
  }

  /** The run's outcome: failed is a list (or, for guests, a count). */
  ranText(name, result) {
    const count = Array.isArray(result.failed) ? result.failed.length : Number(result.failed || 0);
    if (!count) return `${name} ran (${result.done} done).`;
    const first = Array.isArray(result.failed) ? result.failed[0] : null;
    return first ? `${name}: ${result.done} done; ${first.name}: ${first.reason}` : `${name}: ${result.done} done, ${count} failed.`;
  }

  resetText(name, result) {
    const count = Array.isArray(result.failed) ? result.failed.length : Number(result.failed || 0);
    if (!count) return `${name}: put back as before (${result.done} ${result.done === 1 ? 'change' : 'changes'}).`;
    const first = Array.isArray(result.failed) ? result.failed[0] : null;
    return first ? `${name}: ${result.done} put back; ${first.name}: ${first.reason}. Reset again to retry.` : `${name}: ${result.done} put back, ${count} failed. Reset again to retry.`;
  }

  scenesPanel(scenes, canEdit) {
    const home = this.app.home.id;
    const cards = scenes.map((s) => el('div', { className: 'device-card scene-card', testid: 'scene-card', 'data-scene-id': s.id }, [
      el('h3', { text: s.name }),
      s.steps ? el('p', { className: 'muted', text: `${s.steps.length} ${s.steps.length === 1 ? 'step' : 'steps'}` }) : '',
      el('div', { className: 'row' }, [
        el('button', { type: 'button', testid: 'scene-run', text: 'Run', onclick: () => this.act(() => this.app.api.runScene(home, s.id), (r) => this.ranText(s.name, r)) }),
        // Reset: put back what its last run changed (until it is used).
        s.can_reset ? el('button', { type: 'button', className: 'secondary', testid: 'scene-reset', text: 'Reset', title: 'Put back what this scene changed', onclick: () => this.act(() => this.app.api.resetScene(home, s.id), (r) => this.resetText(s.name, r)) }) : '',
      ]),
      canEdit ? el('div', { className: 'row' }, [
        el('button', { type: 'button', className: 'secondary', testid: 'scene-edit', text: 'Change', onclick: () => this.editor.scene(s) }),
        el('button', { type: 'button', className: 'ghost', testid: 'scene-delete', text: 'Delete', onclick: () => this.confirmDelete(s.name, () => this.app.api.deleteScene(home, s.id)) }),
      ]) : '',
    ]));
    return el('section', { className: 'room', testid: 'scenes' }, [
      el('h2', { text: 'Scenes' }),
      cards.length ? el('div', { className: 'device-grid' }, cards) : el('p', { className: 'muted', testid: 'scenes-empty', text: 'No scenes yet.' }),
      canEdit ? el('button', { type: 'button', className: 'secondary', testid: 'scene-new', text: 'New scene', onclick: () => this.editor.scene(null) }) : '',
    ]);
  }

  schedulesPanel(schedules, canEdit) {
    const home = this.app.home.id;
    const rows = schedules.map((s) => {
      const toggle = el('input', { type: 'checkbox', className: 'switch', testid: 'schedule-toggle', checked: s.enabled, disabled: !canEdit, 'aria-label': `${s.name} on` });
      toggle.addEventListener('change', () => this.act(() => this.app.api.saveSchedule(home, s.id, { ...pick(s), enabled: toggle.checked })));
      return el('div', { className: 'device-card schedule-row', testid: 'schedule-row', 'data-schedule-id': s.id }, [
        el('div', { className: 'card-head' }, [el('h3', { text: s.name }), toggle]),
        el('p', { testid: 'schedule-when', text: whenText(s) }),
        el('p', { className: 'muted', testid: 'schedule-next', text: nextText(s) }),
        s.last_result ? el('p', { className: 'muted', testid: 'schedule-last', text: `Last: ${s.last_result}` }) : '',
        canEdit ? el('div', { className: 'row' }, [
          el('button', { type: 'button', className: 'secondary', testid: 'schedule-edit', text: 'Change', onclick: () => this.editor.schedule(s) }),
          el('button', { type: 'button', className: 'secondary', testid: 'schedule-run', text: 'Run now', onclick: () => this.act(() => this.app.api.runSchedule(home, s.id), (r) => this.ranText(s.name, r)) }),
          el('button', { type: 'button', className: 'ghost', testid: 'schedule-delete', text: 'Delete', onclick: () => this.confirmDelete(s.name, () => this.app.api.deleteSchedule(home, s.id)) }),
        ]) : '',
      ]);
    });
    return el('section', { className: 'room', testid: 'schedules' }, [
      el('h2', { text: 'Schedules' }),
      rows.length ? el('div', { className: 'device-grid' }, rows) : el('p', { className: 'muted', testid: 'schedules-empty', text: 'No schedules yet.' }),
      canEdit ? el('button', { type: 'button', className: 'secondary', testid: 'schedule-new', text: 'New schedule', onclick: () => this.editor.schedule(null) }) : '',
    ]);
  }

  /** Delete after a second press within 4 seconds. */
  confirmDelete(name, remove) {
    const button = document.activeElement;
    if (button && button.dataset.confirm !== 'yes') {
      button.dataset.confirm = 'yes';
      button.textContent = 'Press again to delete';
      setTimeout(() => { if (button.isConnected) { button.dataset.confirm = ''; button.textContent = 'Delete'; } }, 4000);
      return;
    }
    this.act(remove, () => `${name} deleted.`);
  }
}

/** A schedule as the server takes it back. */
function pick(s) {
  return { name: s.name, enabled: s.enabled, trigger: s.trigger, days: s.days, scene_id: s.scene_id, steps: s.steps };
}

window.SchedulesView = SchedulesView;
