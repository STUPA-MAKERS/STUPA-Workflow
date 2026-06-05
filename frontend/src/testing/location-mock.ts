/**
 * jsdom-`window.location.assign` ist read-only und lässt sich nicht `spyOn`-en.
 * Helfer ersetzt `location` durch ein Stub-Objekt mit einer Jest-`assign`-Mock
 * und liefert eine Restore-Funktion. In `beforeEach` aufrufen, in `afterEach`
 * restoren.
 */
export interface LocationMock {
  assign: jest.Mock<void, [string]>;
  restore: () => void;
}

export function mockWindowLocation(): LocationMock {
  const original = window.location;
  const assign = jest.fn<void, [string]>();
  Object.defineProperty(window, 'location', {
    configurable: true,
    writable: true,
    value: {
      ...original,
      assign,
      href: original?.href ?? 'http://localhost/',
      pathname: original?.pathname ?? '/',
    },
  });
  return {
    assign,
    restore: () =>
      Object.defineProperty(window, 'location', {
        configurable: true,
        writable: true,
        value: original,
      }),
  };
}
