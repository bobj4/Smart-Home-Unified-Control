/**
 * The home's icon at the top right. With more than one home it opens a
 * list of them to switch to (the select beside the name does the same).
 */

class HomeSwitcher {
  constructor(app, slot) {
    this.app = app;
    this.slot = slot;
    this.menu = null;
    document.addEventListener('click', (event) => {
      if (this.menu && !this.slot.contains(event.target)) this.close();
    });
    document.addEventListener('keydown', (event) => { if (event.key === 'Escape') this.close(); });
    window.addEventListener('resize', () => this.close()); // placed for the old size
  }

  render() {
    this.close();
    const home = this.app.home;
    const homes = (this.app.account && this.app.account.homes) || [];
    if (!home) {
      this.slot.replaceChildren();
      return;
    }
    const many = homes.length > 1;
    const badge = el('button', {
      type: 'button', className: 'home-badge ghost', testid: 'home-badge',
      title: many ? `${home.name}: switch home` : home.name,
      'aria-label': many ? `${home.name}: switch home` : home.name,
      'aria-haspopup': many ? 'true' : 'false', 'aria-expanded': 'false',
      onclick: () => { if (many) this.toggle(badge, homes); },
    }, [homeIcon(home)]);
    this.slot.replaceChildren(badge);
  }

  toggle(badge, homes) {
    if (this.menu) {
      this.close();
      return;
    }
    this.menu = el('div', { className: 'home-menu', testid: 'home-menu', role: 'menu' }, homes.map((h) => el('button', {
      type: 'button', role: 'menuitem', testid: 'home-menu-item',
      className: h.id === this.app.home.id ? 'on' : '',
      'aria-current': String(h.id === this.app.home.id),
      onclick: () => {
        this.close();
        if (h.id !== this.app.home.id) this.app.selectHome(h.id);
      },
    }, [homeIcon(h), el('span', { text: h.name })])));
    badge.setAttribute('aria-expanded', 'true');
    // Fixed under the badge: the top bar scrolls sideways and would clip it.
    const box = badge.getBoundingClientRect();
    this.menu.style.setProperty('top', `${Math.round(box.bottom + 6)}px`);
    this.menu.style.setProperty('right', `${Math.max(8, Math.round(window.innerWidth - box.right))}px`);
    this.slot.append(this.menu);
  }

  close() {
    if (!this.menu) return;
    this.menu.remove();
    this.menu = null;
    const badge = this.slot.querySelector('[data-testid="home-badge"]');
    if (badge) badge.setAttribute('aria-expanded', 'false');
  }
}

window.HomeSwitcher = HomeSwitcher;
