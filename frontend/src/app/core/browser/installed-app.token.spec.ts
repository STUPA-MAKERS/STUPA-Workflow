import { TestBed } from '@angular/core/testing';
import { IS_INSTALLED_APP, isInstalledApp, type DisplayModeHost } from './installed-app.token';

/** A host whose `matchMedia` matches exactly the given display mode. */
function host(mode: string | null, standalone?: boolean): DisplayModeHost {
  return {
    matchMedia: (query: string) => ({ matches: mode !== null && query === `(display-mode: ${mode})` }),
    navigator: standalone === undefined ? {} : { standalone },
  };
}

describe('isInstalledApp', () => {
  it.each(['standalone', 'fullscreen', 'minimal-ui'])('is true for the display mode %s', (mode) => {
    expect(isInstalledApp(host(mode))).toBe(true);
  });

  it('is false for a browser tab', () => {
    expect(isInstalledApp(host('browser'))).toBe(false);
    expect(isInstalledApp(host(null, false))).toBe(false);
  });

  it('is true for an iOS home-screen app, which reports no display mode', () => {
    expect(isInstalledApp(host(null, true))).toBe(true);
  });

  it('is false when the browser has no matchMedia', () => {
    expect(isInstalledApp({ navigator: {} })).toBe(false);
  });

  /** The setup mock of matchMedia matches nothing, which is a browser tab. */
  it('reads the window through the default token', () => {
    const spy = jest.spyOn(window, 'matchMedia');
    const read = TestBed.inject(IS_INSTALLED_APP);
    expect(read()).toBe(false);
    expect(spy).toHaveBeenCalledWith('(display-mode: standalone)');
    spy.mockRestore();
  });
});
