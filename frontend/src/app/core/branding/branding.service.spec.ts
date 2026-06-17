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
    // The constructor effect already mirrored the fallback into document.title.
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
    // EN and DE titles differ, proving the computed re-evaluated on locale change.
    expect(en).not.toBe(de);
  });
});
