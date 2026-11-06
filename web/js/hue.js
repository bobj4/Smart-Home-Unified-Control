/**
 * Settings > Integrations > Philips Hue (operators and up): pair the Hue
 * Bridge (press its round button, then Pair), find its lights again, or
 * disconnect it.
 */

class HuePanel {
  constructor(app) {
    this.app = app;
  }

  async render(container) {
    this.box = el('div', { className: 'subpanel', testid: 'hue' });
    container.append(this.box);
    this.draw(await this.app.api.getHue(this.app.home.id));
  }

  draw(bridge) {
    const note = formNote('hue-note');
    if (!bridge.paired) {
      const host = el('input', { type: 'text', testid: 'hue-host', placeholder: '192.168.1.40', required: true });
      const form = el('form', { className: 'row' }, [
        field('Bridge IP address', host),
        el('button', { type: 'submit', testid: 'hue-pair', text: 'Pair' }), note,
      ]);
      form.addEventListener('submit', (event) => {
        event.preventDefault();
        runWithNote(this.app, note, 'Asking the bridge…', async () => {
          const paired = await this.app.api.pairHue(this.app.home.id, host.value.trim());
          this.draw(paired);
          this.app.status.success(`Hue Bridge paired: ${paired.devices} light${paired.devices === 1 ? '' : 's'} and plugs found.`);
        });
      });
      this.box.replaceChildren(
        el('h3', { text: 'Philips Hue Bridge' }),
        el('p', { className: 'muted', text: 'Press the round button on top of the bridge, then press Pair within 30 seconds. The bridge\'s address is in the Hue app: Settings > My Hue system > (your bridge).' }),
        form,
      );
      return;
    }
    this.box.replaceChildren(
      el('h3', { text: 'Philips Hue Bridge' }),
      el('p', { className: 'note', testid: 'hue-paired', text: `Paired with the bridge at ${bridge.host}: ${bridge.devices} light${bridge.devices === 1 ? '' : 's'} and plugs.` }),
      el('div', { className: 'row' }, [
        el('button', {
          type: 'button', className: 'secondary', testid: 'hue-sync', text: 'Find lights again',
          onclick: () => runWithNote(this.app, note, 'Asking the bridge…', async () => {
            const found = await this.app.api.syncHue(this.app.home.id);
            this.draw(found);
            this.app.status.success(`${found.created} new, ${found.updated} updated.`);
          }),
        }),
        el('button', {
          type: 'button', className: 'danger', testid: 'hue-unpair', text: 'Disconnect',
          onclick: () => this.app.run(async () => {
            this.draw(await this.app.api.unpairHue(this.app.home.id));
            this.app.status.success('Hue Bridge disconnected; its lights were removed here.');
          }),
        }),
      ]),
      note,
    );
  }
}

window.HuePanel = HuePanel;
