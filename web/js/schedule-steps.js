/**
 * Schedules and Scenes: the list of steps in a scene or schedule. A step
 * is a device or a group, a command for it, and its value (brightness,
 * white, color, temperature, mode...). The server checks each step again.
 */

const STEP_COMMANDS = {
  light: [['turn_on', 'On'], ['turn_off', 'Off'], ['set_brightness', 'Brightness', 'brightness'], ['set_color_temp', 'White', 'kelvin'], ['set_color', 'Color', 'color'], ['flash', 'Flash', 'flash']],
  plug: [['turn_on', 'On'], ['turn_off', 'Off']],
  tv: [['turn_on', 'On'], ['turn_off', 'Off']],
  garage_door: [['open', 'Open'], ['close', 'Close'], ['light_on', 'Light on'], ['light_off', 'Light off'], ['laser_on', 'Parking laser on'], ['laser_off', 'Parking laser off']],
  thermostat: [['set_mode', 'Mode', 'mode'], ['set_temperature', 'Heat to (or set to)', 'temperature'], ['set_cool_temperature', 'Cool to', 'temperature'], ['set_fan', 'Fan', 'fan'], ['set_hold', 'Hold', 'hold']],
  water_heater: [['set_temperature', 'Set to', 'temperature'], ['turn_on', 'On'], ['turn_off', 'Off'], ['set_away', 'Away', 'away'], ['resume_schedule', 'Follow its schedule']],
};
const GROUP_STEP_COMMANDS = STEP_COMMANDS.light;
// Color samples beside a step's color (and its own picker for any other).
const STEP_SWATCHES = [
  ['#ff0000', 'Red'], ['#ff6a00', 'Orange'], ['#ffb000', 'Amber'], ['#ffe600', 'Yellow'],
  ['#7cff00', 'Lime'], ['#00c853', 'Green'], ['#00e5ff', 'Cyan'], ['#2962ff', 'Blue'],
  ['#7c4dff', 'Purple'], ['#e040fb', 'Magenta'], ['#ff4081', 'Pink'], ['#ffaa55', 'Warm glow'],
];
const STEP_CHOICES = {
  fan: [['auto', 'Auto'], ['on', 'On']],
  hold: [['schedule', 'Follow schedule'], ['temporary', 'Until next change'], ['permanent', 'Permanent']],
  away: [['true', 'Away'], ['false', 'Home']],
};

/** A color input with its samples; the input keeps the value (data-key). */
function colorWithSwatches(value) {
  const input = el('input', { type: 'color', value, 'aria-label': 'Color' });
  const swatches = STEP_SWATCHES.map(([hex, name]) => el('button', {
    type: 'button', className: 'step-swatch', testid: 'step-swatch', title: name, 'aria-label': name, 'data-color': hex,
    onclick: () => { input.value = hex; mark(); },
  }));
  const mark = () => swatches.forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.color === input.value.toLowerCase())));
  swatches.forEach((b) => b.style.setProperty('--swatch', b.dataset.color));
  input.addEventListener('input', mark);
  mark();
  return { input, box: el('span', { className: 'step-color' }, [input, el('span', { className: 'step-swatches', role: 'group', 'aria-label': 'Color samples' }, swatches)]) };
}

/** Flash: how many times, how long each lasts, how long between (seconds). */
function flashInputs(payload) {
  const number = (key, label, value, attrs) => {
    const input = el('input', { type: 'number', value: String(value), 'aria-label': label, testid: `step-flash-${key}`, ...attrs });
    input.dataset.flash = key;
    return el('label', { className: 'step-flash-part' }, [el('span', { className: 'muted', text: label }), input]);
  };
  const seconds = { min: '0.5', max: '10', step: '0.5' };
  return el('span', { className: 'step-flash' }, [
    number('times', 'Times', payload.times ?? 3, { min: '1', max: '20', step: '1' }),
    number('on_seconds', 'Flash lasts (s)', payload.on_seconds ?? 1, seconds),
    number('off_seconds', 'Between (s)', payload.off_seconds ?? 1, seconds),
  ]);
}

function stepChoice(options, value, testid) {
  const select = el('select', { testid }, options.map(([v, label]) => el('option', { value: v, text: label })));
  if (value !== undefined && value !== null) select.value = String(value);
  return select;
}

class StepList {
  /** devices, groups, hueScenes: the home's; steps: [{kind, id, command, payload}]. */
  constructor(devices, groups, steps, hueScenes = []) {
    this.devices = devices.filter((d) => STEP_COMMANDS[d.type]);
    this.groups = groups;
    this.hueScenes = hueScenes;
    this.list = el('div', { className: 'step-list', testid: 'step-list' });
    this.box = el('div', { className: 'grid' }, [
      this.list,
      el('button', { type: 'button', className: 'secondary', testid: 'step-add', text: 'Add a step', onclick: () => this.add() }),
    ]);
    steps.forEach((s) => this.add(s));
  }

  target(key) {
    const [kind, id] = key.split(':');
    if (kind === 'group') return { kind, id, commands: GROUP_STEP_COMMANDS };
    if (kind === 'hue_scene') return { kind, id, commands: [['recall', 'Show scene']] };
    const device = this.devices.find((d) => d.id === id);
    return { kind, id, device, commands: device ? STEP_COMMANDS[device.type] : [] };
  }

  add(step = null) {
    const options = [
      ...this.devices.map((d) => el('option', { value: `device:${d.id}`, text: d.room ? `${d.name} (${d.room})` : d.name })),
      ...this.groups.map((g) => el('option', { value: `group:${g.id}`, text: `${g.name} (group)` })),
      ...this.hueScenes.map((s) => el('option', { value: `hue_scene:${s.id}`, text: `Hue: ${s.name}${s.room ? ` (${s.room})` : ''}` })),
    ];
    if (!options.length) return;
    const target = el('select', { testid: 'step-target', 'aria-label': 'Device or group' }, options);
    if (step) target.value = `${step.kind}:${step.id}`;
    const command = el('select', { testid: 'step-command', 'aria-label': 'What to do' });
    const value = el('span', { className: 'step-value' });
    const row = el('div', { className: 'step-row', testid: 'step-row' }, [
      target, command, value,
      el('button', { type: 'button', className: 'ghost', testid: 'step-remove', text: '✕', 'aria-label': 'Remove this step', onclick: () => row.remove() }),
    ]);
    const fillValue = (payload = {}) => {
      const chosen = this.target(target.value).commands.find(([c]) => c === command.value);
      const key = chosen && chosen[2];
      const device = this.target(target.value).device;
      let input = null;
      let shown = null; // what goes in the row when it is not the input itself
      if (key === 'brightness') input = el('input', { type: 'number', min: '0', max: '100', value: String(payload.brightness ?? 50), 'aria-label': 'Brightness %' });
      if (key === 'kelvin') input = el('input', { type: 'number', min: '2000', max: '6500', step: '100', value: String(payload.kelvin ?? 2700), 'aria-label': 'White (kelvin)' });
      if (key === 'color') ({ input, box: shown } = colorWithSwatches(payload.color || '#ffaa55'));
      if (key === 'flash') shown = flashInputs(payload);
      if (key === 'temperature') input = el('input', { type: 'number', step: '1', value: String(payload.temperature ?? 70), 'aria-label': 'Temperature' });
      if (key === 'mode') input = stepChoice(((device && device.state.modes) || ['off', 'heat', 'cool', 'auto']).map((m) => [m, m]), payload.mode, 'step-choice');
      if (STEP_CHOICES[key]) input = stepChoice(STEP_CHOICES[key], payload[key], 'step-choice');
      if (input) input.dataset.key = key;
      if (input && !input.dataset.testid) input.dataset.testid = 'step-value';
      value.replaceChildren(shown || input || '');
    };
    const fillCommands = (chosen, payload) => {
      command.replaceChildren(...this.target(target.value).commands.map(([c, label]) => el('option', { value: c, text: label })));
      if (chosen) command.value = chosen;
      fillValue(payload);
    };
    target.addEventListener('change', () => fillCommands());
    command.addEventListener('change', () => fillValue());
    fillCommands(step && step.command, step ? step.payload : {});
    this.list.append(row);
  }

  /** The steps as the server takes them. */
  value() {
    return [...this.list.querySelectorAll('[data-testid="step-row"]')].map((row) => {
      const [kind, id] = row.querySelector('[data-testid="step-target"]').value.split(':');
      const input = row.querySelector('[data-key]');
      const payload = {};
      row.querySelectorAll('[data-flash]').forEach((part) => {
        payload[part.dataset.flash] = part.dataset.flash === 'times' ? Number.parseInt(part.value, 10) : Number(part.value);
      });
      if (input) {
        const key = input.dataset.key;
        if (['brightness', 'kelvin'].includes(key)) payload[key] = Number.parseInt(input.value, 10);
        else if (key === 'temperature') payload.temperature = Number(input.value);
        else if (key === 'away') payload.away = input.value === 'true';
        else payload[key] = input.value;
      }
      return { kind, id, command: row.querySelector('[data-testid="step-command"]').value, payload };
    });
  }
}

window.StepList = StepList;
