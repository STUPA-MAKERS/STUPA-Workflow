import { TestBed } from '@angular/core/testing';
import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { authInterceptor } from './auth.interceptor';
import { AuthService } from './auth.service';
import { USE_MOCK_API } from '../api/api.config';

describe('authInterceptor', () => {
  let httpClient: HttpClient;
  let http: HttpTestingController;
  let auth: AuthService;

  beforeEach(() => {
    sessionStorage.clear();
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([authInterceptor])),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: false },
      ],
    });
    httpClient = TestBed.inject(HttpClient);
    http = TestBed.inject(HttpTestingController);
    auth = TestBed.inject(AuthService);
  });

  afterEach(() => http.verify());

  it('adds withCredentials and no bearer for anonymous /api requests', () => {
    httpClient.get('/api/applications').subscribe();
    const req = http.expectOne('/api/applications');
    expect(req.request.withCredentials).toBe(true);
    expect(req.request.headers.has('Authorization')).toBe(false);
    req.flush({});
  });

  it('attaches the applicant magic-link token as a bearer', () => {
    auth.setApplicantToken('magic-xyz');
    httpClient.get('/api/applications/1').subscribe();
    const req = http.expectOne('/api/applications/1');
    expect(req.request.headers.get('Authorization')).toBe('Bearer magic-xyz');
    req.flush({});
  });

  it('leaves non-api requests untouched', () => {
    httpClient.get('/assets/logos/stupa-mark.svg').subscribe();
    const req = http.expectOne('/assets/logos/stupa-mark.svg');
    expect(req.request.withCredentials).toBe(false);
    req.flush('');
  });

  describe('CSRF double-submit', () => {
    afterEach(() => {
      document.cookie = 'XSRF-TOKEN=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/';
    });

    it('mirrors the XSRF-TOKEN cookie into the header for unsafe methods', () => {
      document.cookie = 'XSRF-TOKEN=csrf-abc; path=/';
      httpClient.post('/api/applications', {}).subscribe();
      const req = http.expectOne('/api/applications');
      expect(req.request.headers.get('X-XSRF-TOKEN')).toBe('csrf-abc');
      req.flush({});
    });

    it('does not send a CSRF header for safe GET requests', () => {
      document.cookie = 'XSRF-TOKEN=csrf-abc; path=/';
      httpClient.get('/api/applications').subscribe();
      const req = http.expectOne('/api/applications');
      expect(req.request.headers.has('X-XSRF-TOKEN')).toBe(false);
      req.flush({});
    });

    it('omits the header when no cookie is present', () => {
      httpClient.post('/api/applications', {}).subscribe();
      const req = http.expectOne('/api/applications');
      expect(req.request.headers.has('X-XSRF-TOKEN')).toBe(false);
      req.flush({});
    });
  });

  describe('401 handling', () => {
    it('triggers re-login on a 401 from a protected endpoint', () => {
      const spy = jest.spyOn(auth, 'handleUnauthorized').mockImplementation(() => undefined);
      httpClient.get('/api/applications').subscribe({ error: () => undefined });
      http
        .expectOne('/api/applications')
        .flush(null, { status: 401, statusText: 'Unauthorized' });
      expect(spy).toHaveBeenCalled();
    });

    it('ignores a 401 from the anonymous /auth/me probe', () => {
      const spy = jest.spyOn(auth, 'handleUnauthorized').mockImplementation(() => undefined);
      httpClient.get('/api/auth/me').subscribe({ error: () => undefined });
      http.expectOne('/api/auth/me').flush(null, { status: 401, statusText: 'Unauthorized' });
      expect(spy).not.toHaveBeenCalled();
    });
  });
});
