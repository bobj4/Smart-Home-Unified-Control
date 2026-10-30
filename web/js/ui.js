/**
 * DOM helpers. Text always goes in through textContent; no HTML is ever
 * built from strings.
 */

const SVG_NS = 'http://www.w3.org/2000/svg';
const ROLE_RANK = { guest: 0, member: 1, operator: 2, admin: 3 };

/** el('button', { testid: 'x', text: 'Go', onclick: fn }, [children]) */
function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  setAttrs(node, attrs);
  for (const child of children) if (child) node.append(child);
  return node;
}

function svg(tag, attrs = {}, children = []) {
  const node = document.createElementNS(SVG_NS, tag);
  setAttrs(node, attrs);
  for (const child of children) if (child) node.append(child);
  return node;
}

function setAttrs(node, attrs) {
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null) continue;
    if (key === 'text') node.textContent = String(value);
    else if (key === 'testid') node.dataset.testid = value;
    else if (key === 'className') node.setAttribute('class', value);
    else if (key.startsWith('on') && typeof value === 'function') {
      node.addEventListener(key.slice(2), value);
    } else if (typeof value === 'boolean' || key === 'value') node[key] = value;
    else node.setAttribute(key, String(value));
  }
}

/** "light" -> "Light", "tv" -> "TV", "water_heater" -> "Water heater". */
function typeLabel(type) {
  const known = { tv: 'TV', water_heater: 'Water heater' };
  if (known[type]) return known[type];
  const words = String(type || '').replace(/_/g, ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function field(label, input) {
  return el('label', { className: 'field' }, [el('span', { text: label }), input]);
}

function section(testid, title, intro) {
  return el('section', { testid, className: 'panel' }, [
    el('h2', { text: title }),
    intro ? el('p', { className: 'muted', text: intro }) : null,
  ]);
}

function formatTime(iso) {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString();
}

/** Split a secret into groups of four so it is easier to type. */
function groupSecret(secret) {
  return secret.replace(/(.{4})/g, '$1 ').trim();
}

/** "Passwords need at least 12 characters, a number." from the login rules. */
function passwordRulesText(options) {
  if (!options) return '';
  const p = options.password;
  const parts = p.min_length > 0 ? [`at least ${p.min_length} characters`] : [];
  if (p.upper) parts.push('an uppercase letter');
  if (p.lower) parts.push('a lowercase letter');
  if (p.digit) parts.push('a number');
  if (p.special) parts.push('a special character');
  return parts.length ? `Passwords need ${parts.join(', ')}.` : 'Any password is accepted.';
}

function codeList(codes, testid) {
  return el('ol', { className: 'codes', testid }, codes.map((c) => el('li', { text: c })));
}

/** A message line under a form, for what is happening and what went wrong. */
function formNote(testid) {
  return el('p', { className: 'form-note', testid, role: 'status', 'aria-live': 'polite' });
}

/** Run a form's action: `pending` under the form while it runs, then the
 * error there in plain words (and in the status bar), or nothing. */
async function runWithNote(app, note, pending, action) {
  note.dataset.kind = 'info';
  note.textContent = pending;
  await app.run(async () => {
    try {
      await action();
      note.textContent = '';
    } catch (error) {
      note.dataset.kind = 'error';
      note.textContent = error.message;
      throw error;
    }
  });
}

/** One place for success and error messages in the app shell. */
class StatusBar {
  constructor(node) {
    this.node = node;
  }

  pending() {
    this.show('', 'pending');
  }

  success(message) {
    this.show(message, 'success');
  }

  error(message) {
    this.show(message, 'error');
  }

  show(message, kind) {
    this.node.textContent = message;
    this.node.dataset.kind = kind;
  }
}

/**
 * A small popup at the bottom of the screen. "Changes Saved" closes by
 * itself; an error stays until it is closed, so it is not missed.
 */
class Toast {
  constructor() {
    this.node = el('div', { className: 'toast', testid: 'toast', role: 'status', 'aria-live': 'polite', hidden: true });
    document.body.append(this.node);
  }

  saved() {
    this.show('Changes Saved', 'success', 2000);
  }

  failed(message) {
    this.show(message, 'error', 0);
  }

  show(message, kind, closeAfter) {
    clearTimeout(this.timer);
    this.node.dataset.kind = kind;
    const parts = [el('span', { testid: 'toast-text', text: message })];
    if (kind === 'error') {
      parts.push(el('button', {
        type: 'button', className: 'ghost toast-close', testid: 'toast-close', text: '✕', 'aria-label': 'Close',
        onclick: () => this.hide(),
      }));
    }
    this.node.replaceChildren(...parts);
    this.node.hidden = false;
    if (closeAfter) this.timer = setTimeout(() => this.hide(), closeAfter);
  }

  hide() {
    clearTimeout(this.timer);
    this.node.hidden = true;
  }
}

/** Is this the click of a Save button ("Save", "Save login times", ...)? */
function isSaveButton(node) {
  const button = node && node.closest && node.closest('button');
  return Boolean(button) && /^save\b/i.test(button.textContent.trim());
}

window.ui = { el, svg, field, section, formatTime, groupSecret, codeList, StatusBar, Toast, ROLE_RANK };
