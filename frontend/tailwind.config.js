/**
 * Tailwind configuration (#tailwind). The goal is additive utilities with no visual change.
 *
 * 1. `preflight: false` turns off the base reset. The reset would change h1, button, ul and
 *    other elements globally.
 * 2. All scales (spacing, colors, radii, font, shadow, z-index) alias the existing design
 *    tokens from `src/styles/tokens.scss`. So `gap-5` gives exactly `var(--space-5)`, which
 *    is 1.5rem and identical to the previous SCSS rule. A migration from `var(--space-5)` to
 *    `gap-5` therefore stays pixel exact.
 *
 * Above step 4 the project spacing scale differs from the Tailwind defaults. `--space-5` is
 * 1.5rem, not 1.25rem. For this reason the config maps the scale explicitly.
 *
 * @type {import('tailwindcss').Config}
 */
const sp = (n) => `var(--space-${n})`;

module.exports = {
  // Scan the HTML and the inline or external component templates. The list includes the
  // separate UI-kit library (a submodule) so that Tailwind also generates its utility classes.
  content: [
    './src/**/*.{html,ts}',
    './vendor/ui-kit/src/**/*.{html,ts}',
    './vendor/ui-kit/markdown-editor/**/*.{html,ts}',
  ],
  corePlugins: {
    preflight: false,
  },
  theme: {
    // Replace the theme completely instead of extending it. Only token values must exist.
    // Accidental Tailwind defaults would differ from the design system.
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
    // Semantic tokens. The names keep `bg-surface`, `text-muted`, `border-line` and
    // `text-primary` readable.
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
