/**
 * TV remote: a panel over the devices view with every TV command the backend
 * accepts. While the TV is off, only Power and Close work.
 */

const TV_INPUTS = [['tv', 'TV'], ['hdmi1', 'HDMI 1'], ['hdmi2', 'HDMI 2'], ['hdmi3', 'HDMI 3'], ['hdmi4', 'HDMI 4'], ['usb', 'USB']];
const TV_APPS = [['netflix', 'Netflix'], ['youtube', 'YouTube'], ['prime_video', 'Prime Video'], ['disney_plus', 'Disney+'], ['hulu', 'Hulu'], ['spotify', 'Spotify']];
const TV_DEFAULTS = { on: false, volume: 10, muted: false, channel: 1, input: 'tv', app: null };
const DPAD = [['up', '▲', 'Up'], ['left', '◀', 'Left'], ['select', 'OK', 'Select'], ['right', '▶', 'Right'], ['down', '▼', 'Down']];
// Media keys are drawn as small icons (24x24 paths), like the other keys.
const MEDIA_KEYS = [
  ['rewind', 'M11 6v12L3 12zM21 6v12l-8-6z', 'Rewind'],
  ['play', 'M7 5v14l12-7z', 'Play'],
  ['pause', 'M6 5h4v14H6zM14 5h4v14h-4z', 'Pause'],
  ['stop', 'M6 6h12v12H6z', 'Stop'],
  ['fast_forward', 'M3 6v12l8-6zM13 6v12l8-6z', 'Fast forward'],
];
// Home and Info sit in their own row under Power; these are the rest.
const MENU_KEYS = [['back', 'Back'], ['menu', 'Menu'], ['guide', 'Guide']];

function mediaIcon(path) {
  return svg('svg', { viewBox: '0 0 24 24', width: '18', height: '18', 'aria-hidden': 'true', focusable: 'false' }, [
    svg('path', { d: path, fill: 'currentColor' }),
  ]);
}

class TvRemote {
  constructor(app) {
    this.app = app;
    this.device = null;
    this.overlay = el('div', { className: 'overlay', hidden: true });
    this.overlay.addEventListener('click', (e) => { if (e.target === this.overlay) this.close(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && this.device) this.close(); });
    document.body.append(this.overlay);
  }

  get state() {
    return { ...TV_DEFAULTS, ...(this.device ? this.device.state : {}) };
  }

  open(device) {
    this.device = { ...device, state: { ...(device.state || {}) } };
    this.render();
    this.overlay.hidden = false;
    this.overlay.querySelector('[data-testid="remote-power"]').focus();
  }

  close() {
    this.device = null;
    this.overlay.hidden = true;
    this.overlay.replaceChildren();
    this.app.devices.load().catch((error) => this.app.handleError(error));
  }

  /** Keep the open remote in step with a fresh device list. */
  refresh(devices) {
    if (!this.device) return;
    const fresh = devices.find((d) => d.id === this.device.id);
    if (!fresh || !fresh.controllable) {
      this.close();
      return;
    }
    const same = JSON.stringify(fresh.state || {}) === JSON.stringify(this.device.state)
      && fresh.name === this.device.name;
    this.device = { ...fresh, state: { ...(fresh.state || {}) } };
    // Redraw only when something changed, so the open remote keeps its
    // buttons (and focus) between the 5-second refreshes.
    if (!same) this.render();
  }

  send(command, payload = {}) {
    const device = this.device;
    return this.app.run(async () => {
      const result = await this.app.api.sendCommand(this.app.home.id, device.id, command, payload);
      if (this.device && this.device.id === device.id) {
        this.device.state = result.state;
        this.render();
      }
      this.app.status.success(`${device.name}: ${command.replace(/_/g, ' ')}.`);
    });
  }

  /** 2010-2015 TVs (legacy and encrypted protocols) cannot launch apps. */
  canLaunchApps() {
    const d = this.device;
    return !d || d.integration !== 'samsung_tv' || d.protocol === 'tizen';
  }

  button(testid, text, onclick, { label, className = 'key', always = false } = {}) {
    return el('button', {
      type: 'button', className, testid, text, onclick,
      'aria-label': label, title: label, disabled: !always && !this.state.on,
    });
  }

  render() {
    const s = this.state;
    const off = !s.on;
    const source = s.app
      ? TV_APPS.find(([id]) => id === s.app)[1]
      : (TV_INPUTS.find(([id]) => id === s.input) || [s.input, s.input])[1];
    const screen = el('div', { className: `tv-screen${off ? ' off' : ''}`, testid: 'remote-screen' }, [
      el('strong', { text: off ? 'Off' : source }),
      el('span', { testid: 'remote-channel', text: off ? '' : `Channel ${s.channel}` }),
      el('span', { testid: 'remote-volume', text: off ? '' : (s.muted ? 'Muted' : `Volume ${s.volume}`) }),
    ]);

    const level = el('input', { type: 'range', min: '0', max: '100', step: '1', testid: 'remote-volume-level', value: String(s.volume), disabled: off, 'aria-label': 'Volume level' });
    level.addEventListener('change', () => this.send('set_volume', { level: Number(level.value) }));
    const channel = el('input', { type: 'number', min: '1', max: '9999', testid: 'remote-channel-input', inputmode: 'numeric', disabled: off, 'aria-label': 'Channel number' });
    const goTo = () => {
      const number = Number(channel.value);
      if (!Number.isInteger(number) || number < 1 || number > 9999) {
        this.app.status.error('Enter a channel from 1 to 9999.');
        return;
      }
      this.send('set_channel', { channel: number });
    };
    channel.addEventListener('keydown', (e) => { if (e.key === 'Enter') goTo(); });
    const input = el('select', { testid: 'remote-input', disabled: off, 'aria-label': 'Input' },
      TV_INPUTS.map(([id, name]) => el('option', { value: id, text: name })));
    input.value = s.input;
    input.addEventListener('change', () => this.send('set_input', { source: input.value }));

    const key = (id, text, label) => this.button(`remote-key-${id}`, text, () => this.send('press_key', { key: id }), { label });
    const panel = el('div', { className: 'remote', testid: 'tv-remote', role: 'dialog', 'aria-label': `${this.device.name} remote` }, [
      el('div', { className: 'remote-head' }, [
        el('h2', { text: this.device.name }),
        this.button('remote-close', '✕', () => this.close(), { label: 'Close remote', className: 'ghost', always: true }),
      ]),
      screen,
      el('div', { className: 'remote-row' }, [
        this.button('remote-power', '⏻ Power', () => this.send(off ? 'turn_on' : 'turn_off'), { className: `power${off ? '' : ' on'}`, always: true }),
        this.button('remote-mute', s.muted ? 'Unmute' : 'Mute', () => this.send('toggle_mute'), { className: 'key wide' }),
      ]),
      el('div', { className: 'remote-row remote-split', testid: 'remote-home-info' }, [key('home', 'Home', 'Home'), key('info', 'Info', 'Info')]),
      el('div', { className: 'remote-rockers' }, [
        el('div', { className: 'rocker' }, [
          this.button('remote-volume-up', '+', () => this.send('volume_up'), { label: 'Volume up' }),
          el('span', { text: 'VOL' }),
          this.button('remote-volume-down', '−', () => this.send('volume_down'), { label: 'Volume down' }),
        ]),
        el('div', { className: 'dpad' }, DPAD.map(([id, text, label]) => {
          const button = key(id, text, label);
          button.classList.add(`dpad-${id}`);
          return button;
        })),
        el('div', { className: 'rocker' }, [
          this.button('remote-channel-up', '+', () => this.send('channel_up'), { label: 'Channel up' }),
          el('span', { text: 'CH' }),
          this.button('remote-channel-down', '−', () => this.send('channel_down'), { label: 'Channel down' }),
        ]),
      ]),
      el('div', { className: 'remote-row keys' }, MENU_KEYS.map(([id, text]) => key(id, text, text))),
      el('div', { className: 'remote-row keys' }, MEDIA_KEYS.map(([id, path, label]) => {
        const button = key(id, '', label);
        button.append(mediaIcon(path));
        return button;
      })),
      this.device.integration === 'simulated' ? field('Volume', level) : null,
      el('div', { className: 'remote-row' }, [field('Channel', channel), this.button('remote-channel-go', 'Go', goTo, { className: 'key' })]),
      field('Input', input),
      this.canLaunchApps() ? el('div', { className: 'remote-apps', testid: 'remote-apps' }, TV_APPS.map(([id, name]) => this.button(`remote-app-${id}`, name, () => this.send('launch_app', { app: id }), { className: `app${s.app === id ? ' active' : ''}` }))) : null,
    ]);
    const focused = document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.testid : null;
    this.overlay.replaceChildren(panel);
    const again = focused && panel.querySelector(`[data-testid="${focused}"]`);
    if (again && !again.disabled) again.focus();
  }
}

window.TvRemote = TvRemote;
