/** A small window with a device's network details (IP and MAC address). */

class DeviceInfoPanel {
  constructor() {
    this.overlay = el('div', { className: 'overlay', hidden: true });
    this.overlay.addEventListener('click', (e) => { if (e.target === this.overlay) this.close(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !this.overlay.hidden) this.close(); });
    document.body.append(this.overlay);
  }

  open(device) {
    const net = device.network || {};
    const line = (label, value) => el('div', { className: 'info-line' }, [el('dt', { text: label }), el('dd', { text: value || 'not reported by the device' })]);
    this.overlay.replaceChildren(el('div', { className: 'remote info-panel', testid: 'device-info-panel', role: 'dialog', 'aria-label': `${device.name} network details` }, [
      el('div', { className: 'remote-head' }, [
        el('h2', { text: device.name }),
        el('button', { type: 'button', className: 'ghost', testid: 'device-info-close', text: '✕', 'aria-label': 'Close', onclick: () => this.close() }),
      ]),
      el('dl', {}, [
        line('IP address', net.ip),
        line('MAC address', net.mac),
        line('Type', device.type.replace('_', ' ')),
        line('Brand', device.integration),
      ]),
    ]));
    this.overlay.hidden = false;
    this.overlay.querySelector('[data-testid="device-info-close"]').focus();
  }

  close() {
    this.overlay.hidden = true;
    this.overlay.replaceChildren();
  }
}

/** The ⓘ button that opens it (one shared window for the page). */
function deviceInfoButton(device) {
  if (!window.deviceInfo) window.deviceInfo = new DeviceInfoPanel();
  return el('button', {
    type: 'button', className: 'icon-button', testid: 'device-info', text: 'ⓘ',
    'aria-label': `Network details for ${device.name}`, title: 'Network details',
    onclick: () => window.deviceInfo.open(device),
  });
}

window.deviceInfoButton = deviceInfoButton;
