/**
 * Editing one day of a thermostat schedule: its periods (start time and set
 * points, or which sensors to read), copied to any other days on saving.
 * The thermostat stores it and reads it back before saving counts.
 */

const EDIT_TITLES = { heat: 'heating', cool: 'cooling', auto: 'auto', sensors: 'sensor' };

function addMinutes(time, minutes) {
  const [h, m] = time.split(':').map(Number);
  const total = Math.min(23 * 60 + 59, h * 60 + m + minutes);
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`;
}

/** A form for one day; `save(days, periods)` returns a promise. */
function scheduleEditor({ kind, day, periods, limits, sensors, save, cancel }) {
  const low = limits && limits.min_temperature;
  const high = limits && limits.max_temperature;
  const start = (limits && limits.default_target) || 68;
  const rows = el('div', { className: 'sched-rows', testid: 'sched-rows' });
  const error = el('p', { className: 'warning', testid: 'sched-error', hidden: true });

  const number = (testid, value, label) => el('input', {
    type: 'number', step: '0.5', min: low, max: high, testid, value: value == null ? '' : String(value), 'aria-label': label,
  });

  const addRow = (period) => {
    const time = el('input', { type: 'time', testid: 'sched-time', value: period.time, required: true, 'aria-label': 'Start time' });
    const fields = [time];
    if (kind === 'heat' || kind === 'auto') fields.push(number('sched-heat', period.heat, 'Heat to'));
    if (kind === 'cool' || kind === 'auto') fields.push(number('sched-cool', period.cool, 'Cool to'));
    if (kind === 'sensors') {
      const read = el('select', { testid: 'sched-read', 'aria-label': 'Read' }, [
        el('option', { value: 'all', text: 'All sensors' }),
        el('option', { value: 'thermostat', text: 'Thermostat only' }),
        ...sensors.map((s) => el('option', { value: `sensor:${s.pin}`, text: s.name })),
      ]);
      read.value = period.read === 'sensor' ? `sensor:${period.pin}` : (period.read || 'all');
      fields.push(read);
    }
    const row = el('div', { className: 'sched-row', testid: 'sched-row' }, [
      ...fields,
      el('button', { type: 'button', className: 'ghost', testid: 'sched-remove', text: '✕', 'aria-label': 'Remove this period', onclick: () => row.remove() }),
    ]);
    rows.append(row);
  };
  periods.forEach(addRow);

  const add = el('button', {
    type: 'button', className: 'secondary', testid: 'sched-add', text: 'Add period',
    onclick: () => {
      const times = [...rows.querySelectorAll('[data-testid="sched-time"]')].map((t) => t.value).filter(Boolean).sort();
      const time = times.length ? addMinutes(times[times.length - 1], 120) : '06:00';
      addRow({ time, heat: start, cool: Math.min(high || start + 6, start + 6), read: 'all' });
    },
  });

  const dayBoxes = SCHEDULE_DAYS.map(([key, name]) => {
    const box = el('input', { type: 'checkbox', testid: `sched-day-${key}`, checked: key === day });
    return el('label', { className: 'sched-day' }, [box, el('span', { text: name })]);
  });

  const collect = () => [...rows.querySelectorAll('[data-testid="sched-row"]')].map((row) => {
    const get = (id) => row.querySelector(`[data-testid="${id}"]`);
    const period = { time: get('sched-time').value };
    if (get('sched-heat')) period.heat = Number(get('sched-heat').value);
    if (get('sched-cool')) period.cool = Number(get('sched-cool').value);
    if (get('sched-read')) {
      const [read, pin] = get('sched-read').value.split(':');
      period.read = read;
      if (pin) period.pin = pin;
    }
    return period;
  }).sort((a, b) => a.time.localeCompare(b.time));

  const saveButton = el('button', {
    type: 'button', testid: 'sched-save', text: 'Save',
    onclick: async () => {
      error.hidden = true;
      const days = SCHEDULE_DAYS.map(([key]) => key).filter((key, i) => dayBoxes[i].querySelector('input').checked);
      const chosen = collect();
      const times = chosen.map((p) => p.time);
      if (!days.length) { error.textContent = 'Choose at least one day.'; error.hidden = false; return; }
      if (times.some((t) => !t) || new Set(times).size !== times.length) {
        error.textContent = 'Every period needs its own start time.'; error.hidden = false; return;
      }
      saveButton.disabled = true;
      saveButton.textContent = 'Saving…';
      try {
        await save(days, chosen);
      } catch (e) {
        error.textContent = e.message;
        error.hidden = false;
        saveButton.disabled = false;
        saveButton.textContent = 'Save';
      }
    },
  });

  return el('div', { className: 'sched-editor', testid: 'sched-editor' }, [
    el('h3', { text: `Edit the ${EDIT_TITLES[kind]} schedule` }),
    rows,
    add,
    el('p', { className: 'muted', text: 'Save the same periods to:' }),
    el('div', { className: 'sched-days' }, dayBoxes),
    kind === 'sensors' ? null : el('p', { className: 'muted', text: 'The thermostat follows this only while its hold button shows Following schedule.' }),
    error,
    el('div', { className: 'row' }, [
      saveButton,
      el('button', { type: 'button', className: 'secondary', testid: 'sched-cancel', text: 'Cancel', onclick: cancel }),
    ]),
  ]);
}

window.scheduleEditor = scheduleEditor;
