import '@testing-library/jest-dom';
import { setupZoneTestEnv } from 'jest-preset-angular/setup-env/zone';

setupZoneTestEnv();

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
