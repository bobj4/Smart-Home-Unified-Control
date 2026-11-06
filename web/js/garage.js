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
  return [line, buttons];
}

window.garageExtras = garageExtras;
