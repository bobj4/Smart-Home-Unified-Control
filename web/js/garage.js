/**
 * A garage door's tile: where the door is (open, closed, moving) and Open,
 * Close and, while it moves, Stop. Opening asks first, so a stray tap does
 * not open the garage.
 */

const DOOR_WORDS = { open: 'Open', closed: 'Closed', opening: 'Opening…', closing: 'Closing…', stopped: 'Stopped' };

function garageExtras(view, device, state) {
  const door = state.door || 'stopped';
  const moving = door === 'opening' || door === 'closing';
  const disabled = !device.controllable;
  const line = el('p', { className: `garage-state ${door}`, testid: 'garage-state', text: DOOR_WORDS[door] || door });
  const buttons = el('div', { className: 'row' }, [
    el('button', {
      type: 'button', className: 'secondary', testid: 'garage-open', text: 'Open', disabled: disabled || door === 'open',
      onclick: (event) => {
        const button = event.currentTarget;
        if (button.dataset.confirm !== 'yes') {
          button.dataset.confirm = 'yes';
          button.textContent = 'Tap again to open';
          setTimeout(() => { button.dataset.confirm = ''; button.textContent = 'Open'; }, 4000);
          return;
        }
        view.command(device, 'open');
      },
    }),
    el('button', { type: 'button', className: 'secondary', testid: 'garage-close', text: 'Close', disabled: disabled || door === 'closed', onclick: () => view.command(device, 'close') }),
    moving ? el('button', { type: 'button', className: 'danger', testid: 'garage-stop', text: 'Stop', disabled, onclick: () => view.command(device, 'stop') }) : null,
  ]);
  // A ratgdo's extras, when the opener has them: in the way, light, lockout.
  const extras = [];
  if (state.obstruction) extras.push(el('p', { className: 'garage-blocked', testid: 'garage-obstruction', text: 'Something is in the way' }));
  const parts = [];
  if (state.light !== undefined && state.light !== null) {
    parts.push(el('button', { type: 'button', className: `toggle${state.light ? ' on' : ''}`, testid: 'garage-light', text: state.light ? 'Light on' : 'Light off', disabled, onclick: () => view.command(device, state.light ? 'light_off' : 'light_on') }));
  }
  if (state.locked !== undefined && state.locked !== null) {
    parts.push(el('button', { type: 'button', className: `toggle${state.locked ? ' on' : ''}`, testid: 'garage-lock', text: state.locked ? 'Remotes locked' : 'Remotes work', title: 'Lock out the wall button and remotes', disabled, onclick: () => view.command(device, state.locked ? 'unlock' : 'lock') }));
  }
  if (parts.length) extras.push(el('div', { className: 'row' }, parts));
  const parking = parkingAssist(view, device, state, disabled);
  if (parking) extras.push(parking);
  return [line, ...extras, buttons];
}

/** ratgdo32 disco: the parking laser, whether a car is in, how far, and
 * where the laser tells the driver to stop (set here, in cm). */
function parkingAssist(view, device, state, disabled) {
  if (state.laser === undefined || state.laser === null) return null;
  const cm = (mm) => `${Math.round(mm / 10)} cm`;
  const car = state.vehicle === true ? 'Car in' : state.vehicle === false ? 'No car' : '';
  const far = typeof state.vehicle_distance_mm === 'number' && state.vehicle ? ` · ${cm(state.vehicle_distance_mm)} away` : '';
  const parts = [
    el('div', { className: 'row' }, [
      el('button', { type: 'button', className: `toggle${state.laser ? ' on' : ''}`, testid: 'garage-laser', text: state.laser ? 'Parking laser on' : 'Parking laser off', disabled, onclick: () => view.command(device, state.laser ? 'laser_off' : 'laser_on') }),
    ]),
    car ? el('p', { className: 'muted', testid: 'garage-vehicle', text: `${car}${far}` }) : '',
  ];
  if (typeof state.parking_target_mm === 'number') {
    const input = el('input', { type: 'number', min: '10', max: '500', step: '1', testid: 'garage-parking-target', value: String(Math.round(state.parking_target_mm / 10)), 'aria-label': 'Stop at (cm from the opener)', disabled });
    parts.push(el('div', { className: 'row parking-target' }, [
      el('label', { className: 'muted', text: 'Stop at (cm)' }), input,
      el('button', { type: 'button', className: 'secondary', testid: 'garage-parking-set', text: 'Set', disabled, onclick: () => view.command(device, 'set_parking_target', { mm: Number.parseInt(input.value, 10) * 10 }) }),
    ]));
  }
  return el('div', { className: 'garage-parking', testid: 'garage-parking' }, parts);
}

window.garageExtras = garageExtras;
