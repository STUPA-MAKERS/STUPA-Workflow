import { TestBed } from '@angular/core/testing';
import { ThemeService } from './theme.service';

describe('ThemeService', () => {
  let matchesMock: boolean;
  let changeHandler: ((e: MediaQueryListEvent) => void) | null;

  beforeEach(() => {
    localStorage.clear();
    matchesMock = false;
    changeHandler = null;
    (window.matchMedia as unknown) = jest.fn().mockImplementation((query: string) => ({
      matches: matchesMock,
      media: query,
      addEventListener: (_: string, cb: (e: MediaQueryListEvent) => void) => (changeHandler = cb),
      removeEventListener: () => {},
    }));
    document.documentElement.removeAttribute('data-theme');
  });

  function service(): ThemeService {
    return TestBed.configureTestingModule({}).inject(ThemeService);
  }

  it('defaults to system preference and resolves to light when OS is light', () => {
    const svc = service();
    svc.init();
    expect(svc.preference()).toBe('system');
    expect(svc.resolved()).toBe('light');
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');
  });

  it('follows the OS when in system mode', () => {
    const svc = service();
    svc.init();
    changeHandler?.({ matches: true } as MediaQueryListEvent);
    expect(svc.resolved()).toBe('dark');
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
  });

  it('toggles to an explicit theme and persists it', () => {
    const svc = service();
    svc.init();
    svc.toggle();
    expect(svc.resolved()).toBe('dark');
    expect(svc.preference()).toBe('dark');
    expect(localStorage.getItem('ap.theme')).toBe('dark');
  });

  it('restores a persisted explicit preference over the OS setting', () => {
    localStorage.setItem('ap.theme', 'dark');
    matchesMock = false;
    const svc = service();
    svc.init();
    expect(svc.resolved()).toBe('dark');
  });

  it('toggles from dark back to light', () => {
    const svc = service();
    svc.init();
    svc.setPreference('dark');
    svc.toggle();
    expect(svc.resolved()).toBe('light');
    expect(svc.preference()).toBe('light');
  });

  it('does not re-apply on OS change when an explicit preference is set', () => {
    const svc = service();
    svc.init();
    svc.setPreference('light');
    const applySpy = jest.spyOn(document.documentElement, 'setAttribute');
    // OS flips to dark, but preference is the explicit 'light' → resolved stays light.
    changeHandler?.({ matches: true } as MediaQueryListEvent);
    expect(svc.resolved()).toBe('light');
    // apply() (setAttribute) must NOT have run for this OS change.
    expect(applySpy).not.toHaveBeenCalled();
    applySpy.mockRestore();
  });

  it('ignores corrupt stored values and falls back to system', () => {
    localStorage.setItem('ap.theme', 'banana');
    const svc = service();
    expect(svc.preference()).toBe('system');
  });

  it('falls back to system when localStorage reads throw', () => {
    const getItem = jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    const svc = service();
    expect(svc.preference()).toBe('system');
    getItem.mockRestore();
  });

  it('swallows localStorage write failures when persisting', () => {
    const setItem = jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota');
    });
    const svc = service();
    svc.init();
    // Should not throw despite the storage write blowing up.
    expect(() => svc.setPreference('dark')).not.toThrow();
    expect(svc.preference()).toBe('dark');
    setItem.mockRestore();
  });
});
