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

/** Every colour of the page from one accent colour and a base. */
function customPalette(accent, base) {
  const [h, s, l] = hexToHsl(accent);
  const tint = Math.min(s, 30);
  const hsl = (sat, light) => `hsl(${Math.round(h)} ${Math.round(sat)}% ${Math.round(light)}%)`;
  const dark = base === 'dark';
  return {
    '--bg': dark ? hsl(tint, 5) : hsl(tint, 96),
    '--surface': dark ? hsl(tint, 9) : '#ffffff',
    '--surface-2': dark ? hsl(tint, 13) : hsl(tint, 93),
    '--text': dark ? hsl(tint, 95) : hsl(tint, 10),
    '--muted': dark ? hsl(tint * 0.6, 68) : hsl(tint * 0.6, 38),
    '--border': dark ? hsl(tint, 21) : hsl(tint, 86),
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
    root.dataset.theme = `custom-${custom.base}`;
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
