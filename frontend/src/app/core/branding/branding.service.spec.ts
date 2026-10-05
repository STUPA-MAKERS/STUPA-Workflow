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

  it('starts with the default confirmation window of 12 hours', () => {
    expect(svc.confirmTtlHours()).toBe(BrandingService.DEFAULT_CONFIRM_TTL_HOURS);
    expect(svc.confirmTtlHours()).toBe(12);
  });

  it('takes the confirmation window from the public config', () => {
    svc.init();
    http.expectOne('/api/site-config').flush({ version: 1, branding: null, confirmTtlHours: 48 });
    expect(svc.confirmTtlHours()).toBe(48);
  });

  it('keeps the default window when the config has none or a bad value', () => {
    svc.init();
    http.expectOne('/api/site-config').flush({ version: 1, branding: null, confirmTtlHours: 0 });
    expect(svc.confirmTtlHours()).toBe(12);
  });

  it('starts with links without an expiry and the default upload limits', () => {
    expect(svc.loaded()).toBe(false);
    expect(svc.linkTtlDays()).toBeNull();
    expect(svc.attachmentLimits()).toEqual(BrandingService.DEFAULT_ATTACHMENT_LIMITS);
    expect(svc.freetexts()).toEqual({});
  });

  it('takes the link lifetime, the upload limits and the free texts from the config', () => {
    svc.init();
    const limits = { maxFileBytes: 5, maxDraftFiles: 3, maxDraftBytes: 9 };
    http.expectOne('/api/site-config').flush({
      version: 1,
      branding: { freetexts: { welcome: { de: 'Hallo' } } },
      linkTtlDays: 30,
      attachmentLimits: limits,
    });
    expect(svc.linkTtlDays()).toBe(30);
    expect(svc.attachmentLimits()).toEqual(limits);
    expect(svc.freetexts()).toEqual({ welcome: { de: 'Hallo' } });
  });

  it('keeps unlimited links and the default limits when the config has none', () => {
    svc.init();
    http.expectOne('/api/site-config').flush({ version: 1, branding: null, linkTtlDays: null });
    expect(svc.loaded()).toBe(true);
    expect(svc.linkTtlDays()).toBeNull();
    expect(svc.attachmentLimits()).toEqual(BrandingService.DEFAULT_ATTACHMENT_LIMITS);
    expect(svc.freetexts()).toEqual({});
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
      // A visitor on the landing page cannot read /admin/site-config, so a footer taken
      // from there falls back to the defaults for exactly the people who are not signed in.
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
