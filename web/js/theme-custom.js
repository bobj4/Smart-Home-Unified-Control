/**
 * Colour themes. A named theme is a data-theme attribute styled in app.css;
 * "custom" builds the whole palette from one chosen colour (the colour
 * wheel in Settings > My account) on a dark or light base.
 */

const THEMES = ['light', 'dark', 'red', 'violet'];
const CUSTOM_VARS = ['--bg', '--surface', '--surface-2', '--text', '--muted', '--border', '--accent', '--accent-fg', '--accent-text', '--on', '--on-text', '--danger', '--success', '--shadow'];

function hexToHsl(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  if (max === min) return [0, 0, l * 100];
  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  const h = max === r ? (g - b) / d + (g < b ? 6 : 0) : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [h * 60, s * 100, l * 100];
}

/** Black or white text, whichever reads better on the colour. */
function textOn(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.18 ? '#111111' : '#ffffff';
}

/** Whether a colour is dark (light text reads better on it). */
function isDark(hex) {
  return textOn(hex) === '#ffffff';
}

/** The page's own colours: the background (dark, light or a chosen colour,
 * the primary colour) and what goes on it. */
function backgroundPalette(accent, base) {
  if (base.startsWith('#')) {
    const [h, s, l] = hexToHsl(base);
    const dark = isDark(base);
    const tone = (by) => `hsl(${Math.round(h)} ${Math.round(s)}% ${Math.round(Math.min(100, Math.max(0, l + (dark ? by : -by))))}%)`;
    const ink = Math.min(s, 25);
    return {
      dark,
      '--bg': base,
      '--surface': tone(5),
      '--surface-2': tone(10),
      '--border': tone(20),
      '--text': `hsl(${Math.round(h)} ${Math.round(ink)}% ${dark ? 95 : 10}%)`,
      '--muted': `hsl(${Math.round(h)} ${Math.round(ink * 0.6)}% ${dark ? 70 : 36}%)`,
    };
  }
  const [h, s] = hexToHsl(accent);
  const tint = Math.min(s, 30);
  const hsl = (sat, light) => `hsl(${Math.round(h)} ${Math.round(sat)}% ${Math.round(light)}%)`;
  const dark = base === 'dark';
  return {
    dark,
    '--bg': dark ? hsl(tint, 5) : hsl(tint, 96),
    '--surface': dark ? hsl(tint, 9) : '#ffffff',
    '--surface-2': dark ? hsl(tint, 13) : hsl(tint, 93),
    '--text': dark ? hsl(tint, 95) : hsl(tint, 10),
    '--muted': dark ? hsl(tint * 0.6, 68) : hsl(tint * 0.6, 38),
    '--border': dark ? hsl(tint, 21) : hsl(tint, 86),
  };
}

/** Every colour of the page from the accent (secondary) colour and the
 * background (primary): dark, light or a colour of one's own. */
function customPalette(accent, base) {
  const [, s, l] = hexToHsl(accent);
  const { dark, ...background } = backgroundPalette(accent, base);
  const [h] = hexToHsl(accent);
  const hsl = (sat, light) => `hsl(${Math.round(h)} ${Math.round(sat)}% ${Math.round(light)}%)`;
  return {
    ...background,
    '--accent': accent,
    // Accent-coloured text: lighter on dark, darker on light, so it reads.
    '--accent-fg': dark ? hsl(s, Math.max(l, 66)) : hsl(s, Math.min(l, 40)),
    '--accent-text': textOn(accent),
    '--on': accent,
    '--on-text': textOn(accent),
    '--danger': dark ? '#ff6b6b' : '#c62828',
    '--success': dark ? '#4cc06f' : '#1b7f3b',
    '--shadow': dark ? 'none' : '0 1px 2px rgba(16, 24, 40, 0.06), 0 1px 3px rgba(16, 24, 40, 0.08)',
  };
}

/** Put a theme on the page: a name from THEMES, "custom" with its colours, or the device's own. */
function applyThemeTo(root, theme, custom) {
  CUSTOM_VARS.forEach((name) => root.style.removeProperty(name));
  if (theme === 'custom' && custom) {
    const dark = custom.base.startsWith('#') ? isDark(custom.base) : custom.base === 'dark';
    root.dataset.theme = `custom-${dark ? 'dark' : 'light'}`;
    Object.entries(customPalette(custom.accent, custom.base)).forEach(([name, value]) => root.style.setProperty(name, value));
  } else if (THEMES.includes(theme)) {
    root.dataset.theme = theme;
  } else {
    delete root.dataset.theme;
  }
  // The phone's status bar follows the page background.
  const meta = document.querySelector('meta[name="theme-color"]');
  const bg = getComputedStyle(root).getPropertyValue('--bg').trim();
  if (meta && bg) meta.setAttribute('content', bg);
}

/** A colour button that shows its colour, with the colour's code beside it. */
function colourPicker(testid, label, value, onInput) {
  const input = el('input', { type: 'color', testid, value, 'aria-label': label, className: 'swatch' });
  const code = el('span', { className: 'muted swatch-code', text: value });
  input.addEventListener('input', () => { code.textContent = input.value; onInput(); });
  return { input, element: el('label', { className: 'swatch-field' }, [el('span', { text: label }), el('span', { className: 'swatch-row' }, [input, code])]) };
}

/** My account > Appearance. Custom: an accent (secondary) colour and a
 * background (primary): dark, light, or a colour of one's own. */
function appearanceBox(app) {
  const account = app.account;
  const select = el('select', { testid: 'theme-select', 'aria-label': 'Appearance' }, [
    ['system', 'Device Theme'], ['light', 'Light'], ['dark', 'Dark'], ['red', 'Red'], ['violet', 'Purple'], ['custom', 'Custom'],
  ].map(([value, text]) => el('option', { value, text })));
  select.value = account.theme || 'system';
  const last = account.theme_custom || { accent: '#1f6feb', base: 'dark' };
  const ownBase = last.base.startsWith('#');
  const chip = el('span', { className: 'theme-chip', testid: 'theme-chip', 'aria-hidden': 'true' });
  const current = () => ({ accent: accent.input.value, base: base.value === 'own' ? background.input.value : base.value });
  const preview = () => {
    const chosen = current();
    background.element.hidden = base.value !== 'own';
    chip.style.setProperty('--chip-accent', chosen.accent);
    chip.style.setProperty('--chip-bg', chosen.base.startsWith('#') ? chosen.base : (chosen.base === 'dark' ? '#16181d' : '#f4f5f7'));
    if (select.value === 'custom') app.applyTheme('custom', chosen);
  };
  const accent = colourPicker('theme-colour', 'Accent colour', last.accent, preview);
  const background = colourPicker('theme-background', 'Background colour', ownBase ? last.base : '#202124', preview);
  const base = el('select', { testid: 'theme-base', 'aria-label': 'Background' },
    [['dark', 'Dark'], ['light', 'Light'], ['own', 'My own colour']].map(([value, text]) => el('option', { value, text })));
  base.value = ownBase ? 'own' : last.base;
  base.addEventListener('change', preview);
  const save = (theme, custom) => app.run(async () => {
    const saved = await app.api.setPreferences(custom ? { theme, custom } : { theme });
    account.theme = saved.theme;
    if (saved.custom) account.theme_custom = saved.custom;
    app.applyTheme(saved.theme, account.theme_custom);
    app.status.success('Appearance saved.');
  });
  const customBox = el('div', { className: 'row', testid: 'theme-custom' }, [
    accent.element, field('Background', base), background.element,
    el('button', { type: 'button', testid: 'theme-custom-save', text: 'Save colours', onclick: () => save('custom', current()) }),
  ]);
  const show = () => { customBox.hidden = select.value !== 'custom'; chip.hidden = select.value !== 'custom'; };
  select.addEventListener('change', () => {
    show();
    if (select.value === 'custom') preview();
    else save(select.value);
  });
  show();
  preview();
  return el('div', { className: 'subpanel' }, [
    el('h3', { text: 'Appearance' }),
    el('div', { className: 'row' }, [field('Colours', select), chip]),
    customBox,
  ]);
}
