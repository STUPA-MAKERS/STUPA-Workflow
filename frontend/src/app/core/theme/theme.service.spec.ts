import { TestBed } from '@angular/core/testing';
import { THEME_COLOR, ThemeService } from './theme.service';

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
    // The OS flips to dark. The preference stays the explicit 'light', so the resolved
    // theme stays light.
    changeHandler?.({ matches: true } as MediaQueryListEvent);
    expect(svc.resolved()).toBe('light');
    // The apply step calls setAttribute. It must not run for this OS change.
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
    expect(() => svc.setPreference('dark')).not.toThrow();
    expect(svc.preference()).toBe('dark');
    setItem.mockRestore();
  });

  describe('theme-color meta tags', () => {
    let metas: HTMLMetaElement[];

    beforeEach(() => {
      metas = ['(prefers-color-scheme: light)', '(prefers-color-scheme: dark)'].map((media) => {
        const meta = document.createElement('meta');
        meta.setAttribute('name', 'theme-color');
        meta.setAttribute('media', media);
        meta.setAttribute('content', '#000000');
        document.head.appendChild(meta);
        return meta;
      });
    });

    afterEach(() => metas.forEach((m) => m.remove()));

    it('colours the browser bars with the page background of the theme in effect', () => {
      const svc = service();
      svc.init();
      expect(metas.map((m) => m.getAttribute('content'))).toEqual([THEME_COLOR.light, THEME_COLOR.light]);
      svc.setPreference('dark');
      expect(metas.map((m) => m.getAttribute('content'))).toEqual([THEME_COLOR.dark, THEME_COLOR.dark]);
    });

    it('uses the background tokens of the design system, not the old brand green', () => {
      expect(THEME_COLOR).toEqual({ light: '#f6f7f5', dark: '#101211' });
    });
  });
});
