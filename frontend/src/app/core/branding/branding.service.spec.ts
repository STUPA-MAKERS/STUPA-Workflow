import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { Title } from '@angular/platform-browser';
import { BrandingService } from './branding.service';
import { I18nService } from '@core/i18n/i18n.service';
import { USE_MOCK_API } from '@core/api/api.config';

describe('BrandingService', () => {
  let svc: BrandingService;
  let http: HttpTestingController;
  let i18n: I18nService;
  let title: Title;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: false },
      ],
    });
    svc = TestBed.inject(BrandingService);
    http = TestBed.inject(HttpTestingController);
    i18n = TestBed.inject(I18nService);
    title = TestBed.inject(Title);
  });

  afterEach(() => http.verify());

  it('falls back to the i18n app title before any config is loaded', () => {
    expect(svc.appName()).toBe(i18n.translate('app.title'));
    expect(svc.homeHeading()).toBe(i18n.translate('home.heading'));
    // The constructor effect already copied the fallback into document.title.
    TestBed.tick();
    expect(title.getTitle()).toBe(i18n.translate('app.title'));
  });

  it('uses the configured app name once the public config loads', () => {
    svc.init();
    http.expectOne('/api/site-config').flush({ version: 1, branding: { appName: 'StuPa Portal' } });

    expect(svc.appName()).toBe('StuPa Portal');
    expect(svc.homeHeading()).toBe('StuPa Portal');
    TestBed.tick();
    expect(title.getTitle()).toBe('StuPa Portal');
  });

  it('trims the configured name and falls back when it is blank', () => {
    svc.init();
    http.expectOne('/api/site-config').flush({ version: 1, branding: { appName: '   ' } });
    expect(svc.appName()).toBe(i18n.translate('app.title'));
  });

  it('falls back when the config has no branding block at all', () => {
    svc.init();
    http.expectOne('/api/site-config').flush({ version: 1, branding: null });
    expect(svc.appName()).toBe(i18n.translate('app.title'));
  });

  it('falls back when branding is present but appName is missing', () => {
    svc.init();
    http.expectOne('/api/site-config').flush({ version: 1, branding: {} });
    expect(svc.appName()).toBe(i18n.translate('app.title'));
  });

  it('keeps the i18n fallback when the config request errors', () => {
    svc.init();
    http
      .expectOne('/api/site-config')
      .flush(null, { status: 500, statusText: 'Server Error' });
    expect(svc.appName()).toBe(i18n.translate('app.title'));
  });

  it('reacts to a locale switch via the i18n fallback', () => {
    const de = svc.appName();
    i18n.setLocale('en');
    const en = svc.appName();
    expect(en).toBe(i18n.translate('app.title'));
    // The EN and DE titles differ, so a change proves the computed value ran again.
    expect(en).not.toBe(de);
  });
  describe('footer branding (public, no session required)', () => {
    it('keeps the copyright and the legal links from the public config', () => {
      svc.init();
      http.expectOne((r) => r.url.endsWith('/site-config')).flush({
        version: 3,
        branding: {
          appName: 'StuPa',
          copyright: { de: '© Verfasste Studierendenschaft' },
          legalLinks: [{ label: { de: 'Impressum' }, url: 'https://example.org/impressum' }],
        },
      });
      expect(svc.copyright()).toEqual({ de: '© Verfasste Studierendenschaft' });
      expect(svc.legalLinks()).toEqual([
        { label: { de: 'Impressum' }, url: 'https://example.org/impressum' },
      ]);
    });

    it('reads the PUBLIC endpoint, so a logged-out visitor sees the same footer', () => {
      // This is the whole point of the fix: the footer used to come from
      // /admin/site-config, which a visitor on the landing page cannot read.
      svc.init();
      const req = http.expectOne((r) => r.url.endsWith('/site-config'));
      expect(req.request.url).not.toContain('/admin/');
      req.flush({ version: 1, branding: null });
    });

    it('falls back to empty footer data when the config carries none', () => {
      svc.init();
      http.expectOne((r) => r.url.endsWith('/site-config')).flush({
        version: 1,
        branding: { appName: 'StuPa' },
      });
      expect(svc.copyright()).toBeNull();
      expect(svc.legalLinks()).toEqual([]);
    });

    it('keeps the footer empty when the config cannot be loaded', () => {
      svc.init();
      http
        .expectOne((r) => r.url.endsWith('/site-config'))
        .flush(null, { status: 500, statusText: 'Server Error' });
      expect(svc.copyright()).toBeNull();
      expect(svc.legalLinks()).toEqual([]);
    });
  });
});
