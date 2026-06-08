/**
 * a11y-Test-Helfer (T-43, requirements N3 — WCAG 2.1 AA).
 *
 * Kapselt `jest-axe` mit projektweiter Konfiguration und führt den axe-Scan
 * gegen einen gerenderten DOM-Knoten aus. Liefert das axe-Ergebnis zurück, das
 * der Aufrufer mit `toHaveNoViolations()` prüft (Matcher in `setup-jest.ts`
 * registriert).
 *
 * Hinweis Farbkontrast: axe kann `color-contrast` in jsdom nicht berechnen
 * (kein Layout/keine aufgelösten Computed-Styles) und meldet es als
 * „incomplete". Die Regel ist hier deaktiviert; Kontraste werden stattdessen
 * deterministisch in `styles/contrast.spec.ts` gegen die CD-Tokens geprüft.
 */
import { axe, type AxeResults, type JestAxeConfigureOptions } from 'jest-axe';

/** Standard-Regelkonfiguration für Unit-/Component-Scans in jsdom. */
export const A11Y_RULES: JestAxeConfigureOptions = {
  rules: {
    // In jsdom nicht berechenbar — separat über Token-Test abgedeckt.
    'color-contrast': { enabled: false },
    // Einzelkomponenten werden ohne <main>/Landmark-Wrapper gerendert; die
    // Landmark-Struktur wird im Shell-/View-Scan geprüft, nicht je Fragment.
    region: { enabled: false },
  },
};

/**
 * axe-Scan über einen DOM-Knoten (oder das Fixture-Root). Für Voll-View-Scans
 * (Shell mit Landmarks) `region` per `extraRules` wieder aktivieren.
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
