/**
 * a11y test helper (WCAG 2.1 AA).
 *
 * The helper wraps `jest-axe` with a project-wide configuration and scans a rendered DOM
 * node. It returns the axe result. The caller checks that result with
 * `toHaveNoViolations()`, a matcher that `setup-jest.ts` registers.
 *
 * Color contrast: jsdom has no layout and no resolved computed styles, so axe cannot
 * compute `color-contrast` and reports it as "incomplete". This file disables the rule.
 * `styles/contrast.spec.ts` checks the contrasts against the CD tokens instead, with a
 * deterministic result.
 */
import { axe, type AxeResults, type JestAxeConfigureOptions } from 'jest-axe';

export const A11Y_RULES: JestAxeConfigureOptions = {
  rules: {
    // jsdom cannot compute this rule. The token test covers it instead.
    'color-contrast': { enabled: false },
    // A single component renders without a <main> landmark wrapper. The shell view
    // scan checks the landmark structure, not each fragment.
    region: { enabled: false },
  },
};

/**
 * Run an axe scan over a DOM node or over the fixture root.
 *
 * For a full-view scan of the shell with its landmarks, enable `region` again through
 * `extraRules`.
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
