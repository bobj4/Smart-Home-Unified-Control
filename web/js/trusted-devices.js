/**
 * Approved devices ("Remember this device" at login: no two-factor code
 * needed there). My account lists your own; Admin lists everyone's in your
 * homes, with whose each one is. Removing one means the code is asked for
 * again on that device.
 */

class TrustedDevicesList {
  /** `all`: the admin's list of everyone's devices. */
  constructor(app, { all = false } = {}) {
    this.app = app;
    this.all = all;
    this.box = el('div', { className: 'sessions', testid: all ? 'all-devices' : 'my-devices' });
  }

  async render(container) {
    container.append(this.box);
    await this.load();
  }

  async load() {
    const api = this.app.api;
    const devices = this.all ? await api.getAllDevices() : await api.getMyDevices();
    if (!devices.length) {
      this.box.replaceChildren(el('p', {
        className: 'muted', testid: 'devices-none',
        text: this.all ? 'Nobody has an approved device.' : 'No approved devices. Tick "Remember this device" when you log in to add one.',
      }));
      return;
    }
    this.box.replaceChildren(...devices.map((d) => this.row(d)));
  }

  row(device) {
    const until = device.expires_at ? `until ${formatTime(device.expires_at)}` : 'no expiry';
    const used = device.last_used_at ? `last used ${formatTime(device.last_used_at)}` : 'not used since approved';
    const who = this.all ? `${device.user_name || device.user} · ` : '';
    return el('div', { className: 'session-row', testid: 'trusted-device', 'data-device-id': device.id, 'data-current': String(device.current) }, [
      el('div', {}, [
        el('strong', { text: `${who}${device.name}${device.current ? ' (this device)' : ''}` }),
        el('p', { className: 'muted', text: `Approved ${formatTime(device.created_at)}${device.ip_address ? ` from ${device.ip_address}` : ''} · ${used} · ${until}` }),
      ]),
      el('button', {
        type: 'button', className: 'secondary', testid: 'trusted-device-forget', text: 'Remove',
        'aria-label': `Remove ${device.name}`,
        onclick: () => this.app.run(async () => {
          if (this.all) await this.app.api.forgetAnyDevice(device.id);
          else await this.app.api.forgetMyDevice(device.id);
          await this.load();
          this.app.status.success('Removed: that device will ask for the code again.');
        }),
      }),
    ]);
  }
}

window.TrustedDevicesList = TrustedDevicesList;
