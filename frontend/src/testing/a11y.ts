/**
 * a11y test helper (WCAG 2.1 AA).
 *
 * Wraps `jest-axe` with project-wide configuration and runs the axe scan against a
 * rendered DOM node. Returns the axe result, which the caller checks with
 * `toHaveNoViolations()` (matcher registered in `setup-jest.ts`).
 *
 * Colour-contrast note: axe cannot compute `color-contrast` in jsdom (no layout /
 * no resolved computed styles) and reports it as "incomplete". The rule is disabled
 * here; contrasts are instead checked deterministically in `styles/contrast.spec.ts`
 * against the CD tokens.
 */
import { axe, type AxeResults, type JestAxeConfigureOptions } from 'jest-axe';

/** Default rule configuration for unit/component scans in jsdom. */
export const A11Y_RULES: JestAxeConfigureOptions = {
  rules: {
    // Not computable in jsdom — covered separately by the token test.
    'color-contrast': { enabled: false },
    // Single components render without a <main>/landmark wrapper; the landmark
    // structure is checked in the shell/view scan, not per fragment.
    region: { enabled: false },
  },
};

/**
 * axe scan over a DOM node (or the fixture root). For full-view scans (shell with
 * landmarks) re-enable `region` via `extraRules`.
 */
export function runAxe(
  target: Element | Document,
  extraRules?: JestAxeConfigureOptions,
): Promise<AxeResults> {
  return axe(target as Element, {
    ...A11Y_RULES,
    ...extraRules,
    rules: { ...A11Y_RULES.rules, ...extraRules?.rules },
  });
}
