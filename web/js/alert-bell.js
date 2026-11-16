/**
 * The bell at the top right, between Log out and the home's icon: how many
 * of this home's alerts came since you last looked (a red circle), and
 * their list. Opening the list counts them as seen. Checked every
 * CHECK_MS, and at once when another home is opened. Not shown to guests.
 */

const BELL_CHECK_MS = 30000;

class AlertBell {
  constructor() {
    this.slot = byTestId('alert-bell-slot');
    this.count = el('span', { className: 'bell-count', testid: 'alert-bell-count', hidden: true });
    this.button = el('button', { type: 'button', className: 'ghost bell', testid: 'alert-bell', 'aria-label': 'Alerts', 'aria-haspopup': 'true' }, [
      svg('svg', { viewBox: '0 0 24 24', class: 'bell-icon', 'aria-hidden': 'true' }, [
        svg('path', { d: 'M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z' }),
        svg('path', { d: 'M10 20a2 2 0 0 0 4 0' }),
      ]),
      this.count,
    ]);
    this.menu = el('div', { className: 'home-menu bell-menu', testid: 'alert-bell-menu', role: 'dialog', 'aria-label': 'Alerts', hidden: true });
    this.button.addEventListener('click', () => (this.menu.hidden ? this.open() : this.close()));
    document.addEventListener('click', (e) => { if (!this.menu.hidden && !this.menu.contains(e.target) && !this.button.contains(e.target)) this.close(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !this.menu.hidden) this.close(); });
    this.slot.append(this.button);
    document.body.append(this.menu);
    setInterval(() => this.tick(), 2000);
  }

  get app() {
    return window.smartHomeApp;
  }

  /** Every 2 s: at once for another home (or after logging in), else every BELL_CHECK_MS. */
  tick() {
    const app = this.app;
    const home = app && app.account && app.home && !app.isGuest() ? app.home.id : null;
    this.slot.hidden = !home;
    if (!home || document.hidden) return;
    if (home !== this.home || Date.now() - (this.checked || 0) >= BELL_CHECK_MS) this.check(home);
  }

  async check(home) {
    this.home = home;
    this.checked = Date.now();
    try {
      this.show(await this.app.api.getAlertFeed(home));
    } catch (error) {
      // Offline or logged out: the bell stays as it was.
    }
  }

  show(feed) {
    this.feed = feed;
    this.slot.hidden = false;
    const n = feed.unseen;
    this.count.hidden = n === 0;
    this.count.textContent = n > 99 ? '99+' : String(n);
    this.button.setAttribute('aria-label', n ? `Alerts: ${n} new` : 'Alerts');
  }

  async open() {
    const home = this.home;
    if (!home) return;
    await this.check(home);
    const items = (this.feed && this.feed.items) || [];
    this.menu.replaceChildren(
      el('h3', { text: 'Alerts' }),
      ...(items.length ? items.map((a) => el('div', { className: `bell-item${a.new ? ' new' : ''}`, testid: 'alert-bell-item' }, [
        el('strong', { text: a.title }),
        el('p', { className: 'muted', text: a.body }),
        el('p', { className: 'muted bell-time', text: formatTime(a.at) }),
      ])) : [el('p', { className: 'muted', testid: 'alert-bell-empty', text: 'No alerts yet. Choose yours in My account > Alerts; the bell beside each device in Settings > Devices sets what it alerts about.' })]),
    );
    const box = this.button.getBoundingClientRect();
    this.menu.style.top = `${box.bottom + 6}px`;
    this.menu.hidden = false;
    // Under the bell, but kept on screen (on a phone it is wider than the
    // room left of the bell).
    const room = document.documentElement.clientWidth;
    this.menu.style.right = `${Math.max(8, Math.min(room - box.right, room - this.menu.offsetWidth - 8))}px`;
    if (this.feed && this.feed.unseen) {
      try {
        this.show(await this.app.api.markAlertsSeen(home).then(() => ({ ...this.feed, unseen: 0 })));
      } catch (error) {
        // Counted again next time.
      }
    }
  }

  close() {
    this.menu.hidden = true;
  }
}

window.addEventListener('DOMContentLoaded', () => { window.alertBell = new AlertBell(); });
