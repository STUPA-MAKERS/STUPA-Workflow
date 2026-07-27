import '@testing-library/jest-dom';
import { toHaveNoViolations } from 'jest-axe';
import { setupZoneTestEnv } from 'jest-preset-angular/setup-env/zone';

setupZoneTestEnv();

// Register the a11y matcher (T-43) for the whole project. Every spec can then call
// `toHaveNoViolations()`.
expect.extend(toHaveNoViolations);

// jsdom reports `en-US`. The reference locale of the app is German. Pin the locale to keep
// tests of the default-locale behavior deterministic. A single test can override it.
Object.defineProperty(navigator, 'language', { value: 'de-DE', configurable: true });

// jsdom does not implement matchMedia. ThemeService needs it.
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
