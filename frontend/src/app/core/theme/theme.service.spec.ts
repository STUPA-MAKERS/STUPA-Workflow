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
});
