/**
 * A device (or some of a group's devices) did not follow a command: a popup
 * says which and why, with Retry, so a failure is not missed in the status
 * line at the top of the page.
 */

const COMMAND_WORDS = {
  turn_on: 'turn on', turn_off: 'turn off', set_brightness: 'change brightness', set_color_temp: 'change white',
  set_color: 'change colour', set_temperature: 'change the temperature', set_mode: 'change mode',
};

class CommandPopup {
  constructor(app) {
    this.app = app;
    this.overlay = el('div', { className: 'overlay command-popup-overlay', testid: 'command-popup-overlay', hidden: true });
    this.overlay.addEventListener('click', (e) => { if (e.target === this.overlay) this.close(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !this.overlay.hidden) this.close(); });
    document.body.append(this.overlay);
  }

  name(id) {
    const all = [...(this.app.devices.lastDevices || []), ...(this.app.devices.groupList || [])];
    const found = all.find((d) => d.id === id);
    return found ? found.name : 'The device';
  }

  show({ deviceId, groupId, command, error, failed, again }) {
    const what = COMMAND_WORDS[command] || String(command || '').replace(/_/g, ' ');
    const title = `${this.name(deviceId || groupId)} did not ${what}`;
    const lines = failed
      ? failed.map((r) => el('li', { text: `${this.name(r.device_id)}: ${r.detail || 'no answer'}` }))
      : [el('li', { text: error ? error.message : 'No answer' })];
    const retry = el('button', {
      type: 'button', testid: 'command-popup-retry', text: 'Retry',
      onclick: () => {
        this.close();
        this.app.run(async () => {
          await again();
          await this.app.devices.load();
          this.app.status.success('Done.');
        });
      },
    });
    const box = el('div', { className: 'remote command-popup', testid: 'command-popup', role: 'alertdialog', 'aria-label': title }, [
      el('div', { className: 'remote-head' }, [
        el('h2', { testid: 'command-popup-title', text: title }),
        el('button', { type: 'button', className: 'ghost', testid: 'command-popup-close', text: '✕', 'aria-label': 'Close', onclick: () => this.close() }),
      ]),
      el('ul', { className: 'command-popup-reasons', testid: 'command-popup-reasons' }, lines),
      el('div', { className: 'row' }, [retry, el('button', { type: 'button', className: 'secondary', text: 'Close', onclick: () => this.close() })]),
    ]);
    this.overlay.replaceChildren(box);
    this.overlay.hidden = false;
    retry.focus();
  }

  close() {
    this.overlay.hidden = true;
    this.overlay.replaceChildren();
  }
}

window.CommandPopup = CommandPopup;
