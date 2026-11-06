/**
 * Filters at the top of the Devices page: a search box (name or room), a
 * type and "On only". Remembered with the person's layout (per screen
 * type). The bar is created once and kept while the page refreshes, so
 * typing is never interrupted.
 */

class DeviceFilters {
  constructor(view) {
    this.view = view;
    this.state = { text: '', type: '', on: false, ...(view.layoutFilters || {}) };
    this.search = el('input', { type: 'search', testid: 'filter-search', placeholder: 'Search devices', 'aria-label': 'Search devices', value: this.state.text });
    this.type = el('select', { testid: 'filter-type', 'aria-label': 'Device type' });
    this.on = el('input', { type: 'checkbox', testid: 'filter-on', checked: Boolean(this.state.on) });
    this.search.addEventListener('input', () => this.changed());
    this.type.addEventListener('change', () => this.changed());
    this.on.addEventListener('change', () => this.changed());
    this.element = el('div', { className: 'device-filters', testid: 'device-filters' }, [
      this.search, this.type, el('label', { className: 'check' }, [this.on, ' On only']),
    ]);
  }

  changed() {
    this.state = { text: this.search.value, type: this.type.value, on: this.on.checked };
    this.view.render(this.view.lastDevices);
    // Saved a moment after the last change, not on every key.
    clearTimeout(this.saving);
    this.saving = setTimeout(() => {
      const { app } = this.view;
      app.api.setLayout(app.home.id, { filters: this.state, screen: this.view.layoutScreen }).catch((error) => app.handleError(error));
    }, 600);
  }

  /** Another screen type's (or home's) saved filters. */
  use(state) {
    this.state = { text: '', type: '', on: false, ...(state || {}) };
    this.search.value = this.state.text;
    this.on.checked = Boolean(this.state.on);
  }

  get active() {
    return Boolean(this.state.text.trim() || this.state.type || this.state.on);
  }

  clear() {
    this.search.value = '';
    this.type.value = '';
    this.on.checked = false;
    this.changed();
  }

  /** The type list shows only the types this home has. */
  setTypes(types) {
    const wanted = ['', ...[...new Set(types)].sort()];
    const have = [...this.type.options].map((o) => o.value);
    if (wanted.join('|') !== have.join('|')) {
      this.type.replaceChildren(...wanted.map((t) => el('option', { value: t, text: t ? typeLabel(t) : 'All types' })));
    }
    this.type.value = wanted.includes(this.state.type) ? this.state.type : '';
  }

  /** Whether a device (or a group shown as one) passes the filters. */
  matches(item) {
    const { text, type, on } = this.state;
    if (type && item.type !== type) return false;
    if (on && !(item.state && item.state.on)) return false;
    const words = text.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const hay = `${item.name} ${item.room || ''}`.toLowerCase();
    return words.every((w) => hay.includes(w));
  }
}

window.DeviceFilters = DeviceFilters;
