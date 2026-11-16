/**
 * Pieces of the device cards (devices.js): the types with a dial or a power
 * button, line icons, the temperature gauge and a light's tint.
 */

const TEMPERATURE_TYPES = new Set(['thermostat', 'water_heater']);
const POWER_TYPES = new Set(['light', 'plug', 'tv']);
// Simple line icons, 24x24.
const ICON_PATHS = {
  light: 'M9 18h6M10 21h4M12 3a6 6 0 0 0-4 10.5c.8.8 1 1.5 1 2.5h6c0-1 .2-1.7 1-2.5A6 6 0 0 0 12 3z',
  plug: 'M9 3v5M15 3v5M6 8h12v4a6 6 0 0 1-12 0zM12 18v3',
  tv: 'M3 6h18v11H3zM8 21h8M12 17v4',
  garage_door: 'M3 21V9l9-6 9 6v12M6 21V11h12v10M6 14h12M6 17h12',
  thermostat: 'M12 3a2 2 0 0 0-2 2v9.3a4 4 0 1 0 4 0V5a2 2 0 0 0-2-2zM12 9v7',
  water_heater: 'M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11z',
  sensor: 'M5 12a7 7 0 0 1 14 0M8 12a4 4 0 0 1 8 0M12 12v.01',
  camera: 'M3 7h4l2-3h6l2 3h4v12H3zM12 10a3 3 0 1 0 0 6 3 3 0 0 0 0-6z',
};

function icon(type) {
  return svg('svg', { viewBox: '0 0 24 24', className: 'icon', 'aria-hidden': 'true' }, [
    svg('path', { d: ICON_PATHS[type] || ICON_PATHS.sensor }),
  ]);
}

/** A 270-degree arc; the filled part shows where the target sits between the limits. */
function gauge(fraction, type) {
  const arc = 'M 26.1 93.9 A 48 48 0 1 1 93.9 93.9';
  const filled = Math.max(0, Math.min(1, fraction)) * 100;
  return svg('svg', { viewBox: '0 0 120 110', className: `gauge ${type}`, testid: 'temp-gauge', role: 'img', 'aria-label': 'Target temperature dial' }, [
    svg('path', { d: arc, className: 'gauge-track', pathLength: '100' }),
    svg('path', { d: arc, className: 'gauge-fill', pathLength: '100', 'stroke-dasharray': `${filled} 100` }),
  ]);
}

/** The color a light shows: its RGB color, or its color temperature as a tint. */
function lightColor(state) {
  if (state.color_mode === 'rgb' && state.color) return state.color;
  const kelvin = state.color_temp || 2700;
  const warm = [255, 166, 77];
  const cool = [214, 230, 255];
  const t = Math.max(0, Math.min(1, (kelvin - 2000) / 4500));
  const mix = warm.map((w, i) => Math.round(w + (cool[i] - w) * t));
  return `rgb(${mix.join(', ')})`;
}
