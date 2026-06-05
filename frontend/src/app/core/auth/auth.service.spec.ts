import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { AuthService } from './auth.service';
import { USE_MOCK_API } from '../api/api.config';
import type { Principal } from '../api/models';

const PRINCIPAL: Principal = {
  id: '1',
  displayName: 'Mia',
  email: 'mia@stupa',
  roles: ['member'],
  permissions: ['vote.cast'],
  groups: [],
};

describe('AuthService', () => {
  let auth: AuthService;
  let http: HttpTestingController;

  beforeEach(() => {
    sessionStorage.clear();
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: false },
      ],
    });
    auth = TestBed.inject(AuthService);
    http = TestBed.inject(HttpTestingController);
  });

  it('loads the principal and exposes permission checks', () => {
    auth.loadPrincipal();
    http.expectOne('/api/auth/me').flush(PRINCIPAL);
    expect(auth.isAuthenticated()).toBe(true);
    expect(auth.can('vote.cast')).toBe(true);
    expect(auth.can('admin.config')).toBe(false);
  });

  it('stays anonymous when /me returns 401', () => {
    auth.loadPrincipal();
    http.expectOne('/api/auth/me').flush(null, { status: 401, statusText: 'Unauthorized' });
    expect(auth.isAuthenticated()).toBe(false);
    expect(auth.can('vote.cast')).toBe(false);
  });

  it('persists the applicant token to sessionStorage', () => {
    auth.setApplicantToken('tok-123');
    expect(auth.applicantToken()).toBe('tok-123');
    expect(sessionStorage.getItem('ap.applicantToken')).toBe('tok-123');
    auth.setApplicantToken(null);
    expect(sessionStorage.getItem('ap.applicantToken')).toBeNull();
  });
});
