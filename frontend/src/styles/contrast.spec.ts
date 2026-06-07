/**
 * Deterministischer Farbkontrast-Test der CD-Tokens (T-43, requirements N3 —
 * WCAG 2.1 AA, Erfolgskriterien 1.4.3 Text und 1.4.11 Non-Text).
 *
 * Hintergrund: axe kann `color-contrast` in jsdom nicht berechnen (kein Layout).
 * Statt eines Browser-Tests parsen wir `tokens.scss`, lösen die Semantic-Tokens
 * (`--color-*`) pro Theme über die Primitive (`--c-*`) auf und prüfen die
 * Vordergrund/Hintergrund-Rollenpaare gegen die WCAG-Schwellen. So schlägt CI
 * an, sobald jemand ein Token unter den AA-Schwellwert ändert — ohne Browser.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const TOKENS = readFileSync(join(__dirname, 'tokens.scss'), 'utf8');

// --- WCAG-Kontrastberechnung (sRGB → relative Luminanz) ---------------------
function channel(c: number): number {
  const s = c / 255;
  return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}
function luminance(hex: string): number {
  const h = hex.replace('#', '');
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}
function ratio(a: string, b: string): number {
  const la = luminance(a);
  const lb = luminance(b);
  const [hi, lo] = la > lb ? [la, lb] : [lb, la];
  return (hi + 0.05) / (lo + 0.05);
}

// --- tokens.scss parsen ------------------------------------------------------
/** Alle Primitive `--c-*: #hex;` (theme-unabhängig, eindeutige Namen). */
function parsePrimitives(): Record<string, string> {
  const map: Record<string, string> = {};
  for (const m of TOKENS.matchAll(/(--c-[\w-]+):\s*(#[0-9a-fA-F]{6})\s*;/g)) {
    map[m[1]] = m[2];
  }
  return map;
}

const PRIMITIVES = parsePrimitives();

/** Löst einen Token-Wert (`#hex` oder `var(--c-…)`) zu einem #hex auf. */
function resolve(value: string): string {
  const v = value.trim();
  if (v.startsWith('#')) return v;
  const varMatch = v.match(/var\((--[\w-]+)\)/);
  if (varMatch) {
    const ref = PRIMITIVES[varMatch[1]];
    if (!ref) throw new Error(`Unaufgelöste Token-Referenz: ${varMatch[1]}`);
    return ref;
  }
  throw new Error(`Unerwarteter Token-Wert: ${value}`);
}

/** Semantic-Block für ein Theme aus tokens.scss ausschneiden + Map bauen. */
function parseSemantic(theme: 'light' | 'dark'): Record<string, string> {
  const darkIdx = TOKENS.indexOf("data-theme='dark'");
  const lightIdx = TOKENS.indexOf("data-theme='light'");
  const block =
    theme === 'light' ? TOKENS.slice(lightIdx, darkIdx) : TOKENS.slice(darkIdx);
  const map: Record<string, string> = {};
  for (const m of block.matchAll(/(--color-[\w-]+):\s*([^;]+);/g)) {
    map[m[1]] = resolve(m[2]);
  }
  return map;
}

const LIGHT = parseSemantic('light');
const DARK = parseSemantic('dark');

// --- Rollenpaare -------------------------------------------------------------
const AA_TEXT = 4.5; // 1.4.3 normaler Text
const AA_NONTEXT = 3.0; // 1.4.11 UI-Komponenten / Fokus / Grenzen

interface Pair {
  name: string;
  fg: string;
  bg: string;
  min: number;
}

function textPairs(t: Record<string, string>): Pair[] {
  const p = (name: string, fg: string, bg: string, min = AA_TEXT): Pair => ({
    name,
    fg: t[fg],
    bg: t[bg],
    min,
  });
  return [
    p('text / bg', '--color-text', '--color-bg'),
    p('text / surface', '--color-text', '--color-surface'),
    p('text / bg-elevated', '--color-text', '--color-bg-elevated'),
    p('text / surface-sunken', '--color-text', '--color-surface-sunken'),
    p('text-muted / bg', '--color-text-muted', '--color-bg'),
    p('text-muted / surface', '--color-text-muted', '--color-surface'),
    p('on-primary / primary', '--color-on-primary', '--color-primary'),
    p('primary (link) / bg', '--color-primary', '--color-bg'),
    p('primary (link) / surface', '--color-primary', '--color-surface'),
    p('success / surface', '--color-success', '--color-surface'),
    p('warning / surface', '--color-warning', '--color-surface'),
    p('danger / surface', '--color-danger', '--color-surface'),
    p('info / surface', '--color-info', '--color-surface'),
    // Non-Text (1.4.11): Fokus-Ring + Control-Rahmen
    p('focus-ring / bg', '--color-focus-ring', '--color-bg', AA_NONTEXT),
    p('focus-ring / surface', '--color-focus-ring', '--color-surface', AA_NONTEXT),
    p('border-strong / surface', '--color-border-strong', '--color-surface', AA_NONTEXT),
    p('border-strong / bg', '--color-border-strong', '--color-bg', AA_NONTEXT),
  ];
}

describe('CD-Token-Kontraste (WCAG 2.1 AA)', () => {
  it('parst Primitive und Semantic-Tokens', () => {
    expect(Object.keys(PRIMITIVES).length).toBeGreaterThan(10);
    expect(LIGHT['--color-text']).toMatch(/^#/);
    expect(DARK['--color-text']).toMatch(/^#/);
    expect(LIGHT['--color-text-muted']).not.toBe(DARK['--color-text-muted']);
  });

  for (const [theme, tokens] of [
    ['light', LIGHT],
    ['dark', DARK],
  ] as const) {
    describe(`Theme: ${theme}`, () => {
      for (const pair of textPairs(tokens)) {
        it(`${pair.name} ≥ ${pair.min}:1`, () => {
          expect(pair.fg).toBeDefined();
          expect(pair.bg).toBeDefined();
          const r = ratio(pair.fg, pair.bg);
          // Hilfreiche Diagnose bei Verstoß.
          expect({ pair: pair.name, fg: pair.fg, bg: pair.bg, ratio: +r.toFixed(2) }).toMatchObject({
            ratio: expect.any(Number),
          });
          expect(r).toBeGreaterThanOrEqual(pair.min);
        });
      }
    });
  }
});
