/**
 * Schedules and Scenes: the window for making or changing a scene or a
 * schedule. A schedule runs at a time, or at sunrise or sunset (minutes
 * before or after), on the days picked, a scene and/or its own steps.
 */

const AUTOMATION_DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

class AutomationEditor {
  constructor(view) {
    this.view = view;
    this.app = view.app;
    this.overlay = el('div', { className: 'overlay', testid: 'automation-editor-overlay', hidden: true });
    this.overlay.addEventListener('click', (e) => { if (e.target === this.overlay) this.close(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !this.overlay.hidden) this.close(); });
    document.body.append(this.overlay);
  }

  close() {
    this.overlay.hidden = true;
    this.overlay.replaceChildren();
  }

  open(title, testid, body, save) {
    const note = formNote(`${testid}-error`);
    const form = el('form', { className: 'remote info-panel automation-editor', testid, role: 'dialog', 'aria-label': title }, [
      el('div', { className: 'remote-head' }, [
        el('h2', { text: title }),
        el('button', { type: 'button', className: 'ghost', testid: `${testid}-close`, text: '✕', 'aria-label': 'Close', onclick: () => this.close() }),
      ]),
      ...body,
      note,
      el('button', { type: 'submit', testid: `${testid}-save`, text: 'Save' }),
    ]);
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      note.textContent = '';
      try {
        await save();
        this.close();
        await this.view.load();
      } catch (error) {
        note.dataset.kind = 'error';
        note.textContent = error.message;
      }
    });
    this.overlay.replaceChildren(form);
    this.overlay.hidden = false;
    form.querySelector('input, select').focus();
  }

  scene(scene) {
    const name = el('input', { type: 'text', testid: 'scene-name', maxlength: '100', required: true, value: scene ? scene.name : '' });
    const steps = new StepList(this.view.devices, this.view.groups, scene ? scene.steps : []);
    if (!scene) steps.add();
    this.open(scene ? 'Change scene' : 'New scene', 'scene-editor', [field('Name', name), el('h3', { text: 'Steps' }), steps.box], async () => {
      const saved = await this.app.api.saveScene(this.app.home.id, scene && scene.id, { name: name.value.trim(), steps: steps.value() });
      this.app.status.success(`${saved.name} saved.`);
    });
  }

  schedule(schedule) {
    const trigger = schedule ? schedule.trigger : { kind: 'time', at: '19:00' };
    const name = el('input', { type: 'text', testid: 'schedule-name', maxlength: '100', required: true, value: schedule ? schedule.name : '' });
    const kind = stepChoice([['time', 'At a time'], ['sunrise', 'At sunrise'], ['sunset', 'At sunset']], trigger.kind, 'schedule-kind');
    const at = el('input', { type: 'time', testid: 'schedule-at', value: trigger.at || '19:00', 'aria-label': 'Time' });
    const minutes = el('input', { type: 'number', testid: 'schedule-offset', min: '0', max: '240', value: String(Math.abs(trigger.offset || 0)), 'aria-label': 'Minutes' });
    const side = stepChoice([['before', 'minutes before'], ['after', 'minutes after']], (trigger.offset || 0) < 0 ? 'before' : 'after', 'schedule-offset-side');
    const sunPart = el('div', { className: 'row' }, [minutes, side]);
    const showKind = () => { at.hidden = kind.value !== 'time'; sunPart.hidden = kind.value === 'time'; };
    kind.addEventListener('change', showKind);
    showKind();
    const chosen = new Set(schedule ? schedule.days : [0, 1, 2, 3, 4, 5, 6]);
    const dayBoxes = AUTOMATION_DAYS.map((label, i) => el('label', { className: 'check day-choice' }, [
      el('input', { type: 'checkbox', testid: `schedule-day-${i}`, checked: chosen.has(i), value: String(i) }), el('span', { text: label }),
    ]));
    const scenes = this.view.data.scenes;
    const scene = stepChoice([['', 'No scene'], ...scenes.map((s) => [s.id, s.name])], schedule ? schedule.scene_id || '' : '', 'schedule-scene');
    const enabled = switchInput('schedule-enabled', schedule ? schedule.enabled : true, 'Schedule on');
    const steps = new StepList(this.view.devices, this.view.groups, schedule ? schedule.steps : []);
    if (!schedule && !scenes.length) steps.add();
    const sunNote = this.view.data.settings.latitude === null
      ? el('p', { className: 'muted', testid: 'schedule-sun-note', text: 'Sunrise and sunset need the home\'s location: Settings > Admin > Schedules and Scenes.' })
      : '';
    this.open(schedule ? 'Change schedule' : 'New schedule', 'schedule-editor', [
      field('Name', name),
      el('div', { className: 'row' }, [kind, at, sunPart]),
      sunNote,
      el('div', { className: 'day-choices', role: 'group', 'aria-label': 'Days' }, dayBoxes),
      field('Run a scene', scene),
      el('h3', { text: 'And these steps' }),
      steps.box,
      settingRow('On', 'Off keeps it without running it.', enabled),
    ], async () => {
      const offset = Number.parseInt(minutes.value || '0', 10) * (side.value === 'before' ? -1 : 1);
      const body = {
        name: name.value.trim(),
        enabled: enabled.checked,
        trigger: kind.value === 'time' ? { kind: 'time', at: at.value } : { kind: kind.value, offset },
        days: dayBoxes.map((d) => d.querySelector('input')).filter((b) => b.checked).map((b) => Number(b.value)),
        scene_id: scene.value || null,
        steps: steps.value(),
      };
      const saved = await this.app.api.saveSchedule(this.app.home.id, schedule && schedule.id, body);
      this.app.status.success(`${saved.name} saved.`);
    });
  }
}

window.AutomationEditor = AutomationEditor;
