import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom } from 'rxjs';
import { USE_MOCK_API } from '@core/api/api.config';
import { AdminApiService } from './admin-api.service';
import type { Branding, WebhookConfig } from './admin.models';

describe('AdminApiService — mock mode', () => {
  function svc(): AdminApiService {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: true },
      ],
    });
    return TestBed.inject(AdminApiService);
  }

  it('lists seeded webhooks and persists a new one', (done) => {
    const s = svc();
    s.listWebhooks().subscribe((hooks) => {
      expect(hooks.length).toBeGreaterThan(0);
      const fresh: WebhookConfig = { id: '', name: 'X', url: 'https://x', events: ['vote_opened'], active: true };
      s.saveWebhook(fresh).subscribe((saved) => {
        expect(saved.id).toBeTruthy();
        s.listWebhooks().subscribe((after) => {
          expect(after.some((h) => h.name === 'X')).toBe(true);
          done();
        });
      });
    });
  });

  it('covers schemas, versions, gremien, roles and rule upsert in mock mode', async () => {
    const s = svc();
    const schemas = await firstValueFrom(s.configSchemas());
    expect(Object.keys(schemas)).toContain('FormFieldDef');
    expect((await firstValueFrom(s.createFormVersion('t', []))).id).toBeTruthy();
    expect((await firstValueFrom(s.createFlowVersion('t', { states: [], transitions: [] }))).id).toBeTruthy();
    expect((await firstValueFrom(s.listGremien())).length).toBeGreaterThan(0);
    expect(await firstValueFrom(s.listRoles())).toEqual([]);

    const rules = await firstValueFrom(s.listNotificationRules());
    const created = await firstValueFrom(
      s.saveNotificationRule({ id: '', event: 'vote_opened', recipients: [{ kind: 'applicant' }], templateKey: 't', enabled: true }),
    );
    expect(created.id).toBeTruthy();
    // update existing → upsert update branch
    const updated = await firstValueFrom(s.saveNotificationRule({ ...rules[0], templateKey: 'changed' }));
    expect(updated.templateKey).toBe('changed');
    // update existing webhook → upsert update branch
    const hooks = await firstValueFrom(s.listWebhooks());
    const wh = await firstValueFrom(s.saveWebhook({ ...hooks[0], name: 'renamed' }));
    expect(wh.name).toBe('renamed');
  });

  it('saves a branding draft and activates a new version', (done) => {
    const s = svc();
    s.getSiteConfig().subscribe((cfg) => {
      expect(cfg.version).toBe(1);
      expect(cfg.hasDraftChanges).toBe(false);
      const draft: Branding = { ...cfg.draft, copyright: { de: 'Neu', en: 'New' } };
      s.saveBrandingDraft(draft).subscribe((withDraft) => {
        expect(withDraft.hasDraftChanges).toBe(true);
        s.activateBranding().subscribe((activated) => {
          expect(activated.version).toBe(2);
          expect(activated.active.copyright['de']).toBe('Neu');
          expect(activated.hasDraftChanges).toBe(false);
          done();
        });
      });
    });
  });
});

describe('AdminApiService — real mode (contract)', () => {
  let http: HttpTestingController;
  let s: AdminApiService;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: false },
      ],
    });
    s = TestBed.inject(AdminApiService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('GETs config schemas from the documented path', () => {
    s.configSchemas().subscribe();
    http.expectOne('/api/admin/config-schemas').flush({});
  });

  it('POSTs a flow version to the documented path', () => {
    s.createFlowVersion('t1', { states: [], transitions: [] }).subscribe();
    const req = http.expectOne('/api/admin/application-types/t1/flow-versions');
    expect(req.request.method).toBe('POST');
    req.flush({ id: 'fv1' });
  });

  it('POSTs a new webhook and PATCHes an existing one', () => {
    s.saveWebhook({ id: '', name: 'n', url: 'https://h', events: ['vote_opened'], active: true }).subscribe();
    expect(http.expectOne('/api/admin/webhooks').request.method).toBe('POST');

    s.saveWebhook({ id: 'wh-9', name: 'n', url: 'https://h', events: ['vote_opened'], active: true }).subscribe();
    expect(http.expectOne('/api/admin/webhooks/wh-9').request.method).toBe('PATCH');
  });

  it('wires the remaining admin endpoints to their documented paths', () => {
    s.createFormVersion('t2', []).subscribe();
    expect(http.expectOne('/api/admin/application-types/t2/form-versions').request.method).toBe('POST');

    s.listGremien().subscribe();
    http.expectOne('/api/admin/gremien').flush([]);
    s.listRoles().subscribe();
    http.expectOne('/api/admin/roles').flush([]);
    s.listNotificationRules().subscribe();
    http.expectOne('/api/admin/notification-rules').flush([]);

    s.saveNotificationRule({ id: '', event: 'vote_opened', recipients: [{ kind: 'applicant' }], templateKey: 't', enabled: true }).subscribe();
    expect(http.expectOne('/api/admin/notification-rules').request.method).toBe('POST');
    s.saveNotificationRule({ id: 'nr-2', event: 'vote_opened', recipients: [{ kind: 'applicant' }], templateKey: 't', enabled: true }).subscribe();
    expect(http.expectOne('/api/admin/notification-rules/nr-2').request.method).toBe('PATCH');

    s.getSiteConfig().subscribe();
    http.expectOne('/api/admin/site-config').flush({});
    s.saveBrandingDraft({} as never).subscribe();
    expect(http.expectOne('/api/admin/site-config/draft').request.method).toBe('PUT');
    s.activateBranding().subscribe();
    expect(http.expectOne('/api/admin/site-config/activate').request.method).toBe('POST');
  });
});
