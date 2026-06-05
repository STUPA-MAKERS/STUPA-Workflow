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
});
