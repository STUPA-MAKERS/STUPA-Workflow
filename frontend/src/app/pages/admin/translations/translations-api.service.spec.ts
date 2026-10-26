import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { TranslationsApiService } from './translations-api.service';

describe('TranslationsApiService', () => {
  let api: TranslationsApiService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    api = TestBed.inject(TranslationsApiService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('calls the admin routes', () => {
    api.languages().subscribe();
    http.expectOne({ method: 'GET', url: '/api/admin/translations/languages' }).flush([]);
    api.createLanguage({ code: 'fr', name: 'Français' }).subscribe();
    expect(http.expectOne({ method: 'POST', url: '/api/admin/translations/languages' }).request.body).toEqual({
      code: 'fr',
      name: 'Français',
    });
    api.updateLanguage('pt-BR', { active: true }).subscribe();
    http.expectOne({ method: 'PATCH', url: '/api/admin/translations/languages/pt-BR' }).flush({});
    api.deleteLanguage('fr').subscribe();
    http.expectOne({ method: 'DELETE', url: '/api/admin/translations/languages/fr' }).flush(null);
    api.texts('de').subscribe();
    http.expectOne({ method: 'GET', url: '/api/admin/translations/texts/de' }).flush({ locale: 'de', overrides: {} });
    api.saveTexts('en', { 'nav.tasks': null }).subscribe();
    expect(http.expectOne({ method: 'PUT', url: '/api/admin/translations/texts/en' }).request.body).toEqual({
      changes: { 'nav.tasks': null },
    });
  });
});
