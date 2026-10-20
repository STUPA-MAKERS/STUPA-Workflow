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

  it('reads the Gravatar switch; a config without it counts as on', () => {
    expect(svc.gravatarEnabled()).toBe(true);
    svc.init();
    http.expectOne('/api/site-config').flush({ version: 1, branding: { gravatarEnabled: false } });
    expect(svc.gravatarEnabled()).toBe(false);
    svc.init();
    http.expectOne('/api/site-config').flush({ version: 2, branding: {} });
    expect(svc.gravatarEnabled()).toBe(true);
    svc.init();
    http.expectOne('/api/site-config').flush({ version: 3, branding: null });
    expect(svc.gravatarEnabled()).toBe(true);
  });

  it('reads the handbook link and the public ticket switch', () => {
    expect(svc.wikiUrl()).toBe(BrandingService.DEFAULT_WIKI_URL);
    expect(svc.ticketsPublic()).toBe(false);
    svc.init();
    http.expectOne('/api/site-config').flush({
      version: 1,
      help: { wikiUrl: 'https://wiki.example/x' },
      tickets: { publicEnabled: true },
    });
    expect(svc.wikiUrl()).toBe('https://wiki.example/x');
    expect(svc.ticketsPublic()).toBe(true);
    // An older server without the blocks keeps the link and turns the form off.
    svc.init();
    http.expectOne('/api/site-config').flush({ version: 2 });
    expect(svc.wikiUrl()).toBe('https://wiki.example/x');
    expect(svc.ticketsPublic()).toBe(false);
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
  describe('accent colour and logos', () => {
    afterEach(() => {
      svc.applyBranding(null);
      TestBed.tick();
      document.head.querySelectorAll('link[data-test-icon]').forEach((l) => l.remove());
    });

    it('applies the accent of the config to the root and keeps it for the next start', () => {
      svc.init();
      http.expectOne('/api/site-config').flush({ version: 1, branding: { accentColor: '#0075BF' } });
      TestBed.tick();
      expect(svc.accentColor()).toBe('#0075bf');
      expect(document.documentElement.style.getPropertyValue('--c-accent')).toBe('#0075bf');
      expect(localStorage.getItem('ap.accent')).toBe('#0075bf');
      svc.applyBranding({ accentColor: null });
      TestBed.tick();
      expect(document.documentElement.style.getPropertyValue('--c-accent')).toBe('');
      expect(localStorage.getItem('ap.accent')).toBeNull();
    });

    it('starts with the stored accent before the config loads', () => {
      localStorage.setItem('ap.accent', '#ce1625');
      TestBed.resetTestingModule();
      TestBed.configureTestingModule({
        providers: [provideHttpClient(), provideHttpClientTesting(), { provide: USE_MOCK_API, useValue: false }],
      });
      const fresh = TestBed.inject(BrandingService);
      http = TestBed.inject(HttpTestingController);
      TestBed.tick();
      expect(fresh.accentColor()).toBe('#ce1625');
      expect(document.documentElement.style.getPropertyValue('--c-accent')).toBe('#ce1625');
      svc = fresh;
    });

    it('previews an accent and goes back to the saved one', () => {
      svc.applyBranding({ accentColor: '#0075bf' });
      svc.previewAccent('#7A4BC2');
      TestBed.tick();
      expect(document.documentElement.style.getPropertyValue('--c-accent')).toBe('#7a4bc2');
      svc.previewAccent(null);
      TestBed.tick();
      expect(document.documentElement.style.getPropertyValue('--c-accent')).toBe('');
      svc.previewAccent(undefined);
      TestBed.tick();
      expect(document.documentElement.style.getPropertyValue('--c-accent')).toBe('#0075bf');
    });

    it('gives the uploaded logos and the built-in ones for an empty slot', () => {
      expect(svc.wordmarkSrc()).toMatch(/^assets\/logos\/stupa-wordmark-(light|dark)\.svg$/);
      expect(svc.markSrc()).toBe('assets/logos/stupa-mark.svg');
      expect(svc.faviconSrc()).toBe('favicon.ico');
      expect(svc.logoUpload('wordmark')).toBeNull();
      svc.applyBranding({ logos: { wordmark: { url: 'data:image/png;base64,AA' }, imagemark: { url: '/m.png' } } });
      expect(svc.wordmarkSrc()).toBe('data:image/png;base64,AA');
      expect(svc.markSrc()).toBe('/m.png');
      expect(svc.faviconSrc()).toBe('favicon.ico');
      expect(svc.logoUpload('imagemark')).toBe('/m.png');
    });

    it('puts an uploaded favicon on the icon links and the built-in one back', () => {
      const link = document.createElement('link');
      link.rel = 'icon';
      link.type = 'image/svg+xml';
      link.href = 'assets/logos/stupa-mark.svg';
      link.setAttribute('data-test-icon', '');
      document.head.appendChild(link);
      TestBed.tick();
      svc.applyBranding({ logos: { favicon: { url: 'data:image/png;base64,BB' } } });
      TestBed.tick();
      expect(link.getAttribute('href')).toBe('data:image/png;base64,BB');
      expect(link.hasAttribute('type')).toBe(false);
      svc.applyBranding({});
      TestBed.tick();
      expect(link.getAttribute('href')).toBe('assets/logos/stupa-mark.svg');
      // A link without an href gets an empty one back.
      const bare = document.createElement('link');
      bare.rel = 'icon';
      bare.setAttribute('data-test-icon', '');
      document.head.appendChild(bare);
      svc.applyBranding({ logos: { favicon: { url: '/f.png' } } });
      TestBed.tick();
      expect(bare.getAttribute('href')).toBe('/f.png');
      svc.applyBranding({});
      TestBed.tick();
      expect(bare.getAttribute('href')).toBe('');
    });

    it('works without a usable browser storage', () => {
      const get = jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
        throw new Error('blocked');
      });
      expect(() => svc.applyBranding({ accentColor: '#0075bf' })).not.toThrow();
      get.mockRestore();
      const read = jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
        throw new Error('blocked');
      });
      TestBed.resetTestingModule();
      TestBed.configureTestingModule({
        providers: [provideHttpClient(), provideHttpClientTesting(), { provide: USE_MOCK_API, useValue: false }],
      });
      const fresh = TestBed.inject(BrandingService);
      http = TestBed.inject(HttpTestingController);
      expect(fresh.accentColor()).toBeNull();
      read.mockRestore();
      svc = fresh;
    });
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
