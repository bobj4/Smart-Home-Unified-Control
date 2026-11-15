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
  return [line, ...extras, buttons];
}

window.garageExtras = garageExtras;
