import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ApiClient } from './api-client.service';
import { USE_MOCK_API } from './api.config';

describe('ApiClient', () => {
  let api: ApiClient;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: false },
      ],
    });
    api = TestBed.inject(ApiClient);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('GETs the principal from /api/auth/me', () => {
    api.me().subscribe();
    const req = http.expectOne('/api/auth/me');
    expect(req.request.method).toBe('GET');
    req.flush({ id: 'x', displayName: 'A', email: 'a@b', roles: [], permissions: [], groups: [] });
  });

  it('GETs application types', () => {
    api.applicationTypes().subscribe();
    http.expectOne('/api/application-types').flush([]);
  });

  it('serialises list query params', () => {
    api.listApplications({ state: 'draft', q: 'foo', limit: 10 }).subscribe();
    const req = http.expectOne((r) => r.url === '/api/applications');
    expect(req.request.params.get('state')).toBe('draft');
    expect(req.request.params.get('q')).toBe('foo');
    expect(req.request.params.get('limit')).toBe('10');
    req.flush({ items: [], total: 0, limit: 10, offset: 0 });
  });

  it('POSTs a transition payload', () => {
    api.fireTransition('app-1', { transition_id: 't-1', note: 'ok' }).subscribe();
    const req = http.expectOne('/api/applications/app-1/transition');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ transition_id: 't-1', note: 'ok' });
    req.flush({});
  });

  it('builds nested resource URLs', () => {
    api.timeline('app-9').subscribe();
    http.expectOne('/api/applications/app-9/timeline').flush([]);
  });

  it('POSTs the magic-link token to verify', () => {
    api.verifyMagicLink('tok-1').subscribe();
    const req = http.expectOne('/api/auth/magic-link/verify');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ token: 'tok-1' });
    req.flush({ application_id: 'a', scope: 'edit' });
  });

  it('GETs the effective form with an optional pot param', () => {
    api.effectiveForm('type-1', 'pot-9').subscribe();
    const req = http.expectOne((r) => r.url === '/api/application-types/type-1/form');
    expect(req.request.params.get('pot')).toBe('pot-9');
    req.flush({ applicationTypeId: 'type-1', formVersionId: 'v1', sections: [] });
  });

  it('PATCHes application data', () => {
    api.updateApplication('app-2', { title: 'Neu' }).subscribe();
    const req = http.expectOne('/api/applications/app-2');
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toEqual({ data: { title: 'Neu' } });
    req.flush({});
  });

  it('GETs and POSTs comments', () => {
    api.comments('app-3').subscribe();
    http.expectOne('/api/applications/app-3/comments').flush([]);
    api.addComment('app-3', 'Hallo').subscribe();
    const req = http.expectOne('/api/applications/app-3/comments');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ body: 'Hallo' });
    req.flush({});
  });
});
