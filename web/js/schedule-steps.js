/**
 * Schedules and Scenes: the list of steps in a scene or schedule. A step
 * is a device or a group, a command for it, and its value (brightness,
 * white, color, temperature, mode...). The server checks each step again.
 */

const STEP_COMMANDS = {
  light: [['turn_on', 'On'], ['turn_off', 'Off'], ['set_brightness', 'Brightness', 'brightness'], ['set_color_temp', 'White', 'kelvin'], ['set_color', 'Color', 'color']],
  plug: [['turn_on', 'On'], ['turn_off', 'Off']],
  tv: [['turn_on', 'On'], ['turn_off', 'Off']],
  garage_door: [['open', 'Open'], ['close', 'Close']],
  thermostat: [['set_mode', 'Mode', 'mode'], ['set_temperature', 'Heat to (or set to)', 'temperature'], ['set_cool_temperature', 'Cool to', 'temperature'], ['set_fan', 'Fan', 'fan'], ['set_hold', 'Hold', 'hold']],
  water_heater: [['set_temperature', 'Set to', 'temperature'], ['turn_on', 'On'], ['turn_off', 'Off'], ['set_away', 'Away', 'away'], ['resume_schedule', 'Follow its schedule']],
};
const GROUP_STEP_COMMANDS = STEP_COMMANDS.light;
const STEP_CHOICES = {
  fan: [['auto', 'Auto'], ['on', 'On']],
  hold: [['schedule', 'Follow schedule'], ['temporary', 'Until next change'], ['permanent', 'Permanent']],
  away: [['true', 'Away'], ['false', 'Home']],
};

function stepChoice(options, value, testid) {
  const select = el('select', { testid }, options.map(([v, label]) => el('option', { value: v, text: label })));
  if (value !== undefined && value !== null) select.value = String(value);
  return select;
}

class StepList {
  /** devices, groups: the home's; steps: [{kind, id, command, payload}]. */
  constructor(devices, groups, steps) {
    this.devices = devices.filter((d) => STEP_COMMANDS[d.type]);
    this.groups = groups;
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
    const device = this.devices.find((d) => d.id === id);
    return { kind, id, device, commands: device ? STEP_COMMANDS[device.type] : [] };
  }

  add(step = null) {
    const options = [
      ...this.devices.map((d) => el('option', { value: `device:${d.id}`, text: d.room ? `${d.name} (${d.room})` : d.name })),
      ...this.groups.map((g) => el('option', { value: `group:${g.id}`, text: `${g.name} (group)` })),
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
      if (key === 'brightness') input = el('input', { type: 'number', min: '0', max: '100', value: String(payload.brightness ?? 50), 'aria-label': 'Brightness %' });
      if (key === 'kelvin') input = el('input', { type: 'number', min: '2000', max: '6500', step: '100', value: String(payload.kelvin ?? 2700), 'aria-label': 'White (kelvin)' });
      if (key === 'color') input = el('input', { type: 'color', value: payload.color || '#ffaa55', 'aria-label': 'Color' });
      if (key === 'temperature') input = el('input', { type: 'number', step: '1', value: String(payload.temperature ?? 70), 'aria-label': 'Temperature' });
      if (key === 'mode') input = stepChoice(((device && device.state.modes) || ['off', 'heat', 'cool', 'auto']).map((m) => [m, m]), payload.mode, 'step-choice');
      if (STEP_CHOICES[key]) input = stepChoice(STEP_CHOICES[key], payload[key], 'step-choice');
      if (input) input.dataset.key = key;
      if (input && !input.dataset.testid) input.dataset.testid = 'step-value';
      value.replaceChildren(input || '');
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
