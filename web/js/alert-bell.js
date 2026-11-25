/**
 * The bell at the top right, between Log out and the home's icon: how many
 * of this home's alerts came since you last looked (a red circle), and
 * their list. Opening the list counts them as seen. Standing notices (a
 * thermostat's air filter due) come first and stay until dealt with
 * (Changed Filter, for operators and admins). Each alert can be
 * dismissed from your list: its X on a computer, a swipe on a phone, or all
 * at once with Dismiss All at the bottom (others still see them). Checked every CHECK_MS, and at once when another home is
 * opened. Not shown to guests.
 */

const BELL_CHECK_MS = 30000;
const SWIPE_PX = 80; // a swipe this far dismisses

/** Swipe a row sideways (touch or pen) to call done(); short swipes spring back. */
function swipeToDismiss(row, done) {
  let start = null;
  let dx = 0;
  const reset = () => {
    start = null;
    row.style.transition = '';
    row.style.transform = '';
    row.style.opacity = '';
  };
  row.addEventListener('pointerdown', (e) => {
    if (e.pointerType === 'mouse' || e.target.closest('button')) return;
    start = e.clientX;
    dx = 0;
    row.style.transition = 'none'; // follow the finger
  });
  row.addEventListener('pointermove', (e) => {
    if (start === null) return;
    dx = e.clientX - start;
    row.style.transform = `translateX(${dx}px)`;
    row.style.opacity = String(Math.max(0.2, 1 - Math.abs(dx) / 240));
  });
  row.addEventListener('pointerup', () => {
    if (start === null) return;
    if (Math.abs(dx) < SWIPE_PX) return reset();
    start = null;
    row.style.transition = '';
    row.style.transform = `translateX(${dx > 0 ? '' : '-'}110%)`;
    row.style.opacity = '0';
    done();
  });
  row.addEventListener('pointercancel', reset); // the list scrolled instead
}

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
    document.addEventListener('click', (e) => { if (!this.menu.hidden && e.target.isConnected && !this.menu.contains(e.target) && !this.button.contains(e.target)) this.close(); });
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
    this.fill((this.feed && this.feed.items) || []);
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

  /** The list: standing notices (a filter due) first, then the alerts. */
  fill(items) {
    const loose = items.filter((a) => !a.sticky);
    this.menu.replaceChildren(
      el('h3', { text: 'Notifications' }),
      loose.length ? el('p', { className: 'muted bell-hint', text: 'Swipe an alert to dismiss it.' }) : '',
      ...(items.length ? items.map((a) => (a.sticky ? this.standing(a) : this.item(a))) : [this.empty()]),
      loose.length ? this.dismissAllButton() : '',
    );
  }

  empty() {
    return el('p', { className: 'muted bell-empty', testid: 'alert-bell-empty', text: 'No notifications' });
  }

  /** A notice that stays until it is dealt with (a thermostat's air filter
   * due): no X or swipe; operators and admins press Changed Filter. */
  standing(a) {
    return el('div', { className: 'bell-item sticky', testid: 'alert-bell-standing', 'data-alert-id': a.id }, [
      el('strong', { text: a.title }),
      el('p', { className: 'muted', text: a.body }),
      a.kind === 'filter' && this.app.can('operator') ? el('button', {
        type: 'button', className: 'secondary', testid: 'alert-bell-filter-changed', text: 'Changed Filter',
        onclick: () => this.app.run(async () => {
          const done = await this.app.api.filterChanged(this.home, a.device_id);
          this.app.status.success(done.thermostat_reset === false ? 'Filter change noted here; the thermostat could not be reached to reset its own count.' : 'Filter change noted.');
          await this.check(this.home);
          this.fill(this.feed.items);
        }),
      }) : '',
    ]);
  }

  item(a) {
    const row = el('div', { className: `bell-item${a.new ? ' new' : ''}`, testid: 'alert-bell-item', 'data-alert-id': String(a.id) });
    row.append(
      el('button', { type: 'button', className: 'ghost bell-dismiss', testid: 'alert-bell-dismiss', 'aria-label': `Dismiss: ${a.title}`, text: '\u00d7', onclick: () => this.dismiss(row, a) }),
      el('strong', { text: a.title }),
      el('p', { className: 'muted', text: a.body }),
      el('p', { className: 'muted bell-time', text: formatTime(a.at) }),
    );
    swipeToDismiss(row, () => this.dismiss(row, a));
    return row;
  }

  dismissAllButton() {
    return el('div', { className: 'bell-footer' }, [
      el('button', {
        type: 'button', className: 'secondary', testid: 'alert-bell-dismiss-all', text: 'Dismiss All',
        onclick: () => this.app.run(async () => {
          const feed = await this.app.api.dismissAllAlerts(this.home);
          this.show(feed);
          this.fill(feed.items); // standing notices stay
        }),
      }),
    ]);
  }

  /** Off my list (the server keeps it for the others). */
  async dismiss(row, a) {
    row.classList.add('leaving');
    try {
      this.show(await this.app.api.dismissAlert(this.home, a.id));
    } catch (error) {
      if (error.status !== 404) { // 404: already gone
        row.classList.remove('leaving');
        row.style.transform = '';
        row.style.opacity = '';
        this.app.status.error(error.message || 'Could not dismiss the alert.');
        return;
      }
    }
    row.remove();
    if (!this.menu.querySelector('[data-testid="alert-bell-item"]')) {
      this.menu.querySelectorAll('.bell-hint, .bell-footer').forEach((n) => n.remove());
      if (!this.menu.querySelector('[data-testid="alert-bell-standing"]')) this.menu.append(this.empty());
    }
  }
}

window.addEventListener('DOMContentLoaded', () => { window.alertBell = new AlertBell(); });
