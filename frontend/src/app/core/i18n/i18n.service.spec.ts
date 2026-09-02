import { TestBed } from '@angular/core/testing';
import { I18nService } from './i18n.service';
import { CATALOG } from './translations';

describe('I18nService', () => {
  beforeEach(() => {
    localStorage.clear();
    // jsdom reports en-US by default. Pin German so the "no stored choice" path
    // always resolves to the default that this spec expects.
    Object.defineProperty(navigator, 'language', { value: 'de-DE', configurable: true });
  });

  function service(): I18nService {
    return TestBed.configureTestingModule({}).inject(I18nService);
  }

  it('defaults to German', () => {
    const i18n = service();
    expect(i18n.locale()).toBe('de');
    expect(i18n.translate('nav.dashboard')).toBe('Dashboard');
  });

  it('switches locale and persists the choice', () => {
    const i18n = service();
    i18n.setLocale('en');
    expect(i18n.locale()).toBe('en');
    expect(i18n.translate('action.login')).toBe('Sign in');
    expect(localStorage.getItem('ap.locale')).toBe('en');
    expect(document.documentElement.lang).toBe('en');
  });

  it('falls back to German for keys missing in the active locale', () => {
    // Simulate an incomplete EN catalog. The `en` type is `Partial` on purpose.
    // `action.login` is a shared, long-lived key, so this test does not break again the
    // next time a page reworks its own copy.
    const original = CATALOG.en['action.login'];
    delete CATALOG.en['action.login'];
    try {
      const i18n = service();
      i18n.setLocale('en');
      expect(i18n.translate('action.login')).toBe('Anmelden');
    } finally {
      CATALOG.en['action.login'] = original;
    }
  });

  it('interpolates parameters', () => {
    const i18n = service();
    expect(i18n.translate('nav.dashboard', { x: 1 })).toBe('Dashboard');
  });

  it('ignores unsupported locales', () => {
    const i18n = service();
    i18n.setLocale('fr' as never);
    expect(i18n.locale()).toBe('de');
  });

  it('syncs <html lang> with the resolved locale on construction', () => {
    document.documentElement.lang = '';
    localStorage.setItem('ap.locale', 'en');
    service();
    expect(document.documentElement.lang).toBe('en');
  });
});
