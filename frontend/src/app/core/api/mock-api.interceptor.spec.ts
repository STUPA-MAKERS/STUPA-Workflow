import { TestBed } from '@angular/core/testing';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ApiClient } from './api-client.service';
import { USE_MOCK_API } from './api.config';
import { mockApiInterceptor } from './mock-api.interceptor';

describe('mockApiInterceptor', () => {
  function setup(useMock: boolean): { api: ApiClient; http: HttpTestingController } {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([mockApiInterceptor])),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: useMock },
      ],
    });
    return { api: TestBed.inject(ApiClient), http: TestBed.inject(HttpTestingController) };
  }

  it('short-circuits known GET endpoints with canned, mapped data', (done) => {
    const { api, http } = setup(true);
    api.applicationTypes().subscribe((types) => {
      expect(types.length).toBeGreaterThan(0);
      // mapper applied to the wire Page → view shape with hasBudget
      expect(typeof types[0].hasBudget).toBe('boolean');
      done();
    });
    http.expectNone('/api/application-types'); // handled by the mock, never hits the backend
  });

  it('passes through when the mock is disabled', () => {
    const { api, http } = setup(false);
    api.applicationTypes().subscribe();
    http.expectOne('/api/application-types').flush({ items: [], total: 0, limit: 20, offset: 0 });
    http.verify();
  });

  it('serves the effective form (with sections) for the apply wizard', (done) => {
    const { api, http } = setup(true);
    api.effectiveForm('11111111-1111-1111-1111-111111111111').subscribe((form) => {
      expect(form.sections.length).toBeGreaterThan(0);
      expect(form.budgetPotId).toBeTruthy();
      done();
    });
    http.expectNone((r) => r.url.includes('/form'));
  });

  it('creates an application returning an applicationId', (done) => {
    const { api } = setup(true);
    api
      .createApplication({
        typeId: '11111111-1111-1111-1111-111111111111',
        data: { title: 'X' },
        applicantEmail: 'a@b.de',
        lang: 'de',
        altcha: 'sol',
      })
      .subscribe((created) => {
        expect(created.applicationId).toBeTruthy();
        done();
      });
  });

  it('verifies a magic-link token and returns an applicant scope', (done) => {
    const { api } = setup(true);
    api.verifyMagicLink('tok').subscribe((res) => {
      expect(res.scope).toBe('edit');
      expect(res.application_id).toBeTruthy();
      done();
    });
  });

  it('serves a single application, its timeline and comments, and accepts a PATCH', (done) => {
    const { api } = setup(true);
    api.getApplication('33333333-3333-3333-3333-333333333333').subscribe((app) => {
      expect(app.state?.editAllowed).toBe(true);
      // i18n label resolved by the mapper (de default)
      expect(app.state?.label).toBe('Eingereicht');
      api.timeline(app.id).subscribe((t) => {
        expect(t.length).toBeGreaterThan(0);
        expect(t[0].label).toBeTruthy();
        api.comments(app.id).subscribe((c) => {
          expect(c.length).toBeGreaterThan(0);
          expect(c[0].isPublic).toBe(true);
          api.addComment(app.id, 'Neu').subscribe((created) => {
            expect(created.isPublic).toBe(true);
            api.updateApplication(app.id, { title: 'Y' }).subscribe((updated) => {
              expect(updated.data).toEqual({ title: 'Y' });
              done();
            });
          });
        });
      });
    });
  });
});
