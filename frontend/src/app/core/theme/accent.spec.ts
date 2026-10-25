import {
  ACCENT_PROPERTIES,
  DEFAULT_ACCENT,
  accentPalette,
  applyAccent,
  contrast,
  ensureContrast,
  normalizeHex,
} from './accent';

/** The surfaces of `tokens.scss` that the accent text sits on, per theme. */
const LIGHT_SURFACES = ['#ffffff', '#f6f7f5', '#f0f2ef', '#e6e9e5'];
const DARK_SURFACES = ['#171a18', '#101211', '#1d201e', '#262a27'];

const PICKS = ['#ffff00', '#00ffff', '#ff0000', '#0000ff', '#0075bf', '#ce1625', '#f18700', '#e6c619', '#7a4bc2', '#000000', '#ffffff', '#808080', '#00ff00', '#ff00ff'];

describe('accent palette', () => {
  it('gives the built-in values for the built-in accent', () => {
    const p = accentPalette(DEFAULT_ACCENT);
    expect(p['--c-accent']).toBe('#72a384');
    expect(p['--c-on-accent']).toBe('#0b1d12');
    expect(p['--c-light-pt']).toBe('#3c6a4d');
    expect(p['--c-dark-pt']).toBe('#8dbb9d');
    expect(Object.keys(p).sort()).toEqual([...ACCENT_PROPERTIES].sort());
  });

  /** A slightly different green walks the same path as the built-in one. */
  it('keeps the derivation close to the built-in values for the built-in hue', () => {
    const p = accentPalette('#72a385');
    expect(contrast(p['--c-light-pt'], '#3c6a4d')).toBeLessThan(1.1);
    expect(contrast(p['--c-dark-sel'], '#243129')).toBeLessThan(1.1);
  });

  it.each(PICKS)('keeps AA text contrast in both themes for %s', (pick) => {
    const p = accentPalette(pick);
    for (const step of ['pt', 'pt-hover', 'pt-active']) {
      for (const s of [...LIGHT_SURFACES, p['--c-light-sel']]) {
        expect(contrast(p[`--c-light-${step}`], s)).toBeGreaterThanOrEqual(4.5);
      }
      for (const s of [...DARK_SURFACES, p['--c-dark-sel']]) {
        expect(contrast(p[`--c-dark-${step}`], s)).toBeGreaterThanOrEqual(4.5);
      }
    }
    expect(contrast(p['--c-light-onpc'], p['--c-light-pc'])).toBeGreaterThanOrEqual(4.5);
    expect(contrast(p['--c-dark-onpc'], p['--c-dark-pc'])).toBeGreaterThanOrEqual(4.5);
    expect(contrast(p['--c-light-onsel'], p['--c-light-sel'])).toBeGreaterThanOrEqual(4.5);
    expect(contrast(p['--c-dark-onsel'], p['--c-dark-sel'])).toBeGreaterThanOrEqual(4.5);
    expect(p['--c-accent']).toBe(pick);
    for (const v of Object.values(p)) expect(v).toMatch(/^#[0-9a-f]{6}$/);
  });

  it('puts white text on a dark fill and the dark tint on a light one', () => {
    expect(accentPalette('#003366')['--c-on-accent']).toBe('#ffffff');
    expect(accentPalette('#e6c619')['--c-on-accent']).not.toBe('#ffffff');
  });

  it('turns the hue towards the pick', () => {
    const p = accentPalette('#0075bf');
    const [r, , b] = [1, 3, 5].map((i) => parseInt(p['--c-light-pt'].slice(i, i + 2), 16));
    expect(b).toBeGreaterThan(r);
  });

  it('moves a step darker on light surfaces and lighter on dark ones until it passes', () => {
    const light = ensureContrast('#9ab0a2', ['#ffffff'], false);
    expect(contrast(light, '#ffffff')).toBeGreaterThanOrEqual(4.5);
    const dark = ensureContrast('#3c4a40', ['#101211'], true);
    expect(contrast(dark, '#101211')).toBeGreaterThanOrEqual(4.5);
    expect(ensureContrast('#000000', ['#ffffff'], false)).toBe('#000000');
  });

  it('normalizes the hex value', () => {
    expect(normalizeHex(' #AABBCC ')).toBe('#aabbcc');
    expect(normalizeHex('#abc')).toBeNull();
    expect(normalizeHex(null)).toBeNull();
    expect(accentPalette('nonsense')['--c-accent']).toBe(DEFAULT_ACCENT);
  });

  it('writes the palette on the root and removes it again', () => {
    const root = document.createElement('div');
    applyAccent('#0075BF', root);
    expect(root.style.getPropertyValue('--c-accent')).toBe('#0075bf');
    expect(root.style.getPropertyValue('--c-dark-pt')).toMatch(/^#/);
    applyAccent(DEFAULT_ACCENT, root);
    expect(root.style.getPropertyValue('--c-accent')).toBe('');
    applyAccent('#0075bf', root);
    applyAccent(null, root);
    for (const name of ACCENT_PROPERTIES) expect(root.style.getPropertyValue(name)).toBe('');
  });
});
