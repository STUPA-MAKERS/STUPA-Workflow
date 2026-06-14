/**
 * Tailwind-Konfiguration (#tailwind). Ziel: **additive Utilities ohne jede optische
 * Änderung**. Dafür:
 *
 * 1. `preflight: false` — kein Base-Reset (würde h1/button/ul/… global verändern).
 * 2. Alle Skalen (Spacing/Farben/Radien/Schrift/Schatten/z-Index) sind **Aliase auf
 *    die bestehenden Design-Tokens** (`var(--…)` aus `src/styles/tokens.scss`). So
 *    erzeugt z. B. `gap-5` exakt `var(--space-5)` (1.5rem) — identisch zur bisherigen
 *    SCSS-Regel. Migration `var(--space-5)` → `gap-5` ist damit pixelgenau.
 *
 * Die Projekt-Spacing-Skala weicht oberhalb von 4 von Tailwind-Defaults ab
 * (`--space-5` = 1.5rem statt 1.25rem) — deshalb wird sie **explizit** gemappt.
 *
 * @type {import('tailwindcss').Config}
 */
const sp = (n) => `var(--space-${n})`;

module.exports = {
  // HTML + inline-/externe Komponenten-Templates scannen.
  content: ['./src/**/*.{html,ts}'],
  corePlugins: {
    preflight: false,
  },
  theme: {
    // Vollständig ersetzen (nicht extend), damit NUR Token-Werte existieren — keine
    // versehentlichen Tailwind-Defaults, die vom Design-System abweichen.
    spacing: {
      0: '0',
      px: '1px',
      1: sp(1),
      2: sp(2),
      3: sp(3),
      4: sp(4),
      5: sp(5),
      6: sp(6),
      7: sp(7),
      8: sp(8),
      10: sp(10),
      12: sp(12),
    },
    borderRadius: {
      none: '0',
      sm: 'var(--radius-sm)',
      DEFAULT: 'var(--radius-md)',
      md: 'var(--radius-md)',
      lg: 'var(--radius-lg)',
      xl: 'var(--radius-xl)',
      pill: 'var(--radius-pill)',
      full: 'var(--radius-pill)',
    },
    borderWidth: {
      DEFAULT: 'var(--border-width)',
      0: '0',
      2: '2px',
    },
    fontSize: {
      xs: 'var(--fs-xs)',
      sm: 'var(--fs-sm)',
      base: 'var(--fs-md)',
      md: 'var(--fs-md)',
      lg: 'var(--fs-lg)',
      xl: 'var(--fs-xl)',
      '2xl': 'var(--fs-2xl)',
      '3xl': 'var(--fs-3xl)',
    },
    fontWeight: {
      normal: 'var(--fw-regular)',
      regular: 'var(--fw-regular)',
      medium: 'var(--fw-medium)',
      semibold: 'var(--fw-semibold)',
      bold: 'var(--fw-bold)',
    },
    boxShadow: {
      none: 'none',
      sm: 'var(--shadow-sm)',
      DEFAULT: 'var(--shadow-md)',
      md: 'var(--shadow-md)',
      lg: 'var(--shadow-lg)',
    },
    zIndex: {
      auto: 'auto',
      0: '0',
      dropdown: 'var(--z-dropdown)',
      sticky: 'var(--z-sticky)',
      dialog: 'var(--z-dialog)',
      toast: 'var(--z-toast)',
    },
    // Farben = Semantik-Tokens. Namen so gewählt, dass `bg-surface`, `text-muted`,
    // `border-line`, `text-primary` … lesbar sind.
    colors: {
      transparent: 'transparent',
      current: 'currentColor',
      inherit: 'inherit',
      bg: 'var(--color-bg)',
      'bg-elevated': 'var(--color-bg-elevated)',
      surface: 'var(--color-surface)',
      'surface-sunken': 'var(--color-surface-sunken)',
      line: 'var(--color-border)',
      'line-strong': 'var(--color-border-strong)',
      text: 'var(--color-text)',
      muted: 'var(--color-text-muted)',
      inverse: 'var(--color-text-inverse)',
      primary: 'var(--color-primary)',
      'primary-hover': 'var(--color-primary-hover)',
      'primary-active': 'var(--color-primary-active)',
      'primary-subtle': 'var(--color-primary-subtle)',
      'on-primary': 'var(--color-on-primary)',
      accent: 'var(--color-accent)',
      success: 'var(--color-success)',
      'success-subtle': 'var(--color-success-subtle)',
      warning: 'var(--color-warning)',
      'warning-subtle': 'var(--color-warning-subtle)',
      danger: 'var(--color-danger)',
      'danger-subtle': 'var(--color-danger-subtle)',
      info: 'var(--color-info)',
      'info-subtle': 'var(--color-info-subtle)',
    },
    extend: {
      fontFamily: {
        mono: 'var(--font-mono, monospace)',
      },
    },
  },
  plugins: [],
};
