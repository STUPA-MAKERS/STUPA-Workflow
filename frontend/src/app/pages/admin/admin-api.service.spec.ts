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
    // #105 — Gremien anlegen/bearbeiten im Mock-Store.
    const before = (await firstValueFrom(s.listGremien())).length;
    const newGremium = await firstValueFrom(
      s.createGremium({ name: 'Neu', slug: 'neu', cdVariant: 'stupa', defaultLang: 'de' }),
    );
    expect(newGremium.name).toBe('Neu');
    expect((await firstValueFrom(s.listGremien())).length).toBe(before + 1);
    const edited = await firstValueFrom(s.updateGremium(newGremium.id, { name: 'Geändert' }));
    expect(edited.name).toBe('Geändert');
    expect((await firstValueFrom(s.listRoles())).length).toBeGreaterThan(0);

    // update existing webhook → upsert update branch
    const hooks = await firstValueFrom(s.listWebhooks());
    const wh = await firstValueFrom(s.saveWebhook({ ...hooks[0], name: 'renamed' }));
    expect(wh.name).toBe('renamed');
  });

  it('manages principals, role assignments and permissions in mock mode (#72)', async () => {
    const s = svc();
    const all = await firstValueFrom(s.listPrincipals());
    expect(all.length).toBeGreaterThan(0);
    // search filters by name/email/sub
    const hit = await firstValueFrom(s.listPrincipals('robin'));
    expect(hit.every((p) => /robin/i.test(p.sub + p.email + p.displayName))).toBe(true);

    const perms = await firstValueFrom(s.listPermissions());
    expect(perms).toContain('flow.configure');

    const target = all.find((p) => p.assignments.length === 0)!;
    const assignment = await firstValueFrom(
      s.assignRole({ principalId: target.id, roleId: 'r-member', validFrom: '2026-07-01T00:00:00Z', delegateVoting: true }),
    );
    expect(assignment.id).toBeTruthy();
    const afterAssign = await firstValueFrom(s.listPrincipals());
    expect(afterAssign.find((p) => p.id === target.id)!.assignments).toHaveLength(1);

    await firstValueFrom(s.revokeRole(assignment.id));
    const afterRevoke = await firstValueFrom(s.listPrincipals());
    expect(afterRevoke.find((p) => p.id === target.id)!.assignments).toHaveLength(0);

    const role = (await firstValueFrom(s.listRoles())).find((r) => r.key === 'member')!;
    const saved = await firstValueFrom(s.saveRolePermissions(role.id, [...role.permissions, 'flow.configure']));
    expect(saved.permissions).toContain('flow.configure');
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

    s.getSiteConfig().subscribe();
    http.expectOne('/api/admin/site-config').flush({});
    s.saveBrandingDraft({} as never).subscribe();
    expect(http.expectOne('/api/admin/site-config/draft').request.method).toBe('PUT');
    s.activateBranding().subscribe();
    expect(http.expectOne('/api/admin/site-config/activate').request.method).toBe('POST');
  });

  it('wires principal/role-assignment/permission endpoints (#72)', () => {
    s.listPrincipals().subscribe();
    expect(http.expectOne('/api/admin/principals').request.method).toBe('GET');
    s.listPrincipals('a x').subscribe();
    http.expectOne('/api/admin/principals?q=a%20x').flush([]);

    s.listPermissions().subscribe();
    http.expectOne('/api/admin/permissions').flush([]);

    s.assignRole({ principalId: 'p1', roleId: 'r1' }).subscribe();
    expect(http.expectOne('/api/admin/role-assignments').request.method).toBe('POST');

    s.revokeRole('a-9').subscribe();
    expect(http.expectOne('/api/admin/role-assignments/a-9').request.method).toBe('DELETE');

    s.saveRolePermissions('r-9', ['flow.configure']).subscribe();
    expect(http.expectOne('/api/admin/roles/r-9').request.method).toBe('PATCH');
  });
});
