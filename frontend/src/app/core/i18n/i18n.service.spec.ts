import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { I18nService, baseLocale, fallbackChain, toFormatLocale } from './i18n.service';
import * as translations from './translations';
import { CATALOG } from './translations';

describe('I18nService', () => {
  /**
   * jsdom reports en-US by default. The test pins German, so the "no stored choice" path always
   * resolves to the default that this spec expects.
   */
  beforeEach(() => {
    localStorage.clear();
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

  /**
   * The test simulates an incomplete EN catalog. The `en` type is `Partial` on purpose.
   * `action.login` is a shared, long-lived key, so a rework of the copy of a page does not break
   * this test.
   */
  it('falls back to German for keys missing in the active locale', () => {
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

  /**
   * The key lookup stays on 'de'/'en', because the catalogue has no other keys. Intl gets en-GB, so
   * English reads DD/MM/YYYY and a 24 h clock.
   */
  it('maps the UI locale to an Intl locale without moving the translation key locale', () => {
    const i18n = service();
    expect(i18n.locale()).toBe('de');
    expect(i18n.formatLocale()).toBe('de-DE');
    i18n.setLocale('en');
    expect(i18n.locale()).toBe('en');
    expect(i18n.translate('action.login')).toBe('Sign in');
    expect(i18n.formatLocale()).toBe('en-GB');
  });

  it('gives the same mapping as a pure function to code that has no injector', () => {
    expect(toFormatLocale('de')).toBe('de-DE');
    expect(toFormatLocale('en')).toBe('en-GB');
    expect(toFormatLocale('fr')).toBe('en-GB');
  });
  it('ready() loads the catalog of the active locale', async () => {
    localStorage.setItem('ap.locale', 'en');
    const load = jest.spyOn(translations, 'loadCatalog');
    const i18n = service();
    await i18n.ready();
    expect(load).toHaveBeenCalledWith('en');
    expect(i18n.translate('action.login')).toBe('Sign in');
    load.mockRestore();
  });

  it('ready() resolves when the catalog does not load, so the app starts in German', async () => {
    localStorage.setItem('ap.locale', 'en');
    const load = jest.spyOn(translations, 'loadCatalog').mockRejectedValue(new Error('offline'));
    const i18n = service();
    await expect(i18n.ready()).resolves.toBeUndefined();
    load.mockRestore();
  });

  it('setLocale() starts the load of the new catalog', () => {
    const load = jest.spyOn(translations, 'loadCatalog');
    service().setLocale('en');
    expect(load).toHaveBeenCalledWith('en');
    load.mockRestore();
  });

  describe('overrides and extra languages', () => {
    function withHttp(): { i18n: I18nService; http: HttpTestingController } {
      TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
      return { i18n: TestBed.inject(I18nService), http: TestBed.inject(HttpTestingController) };
    }

    it('applies the overrides of the bundle before the built-in texts', async () => {
      const { i18n, http } = withHttp();
      const done = i18n.ready();
      const req = http.expectOne((r) => r.url === '/api/i18n');
      expect(req.request.params.get('locale')).toBe('de');
      req.flush({ locale: 'de', languages: [], overrides: { de: { 'nav.dashboard': 'Übersicht' } } });
      await done;
      expect(i18n.translate('nav.dashboard')).toBe('Übersicht');
      expect(i18n.translate('action.login')).toBe('Anmelden');
      expect(i18n.builtIn('nav.dashboard', 'de')).toBe('Dashboard');
      expect(i18n.builtIn('nav.dashboard', 'en')).toBe('Dashboard');
    });

    it('resolves an extra language through EN, then DE', async () => {
      localStorage.setItem('ap.locale', 'fr');
      const { i18n, http } = withHttp();
      expect(i18n.uiLocale()).toBe('de');
      const done = i18n.ready();
      const req = http.expectOne((r) => r.url === '/api/i18n');
      expect(req.request.params.get('locale')).toBe('fr');
      req.flush({
        locale: 'fr',
        languages: [{ code: 'fr', name: 'Français' }],
        overrides: { fr: { 'nav.dashboard': 'Tableau de bord' }, en: { 'action.login': 'Log in' }, de: {} },
      });
      await done;
      expect(i18n.uiLocale()).toBe('fr');
      expect(i18n.locale()).toBe('en');
      expect(i18n.formatLocale()).toBe('en-GB');
      expect(document.documentElement.lang).toBe('fr');
      expect(i18n.locales()).toEqual(['de', 'en', 'fr']);
      expect(i18n.extraLanguages()).toEqual([{ code: 'fr', name: 'Français' }]);
      expect(i18n.locales().map((code) => i18n.languageName(code))).toEqual(['Deutsch', 'English', 'Français']);
      expect(i18n.languageName('pt-BR')).toBe('PT-BR');
      expect(i18n.translate('nav.dashboard')).toBe('Tableau de bord');
      expect(i18n.translate('action.login')).toBe('Log in');
      expect(i18n.translate('nav.tasks')).toBe('Tasks');

      i18n.applyOverrides('fr', { 'nav.tasks': 'Tâches' });
      expect(i18n.translate('nav.tasks')).toBe('Tâches');
      expect(i18n.translate('nav.dashboard')).toBe('Dashboard');

      i18n.setLocale('de');
      expect(i18n.translate('nav.tasks')).toBe('Aufgaben');
      i18n.setLocale('fr');
      expect(i18n.uiLocale()).toBe('fr');
    });

    it('keeps the built-in texts when the bundle does not load', async () => {
      const { i18n, http } = withHttp();
      const done = i18n.ready();
      http.expectOne((r) => r.url === '/api/i18n').flush('down', { status: 503, statusText: 'down' });
      await done;
      expect(i18n.translate('nav.dashboard')).toBe('Dashboard');
      expect(i18n.locales()).toEqual(['de', 'en']);
    });

    it('starts from a browser language that may be an extra language', () => {
      Object.defineProperty(navigator, 'language', { value: 'fr-FR', configurable: true });
      const { i18n, http } = withHttp();
      void i18n.ready();
      expect(http.expectOne((r) => r.url === '/api/i18n').request.params.get('locale')).toBe('fr');
    });

    it('ignores a stored value that is no locale tag', () => {
      localStorage.setItem('ap.locale', '<script>');
      const { i18n, http } = withHttp();
      void i18n.ready();
      expect(http.expectOne((r) => r.url === '/api/i18n').request.params.get('locale')).toBe('de');
    });
  });

  it('gives the base locale and the fallback chain of each UI locale', () => {
    expect(baseLocale('de')).toBe('de');
    expect(baseLocale('en')).toBe('en');
    expect(baseLocale('fr')).toBe('en');
    expect(fallbackChain('de')).toEqual(['de']);
    expect(fallbackChain('en')).toEqual(['en', 'de']);
    expect(fallbackChain('pt-BR')).toEqual(['pt-BR', 'en', 'de']);
  });

  it('works when the storage is blocked', () => {
    const get = jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    const set = jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    try {
      const i18n = service();
      expect(i18n.uiLocale()).toBe('de');
      i18n.setLocale('en');
      expect(i18n.uiLocale()).toBe('en');
    } finally {
      get.mockRestore();
      set.mockRestore();
    }
  });
});
