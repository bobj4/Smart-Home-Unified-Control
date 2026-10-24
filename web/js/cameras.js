/**
 * Cameras view (#/cameras): recent Frigate events with thumbnails; a clip
 * plays in a panel over the page. Images and video come through this app.
 */

class CamerasView {
  constructor(app, root) {
    this.app = app;
    this.root = root;
    this.camera = '';
    this.player = el('div', { className: 'overlay', hidden: true });
    this.player.addEventListener('click', (e) => { if (e.target === this.player) this.closeClip(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !this.player.hidden) this.closeClip(); });
    document.body.append(this.player);
  }

  base() {
    return `${API_BASE}/homes/${encodeURIComponent(this.app.home.id)}/cameras`;
  }

  async load() {
    let cameras;
    try {
      cameras = await this.app.api.getCameras(this.app.home.id);
    } catch (error) {
      if (error instanceof AuthError || error.status !== 409) throw error;
      this.root.replaceChildren(el('p', { className: 'empty', testid: 'cameras-not-set-up', text: `Cameras are not available: ${error.message}.` }));
      return;
    }
    const filter = el('select', { testid: 'camera-filter', 'aria-label': 'Camera' },
      [el('option', { value: '', text: 'All cameras' }), ...cameras.map((c) => el('option', { value: c, text: c.replace(/_/g, ' ') }))]);
    filter.value = cameras.includes(this.camera) ? this.camera : '';
    filter.addEventListener('change', () => { this.camera = filter.value; this.app.run(() => this.fillEvents()); });
    this.grid = el('div', { className: 'event-grid' });
    this.root.replaceChildren(
      el('div', { className: 'actions events-bar' }, [
        el('h2', { text: 'Recent events' }),
        filter,
        el('button', { type: 'button', className: 'secondary', testid: 'events-refresh', text: 'Refresh', onclick: () => this.app.run(() => this.fillEvents()) }),
      ]),
      this.grid,
    );
    await this.fillEvents();
  }

  async fillEvents() {
    const events = await this.app.api.getCameraEvents(this.app.home.id, this.camera);
    if (events.length === 0) {
      this.grid.replaceChildren(el('p', { className: 'empty', testid: 'events-empty', text: 'No events yet.' }));
      return;
    }
    this.grid.replaceChildren(...events.map((e) => this.eventCard(e)));
  }

  eventCard(event) {
    const id = encodeURIComponent(event.id);
    const when = event.start_time ? new Date(event.start_time * 1000).toLocaleString() : '';
    const score = event.score !== null ? ` · ${Math.round(event.score * 100)}%` : '';
    return el('article', { className: 'event-card', testid: 'camera-event', 'data-event-id': event.id }, [
      el('img', { className: 'event-thumb', testid: 'event-thumb', src: `${this.base()}/events/${id}/thumbnail`, alt: `${event.label} on ${event.camera}`, loading: 'lazy' }),
      el('div', { className: 'event-info' }, [
        el('strong', { text: event.sub_label ? `${event.label} (${event.sub_label})` : event.label }),
        el('p', { className: 'muted', text: `${event.camera.replace(/_/g, ' ')}${score}` }),
        el('p', { className: 'muted', text: when }),
        event.has_clip
          ? el('button', { type: 'button', testid: 'event-play', text: '▶ Play clip', onclick: () => this.openClip(event) })
          : el('p', { className: 'muted', text: 'No clip' }),
      ]),
    ]);
  }

  openClip(event) {
    const video = el('video', { testid: 'event-video', controls: true, autoplay: true, playsinline: true, preload: 'metadata', src: `${this.base()}/events/${encodeURIComponent(event.id)}/clip` });
    this.player.replaceChildren(el('div', { className: 'clip-panel', role: 'dialog', 'aria-label': `${event.label} clip` }, [
      el('div', { className: 'remote-head' }, [
        el('h2', { text: `${event.label} · ${event.camera.replace(/_/g, ' ')}` }),
        el('button', { type: 'button', className: 'ghost', testid: 'event-close', text: '✕', 'aria-label': 'Close clip', onclick: () => this.closeClip() }),
      ]),
      video,
    ]));
    this.player.hidden = false;
  }

  closeClip() {
    const video = this.player.querySelector('video');
    if (video) video.pause();
    this.player.hidden = true;
    this.player.replaceChildren();
  }
}

window.CamerasView = CamerasView;
