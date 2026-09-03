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

// jsdom does not implement ResizeObserver. Any directive that measures its own element
// needs it, and a test that does not drive a resize still needs the constructor to exist.
// A spec that wants to trigger a callback replaces this with its own stub.
if (!('ResizeObserver' in globalThis)) {
  Object.defineProperty(globalThis, 'ResizeObserver', {
    writable: true,
    value: class {
      observe(): void {}
      unobserve(): void {}
      disconnect(): void {}
    },
  });
}

