/**
 * Light settings window: brightness, white temperature and colour, opened
 * from a light's card so a stray tap on the card cannot change them.
 */

class LightPanel {
  constructor(app) {
    this.app = app;
    this.device = null;
    this.overlay = el('div', { className: 'overlay', hidden: true });
    this.overlay.addEventListener('click', (e) => { if (e.target === this.overlay) this.close(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && this.device) this.close(); });
    document.body.append(this.overlay);
  }

  open(device) {
    this.device = { ...device, state: { ...(device.state || {}) } };
    this.render();
    this.overlay.hidden = false;
  }

  close() {
    this.device = null;
    this.overlay.hidden = true;
    this.overlay.replaceChildren();
    this.app.devices.load().catch((error) => this.app.handleError(error));
  }

  refresh(devices) {
    if (!this.device) return;
    const fresh = devices.find((d) => d.id === this.device.id);
    if (!fresh || !fresh.controllable) this.close();
  }

  send(command, payload) {
    const device = this.device;
    return this.app.run(async () => {
      const result = device.isGroup
        ? await this.app.api.groupCommand(this.app.home.id, device.id, command, payload)
        : await this.app.api.sendCommand(this.app.home.id, device.id, command, payload);
      if (this.device && this.device.id === device.id) {
        this.device.state = device.isGroup ? result.group.state : result.state;
        this.render();
      }
      this.app.status.success(`${device.name}: saved.`);
    });
  }

  render() {
    const s = { brightness: 100, color_temp: 2700, color: '#ffffff', color_mode: 'temp', ...this.device.state };
    const brightness = el('input', { type: 'range', min: '1', max: '100', step: '1', testid: 'light-brightness', value: String(s.brightness), 'aria-label': 'Brightness' });
    brightness.addEventListener('change', () => this.send('set_brightness', { brightness: Number(brightness.value) }));
    const temp = el('input', { type: 'range', min: '2000', max: '6500', step: '100', className: 'temp-slider', testid: 'light-temp', value: String(s.color_temp), 'aria-label': 'White temperature' });
    temp.addEventListener('change', () => this.send('set_color_temp', { kelvin: Number(temp.value) }));
    const color = el('input', { type: 'color', testid: 'light-color', value: s.color, 'aria-label': 'Colour' });
    color.addEventListener('change', () => this.send('set_color', { color: color.value }));
    const swatch = el('div', { className: 'light-swatch', testid: 'light-swatch' });
    if (s.on) swatch.style.setProperty('--light', lightColor(s));
    const panel = el('div', { className: 'light-panel', testid: 'light-panel', role: 'dialog', 'aria-label': `${this.device.name} settings` }, [
      el('div', { className: 'remote-head' }, [
        el('h2', { text: this.device.name }),
        el('button', { type: 'button', className: 'ghost', testid: 'light-close', text: '✕', 'aria-label': 'Close', onclick: () => this.close() }),
      ]),
      swatch,
      el('div', { className: 'light-controls', 'data-mode': s.color_mode === 'rgb' ? 'rgb' : 'temp' }, [
        field(`Brightness ${s.brightness}%`, brightness),
        field(`White ${s.color_temp} K`, temp),
        el('label', { className: 'field color-field' }, [el('span', { text: 'Colour' }), color]),
      ]),
    ]);
    this.overlay.replaceChildren(panel);
  }
}

window.LightPanel = LightPanel;
