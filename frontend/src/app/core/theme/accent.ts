/**
 * The configurable accent colour (`branding.accentColor`).
 *
 * The ui-kit tokens carry one green: the fill `--c-accent` and, per theme, the accent as
 * text, its hover and active steps, the container, the selected row and the text on
 * them. An admin picks one colour; this file derives every one of those primitives from
 * it and writes them on `<html>`, so the semantic tokens (`--color-primary`, …) follow in
 * both themes without a change to a stylesheet.
 *
 * The derivation works in OKLCH. Each primitive keeps the perceived lightness of its
 * built-in value, turns its hue by the hue difference of the picked colour to the built-in
 * accent and scales its chroma by their chroma ratio. Lightness carries the contrast, so
 * the derived palette keeps the contrast of the built-in one. A colour outside sRGB loses
 * chroma until it fits. After that, each text step moves its lightness until it reaches
 * 4.5:1 on every surface it sits on, because a very saturated hue can still fall short.
 * The text on the fill is the derived dark tint or white, whichever gives more contrast.
 */

/** The built-in accent of the design system (`--c-accent` in `tokens.scss`). */
export const DEFAULT_ACCENT = '#72a384';

/** The AA contrast for normal text. */
const AA = 4.5;

/** A built-in primitive: its CSS name and its value in `tokens.scss`. */
interface Primitive {
  readonly name: string;
  readonly value: string;
}

/** The primitives that carry the accent hue, with their built-in values. */
const PRIMITIVES: readonly Primitive[] = [
  { name: '--c-light-pt', value: '#3c6a4d' },
  { name: '--c-light-pt-hover', value: '#2f5a3f' },
  { name: '--c-light-pt-active', value: '#24482f' },
  { name: '--c-light-pc', value: '#d6eadc' },
  { name: '--c-light-onpc', value: '#0f2e1b' },
  { name: '--c-light-sel', value: '#e1eee5' },
  { name: '--c-light-onsel', value: '#11301d' },
  { name: '--c-dark-pt', value: '#8dbb9d' },
  { name: '--c-dark-pt-hover', value: '#a6cdb3' },
  { name: '--c-dark-pt-active', value: '#c3e3cd' },
  { name: '--c-dark-pc', value: '#21362a' },
  { name: '--c-dark-onpc', value: '#c3e3cd' },
  { name: '--c-dark-sel', value: '#243129' },
  { name: '--c-dark-onsel', value: '#e2efe6' },
];

/** The built-in text on the fill, a dark tint of the accent. */
const ON_ACCENT = '#0b1d12';

/** Every property that {@link applyAccent} writes, so a reset removes all of them. */
export const ACCENT_PROPERTIES: readonly string[] = [
  '--c-accent',
  '--c-on-accent',
  ...PRIMITIVES.map((p) => p.name),
];

/**
 * The surfaces a text step sits on, per theme: the cards, the page, the sunken and the
 * raised surface (`--c-light-c1` … of `tokens.scss`). The selected row and the container
 * join from the derived palette.
 */
const SURFACES = {
  light: ['#ffffff', '#f6f7f5', '#f0f2ef', '#e6e9e5'],
  dark: ['#171a18', '#101211', '#1d201e', '#262a27'],
} as const;

type Rgb = readonly [number, number, number];
type Oklch = readonly [number, number, number];

/** `#rrggbb` in any case, or null for anything else. */
export function normalizeHex(value: string | null | undefined): string | null {
  const v = (value ?? '').trim().toLowerCase();
  return /^#[0-9a-f]{6}$/.test(v) ? v : null;
}

function hexToRgb(hex: string): Rgb {
  const n = parseInt(hex.slice(1), 16);
  return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
}

function rgbToHex(rgb: Rgb): string {
  return (
    '#' +
    rgb
      .map((c) =>
        Math.round(Math.min(1, Math.max(0, c)) * 255)
          .toString(16)
          .padStart(2, '0'),
      )
      .join('')
  );
}

function toLinear(c: number): number {
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

function fromLinear(c: number): number {
  return c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055;
}

/** sRGB → OKLCH (L 0..1, C, H in degrees). */
function rgbToOklch(rgb: Rgb): Oklch {
  const [r, g, b] = rgb.map(toLinear) as unknown as Rgb;
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  const L = 0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s;
  const a = 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s;
  const bb = 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s;
  const H = (Math.atan2(bb, a) * 180) / Math.PI;
  return [L, Math.hypot(a, bb), H < 0 ? H + 360 : H];
}

/** OKLCH → sRGB, without clipping (a channel may leave 0..1). */
function oklchToRgb([L, C, H]: Oklch): Rgb {
  const hr = (H * Math.PI) / 180;
  const a = C * Math.cos(hr);
  const b = C * Math.sin(hr);
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  return [
    fromLinear(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
    fromLinear(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
    fromLinear(-0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s),
  ];
}

function inGamut(rgb: Rgb): boolean {
  return rgb.every((c) => c >= -0.0005 && c <= 1.0005);
}

/** OKLCH → hex. Reduces the chroma until the colour fits sRGB. */
function oklchToHex([L, C, H]: Oklch): string {
  if (inGamut(oklchToRgb([L, C, H]))) return rgbToHex(oklchToRgb([L, C, H]));
  let lo = 0;
  let hi = C;
  for (let i = 0; i < 20; i++) {
    const mid = (lo + hi) / 2;
    if (inGamut(oklchToRgb([L, mid, H]))) lo = mid;
    else hi = mid;
  }
  return rgbToHex(oklchToRgb([L, lo, H]));
}

/** The relative luminance of WCAG 2. */
function luminance(hex: string): number {
  const [r, g, b] = hexToRgb(hex).map(toLinear) as unknown as Rgb;
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** The WCAG 2 contrast ratio of two colours. */
export function contrast(a: string, b: string): number {
  const la = luminance(a);
  const lb = luminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

/**
 * Move the lightness of `hex` (darker on light surfaces, lighter on dark ones) until it
 * has AA contrast on every one of `surfaces`. The hue and the chroma stay.
 */
export function ensureContrast(hex: string, surfaces: readonly string[], dark: boolean): string {
  const [L0, C, H] = rgbToOklch(hexToRgb(hex));
  const step = dark ? 0.01 : -0.01;
  let out = hex;
  // At L 0 or 1 the colour is black or white, which passes on every surface of a theme.
  for (let i = 1; i <= 100 && !surfaces.every((s) => contrast(out, s) >= AA); i++) {
    out = oklchToHex([Math.min(1, Math.max(0, L0 + i * step)), C, H]);
  }
  return out;
}

/** The hue difference in degrees, in -180..180. */
function hueDelta(from: number, to: number): number {
  return ((to - from + 540) % 360) - 180;
}

/**
 * Every accent primitive for one accent colour, by CSS name. The built-in accent gives
 * the built-in values. A grey (no chroma) gives grey steps.
 */
export function accentPalette(accent: string): Record<string, string> {
  const hex = normalizeHex(accent) ?? DEFAULT_ACCENT;
  if (hex === DEFAULT_ACCENT) {
    return Object.fromEntries([
      ['--c-accent', DEFAULT_ACCENT],
      ['--c-on-accent', ON_ACCENT],
      ...PRIMITIVES.map((p) => [p.name, p.value]),
    ]);
  }
  const [, C0, H0] = rgbToOklch(hexToRgb(DEFAULT_ACCENT));
  const [, C, H] = rgbToOklch(hexToRgb(hex));
  // A grey has no chroma, so its steps turn grey. The cap keeps a neon pick usable.
  const ratio = Math.min(C / C0, 2);
  const turn = hueDelta(H0, H);
  const derive = (value: string): string => {
    const [Lt, Ct, Ht] = rgbToOklch(hexToRgb(value));
    return oklchToHex([Lt, Ct * ratio, (Ht + turn + 360) % 360]);
  };
  const out: Record<string, string> = {};
  for (const p of PRIMITIVES) out[p.name] = derive(p.value);

  for (const theme of ['light', 'dark'] as const) {
    const dark = theme === 'dark';
    const sel = out[`--c-${theme}-sel`];
    const pc = out[`--c-${theme}-pc`];
    const surfaces = [...SURFACES[theme], sel];
    for (const step of ['pt', 'pt-hover', 'pt-active']) {
      const name = `--c-${theme}-${step}`;
      out[name] = ensureContrast(out[name], surfaces, dark);
    }
    out[`--c-${theme}-onpc`] = ensureContrast(out[`--c-${theme}-onpc`], [pc], dark);
    out[`--c-${theme}-onsel`] = ensureContrast(out[`--c-${theme}-onsel`], [sel], dark);
  }

  out['--c-accent'] = hex;
  const tint = derive(ON_ACCENT);
  out['--c-on-accent'] = contrast(tint, hex) >= contrast('#ffffff', hex) ? tint : '#ffffff';
  return out;
}

/**
 * Write the palette of `accent` on `<html>`, or remove it for none or the built-in
 * accent, so the values of `tokens.scss` apply again.
 */
export function applyAccent(accent: string | null | undefined, root: HTMLElement = document.documentElement): void {
  const hex = normalizeHex(accent);
  if (!hex || hex === DEFAULT_ACCENT) {
    for (const name of ACCENT_PROPERTIES) root.style.removeProperty(name);
    return;
  }
  for (const [name, value] of Object.entries(accentPalette(hex))) root.style.setProperty(name, value);
}
