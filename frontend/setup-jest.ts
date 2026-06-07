import '@testing-library/jest-dom';
import { toHaveNoViolations } from 'jest-axe';
import { setupZoneTestEnv } from 'jest-preset-angular/setup-env/zone';

setupZoneTestEnv();

// a11y-Matcher (T-43) projektweit registrieren, damit `toHaveNoViolations()`
// in jeder Spec verfügbar ist.
expect.extend(toHaveNoViolations);

// jsdom reports `en-US`; the app's reference locale is German. Pin it so tests
// that exercise default-locale behaviour are deterministic (override per-test as
// needed).
Object.defineProperty(navigator, 'language', { value: 'de-DE', configurable: true });

// matchMedia is not implemented in jsdom — ThemeService relies on it.
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }),
});
