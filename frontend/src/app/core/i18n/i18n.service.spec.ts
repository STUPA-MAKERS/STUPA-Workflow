import { TestBed } from '@angular/core/testing';
import { I18nService } from './i18n.service';
import { CATALOG } from './translations';

describe('I18nService', () => {
  beforeEach(() => {
    localStorage.clear();
    // jsdom reports en-US by default — pin to German so the "no stored choice"
    // path resolves deterministically to the spec's expected default.
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
    // Simulate an incomplete EN catalog (en is intentionally `Partial`).
    const original = CATALOG.en['home.cta'];
    delete CATALOG.en['home.cta'];
    try {
      const i18n = service();
      i18n.setLocale('en');
      expect(i18n.translate('home.cta')).toBe('Jetzt Antrag stellen');
    } finally {
      CATALOG.en['home.cta'] = original;
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
});
