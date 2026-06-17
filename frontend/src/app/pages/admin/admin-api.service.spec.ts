import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom } from 'rxjs';
import { USE_MOCK_API } from '@core/api/api.config';
import type { FormFieldDef } from '@core/api/models';
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

  it('GETs gremium options from the public /gremien path (#68)', () => {
    s.listGremienOptions().subscribe();
    http.expectOne('/api/gremien').flush([]);
  });

  it('PATCHes/DELETEs a gremium and gets/sets mail recipients (#105)', () => {
    s.updateGremium('g-9', { name: 'X' }).subscribe();
    expect(http.expectOne('/api/admin/gremien/g-9').request.method).toBe('PATCH');

    s.deleteGremium('g-9').subscribe();
    expect(http.expectOne('/api/admin/gremien/g-9').request.method).toBe('DELETE');

    s.createGremium({ name: 'X', slug: 'x', cdVariant: 'stupa', defaultLang: 'de' }).subscribe();
    expect(http.expectOne('/api/admin/gremien').request.method).toBe('POST');

    s.getGremiumMailRecipients('g-9').subscribe();
    expect(http.expectOne('/api/admin/gremien/g-9/mail-recipients').request.method).toBe('GET');

    let recv: string[] | undefined;
    s.setGremiumMailRecipients('g-9', ['a@b.org']).subscribe((r) => (recv = r.recipients));
    const put = http.expectOne('/api/admin/gremien/g-9/mail-recipients');
    expect(put.request.method).toBe('PUT');
    expect(put.request.body).toEqual({ recipients: ['a@b.org'] });
    put.flush({ recipients: ['a@b.org'] });
    expect(recv).toEqual(['a@b.org']);
  });

  it('wires OIDC group-mapping CRUD endpoints (#5-4)', () => {
    s.listGroupMappings().subscribe();
    http.expectOne('/api/admin/group-mappings').flush([]);

    s.createGroupMapping({ oidcGroup: 'g', roleId: 'r1' }).subscribe();
    expect(http.expectOne('/api/admin/group-mappings').request.method).toBe('POST');

    s.updateGroupMapping('gm-9', { oidcGroup: 'g2' }).subscribe();
    expect(http.expectOne('/api/admin/group-mappings/gm-9').request.method).toBe('PATCH');

    s.deleteGroupMapping('gm-9').subscribe();
    expect(http.expectOne('/api/admin/group-mappings/gm-9').request.method).toBe('DELETE');
  });

  it('wires mail-template endpoints (list/upsert/reset/preview) (#5-4/#12)', () => {
    s.listMailTemplates().subscribe();
    http.expectOne('/api/admin/mail-templates').flush([]);

    s.upsertMailTemplate({ key: 'k', subjectI18n: {}, bodyI18n: {}, bodyHtmlI18n: {} }).subscribe();
    expect(http.expectOne('/api/admin/mail-templates').request.method).toBe('PUT');

    s.resetMailTemplate('weird/key').subscribe();
    expect(http.expectOne('/api/admin/mail-templates/by-key/weird%2Fkey').request.method).toBe(
      'DELETE',
    );

    s.previewMailPayload({ subjectI18n: {}, bodyI18n: {}, bodyHtmlI18n: {}, lang: 'de', context: {} }).subscribe();
    expect(http.expectOne('/api/admin/mail-templates/preview').request.method).toBe('POST');
  });

  it('maps /application-types page to id+name options (#69)', () => {
    let out: { id: string; name: string }[] | undefined;
    s.listApplicationTypes().subscribe((o) => (out = o));
    http
      .expectOne('/api/application-types')
      .flush({ items: [{ id: 't1', name: 'Foo', extra: 1 }] });
    expect(out).toEqual([{ id: 't1', name: 'Foo' }]);
  });

  it('maps /admin/application-types to FormOverviewItem (active vs draft) (#75)', () => {
    let out: { status: string; name: unknown; gremiumId: unknown }[] | undefined;
    s.listForms().subscribe((o) => (out = o as never));
    http.expectOne('/api/admin/application-types').flush([
      { id: 't1', nameI18n: { de: 'Aktiv' }, gremiumId: 'g1', activeFormVersionId: 'fv-1' },
      { id: 't2' },
    ]);
    expect(out![0]).toEqual({ id: 't1', name: { de: 'Aktiv' }, gremiumId: 'g1', status: 'active', version: 0 });
    // missing nameI18n/gremiumId/activeFormVersionId → defaults + draft
    expect(out![1]).toEqual({ id: 't2', name: {}, gremiumId: null, status: 'draft', version: 0 });
  });

  it('maps listApplicationTypesFull with defaults for missing fields (#13)', () => {
    let out: { hasBudget: boolean; retentionMonths: unknown; activeFormVersionId: unknown }[] | undefined;
    s.listApplicationTypesFull().subscribe((o) => (out = o as never));
    http.expectOne('/api/admin/application-types').flush([
      { id: 't1', nameI18n: { de: 'X' }, gremiumId: 'g1', hasBudget: true, retentionMonths: 12, activeFormVersionId: 'fv' },
      { id: 't2' },
    ]);
    expect(out![0]).toEqual({ id: 't1', name: { de: 'X' }, gremiumId: 'g1', hasBudget: true, retentionMonths: 12, activeFormVersionId: 'fv' });
    expect(out![1]).toEqual({ id: 't2', name: {}, gremiumId: null, hasBudget: false, retentionMonths: null, activeFormVersionId: null });
  });

  it('POSTs a new application type and maps the wire response (#13)', () => {
    let created: { hasBudget: boolean; name: unknown } | undefined;
    s.createApplicationType({ key: 'k', name: { de: 'N' }, gremiumId: 'g1', hasBudget: true }).subscribe(
      (c) => (created = c as never),
    );
    const req = http.expectOne('/api/admin/application-types');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ key: 'k', nameI18n: { de: 'N' }, gremiumId: 'g1', hasBudget: true });
    req.flush({ id: 'new-1' });
    expect(created).toEqual({ id: 'new-1', name: {}, gremiumId: null, hasBudget: false, retentionMonths: null, activeFormVersionId: null });
  });

  it('POSTs an application type with default gremium/budget when omitted', () => {
    s.createApplicationType({ key: 'k', name: { de: 'N' } }).subscribe();
    const req = http.expectOne('/api/admin/application-types');
    expect(req.request.body).toEqual({ key: 'k', nameI18n: { de: 'N' }, gremiumId: null, hasBudget: false });
    req.flush({ id: 'x' });
  });

  it('PATCHes only the supplied application-type fields and DELETEs (#13)', () => {
    let done = false;
    s.updateApplicationType('t1', { name: { de: 'N' }, gremiumId: 'g1', hasBudget: false }).subscribe(
      () => (done = true),
    );
    const req = http.expectOne('/api/admin/application-types/t1');
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toEqual({ nameI18n: { de: 'N' }, gremiumId: 'g1', hasBudget: false });
    req.flush({});
    expect(done).toBe(true);

    // empty body → no keys set
    s.updateApplicationType('t1', {}).subscribe();
    expect(http.expectOne('/api/admin/application-types/t1').request.body).toEqual({});

    let del = false;
    s.deleteApplicationType('t1').subscribe(() => (del = true));
    const dreq = http.expectOne('/api/admin/application-types/t1');
    expect(dreq.request.method).toBe('DELETE');
    dreq.flush({});
    expect(del).toBe(true);
  });

  it('GETs the latest form draft, sets active and global flow endpoints', () => {
    s.getFormDraft('t1').subscribe();
    http.expectOne('/api/admin/application-types/t1/form-versions/latest').flush({ applicationTypeId: 't1', fields: [] });

    s.setFormActive('t1', true).subscribe();
    const req = http.expectOne('/api/admin/application-types/t1/form-active');
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toEqual({ active: true });
    req.flush({ applicationTypeId: 't1', fields: [] });

    s.getGlobalFlow().subscribe();
    http.expectOne('/api/admin/flow-versions/global').flush(null);

    s.createGlobalFlowVersion({ states: [], transitions: [] }).subscribe();
    const fl = http.expectOne('/api/admin/flow-versions/global');
    expect(fl.request.method).toBe('POST');
    expect(fl.request.body).toEqual({ graph: { states: [], transitions: [] } });
    fl.flush({ id: 'g-1' });
  });

  it('POSTs a form version with description default null', () => {
    s.createFormVersion('t1', [{ key: 'a', type: 'text', label: { de: 'A' } }]).subscribe();
    const req = http.expectOne('/api/admin/application-types/t1/form-versions');
    expect(req.request.body).toEqual({ fields: [{ key: 'a', type: 'text', label: { de: 'A' } }], description: null });
    req.flush({ id: 'fv-1' });

    s.createFormVersion('t1', [], { de: 'D' }).subscribe();
    expect(http.expectOne('/api/admin/application-types/t1/form-versions').request.body).toEqual({
      fields: [],
      description: { de: 'D' },
    });
  });

  it('wires gremium-role CRUD + permission helper (#42/#62)', () => {
    s.listGremiumRoles('g1').subscribe();
    http.expectOne('/api/admin/gremien/g1/roles').flush([]);

    s.createGremiumRole('g1', { key: 'k', name: { de: 'N' } }).subscribe();
    expect(http.expectOne('/api/admin/gremien/g1/roles').request.method).toBe('POST');

    s.updateGremiumRole('gr-9', { name: { de: 'N2' } }).subscribe();
    expect(http.expectOne('/api/admin/gremium-roles/gr-9').request.method).toBe('PATCH');

    // helper delegates to updateGremiumRole
    s.saveGremiumRolePermissions('gr-9', ['vote.cast']).subscribe();
    const pr = http.expectOne('/api/admin/gremium-roles/gr-9');
    expect(pr.request.body).toEqual({ permissions: ['vote.cast'] });
    pr.flush({ id: 'gr-9', gremiumId: 'g1', key: 'k', name: {} });

    s.deleteGremiumRole('gr-9').subscribe();
    expect(http.expectOne('/api/admin/gremium-roles/gr-9').request.method).toBe('DELETE');
  });

  it('wires deadline-policy CRUD endpoints', () => {
    s.listDeadlinePolicies().subscribe();
    http.expectOne('/api/admin/deadline-policies').flush([]);

    s.createDeadlinePolicy({ key: 'k', label: { de: 'L' }, kind: 'absolute' }).subscribe();
    expect(http.expectOne('/api/admin/deadline-policies').request.method).toBe('POST');

    s.updateDeadlinePolicy('dp-9', { offsetDays: 3 }).subscribe();
    expect(http.expectOne('/api/admin/deadline-policies/dp-9').request.method).toBe('PATCH');

    s.deleteDeadlinePolicy('dp-9').subscribe();
    expect(http.expectOne('/api/admin/deadline-policies/dp-9').request.method).toBe('DELETE');
  });

  it('wires gremium-membership endpoints', () => {
    s.listGremiumMemberships('g1').subscribe();
    http.expectOne('/api/admin/gremien/g1/memberships').flush([]);

    s.createGremiumMembership('g1', { principalId: 'p1', gremiumRoleId: 'gr1', validFrom: null, validUntil: null }).subscribe();
    expect(http.expectOne('/api/admin/gremien/g1/memberships').request.method).toBe('POST');

    s.deleteGremiumMembership('gm-9').subscribe();
    expect(http.expectOne('/api/admin/gremium-memberships/gm-9').request.method).toBe('DELETE');
  });

  it('builds audit-log query params (defaults and all filters)', () => {
    s.listAuditLog().subscribe();
    const def = http.expectOne((r) => r.url === '/api/admin/audit');
    expect(def.request.params.get('limit')).toBe('50');
    expect(def.request.params.get('before')).toBeNull();
    def.flush({ items: [], nextCursor: null, hasMore: false });

    s.listAuditLog({ limit: 10, before: 99, action: 'x', actor: 'kc|a', since: 's', until: 'u' }).subscribe();
    const all = http.expectOne((r) => r.url === '/api/admin/audit');
    expect(all.request.params.get('limit')).toBe('10');
    expect(all.request.params.get('before')).toBe('99');
    expect(all.request.params.get('action')).toBe('x');
    expect(all.request.params.get('actor')).toBe('kc|a');
    expect(all.request.params.get('since')).toBe('s');
    expect(all.request.params.get('until')).toBe('u');
    all.flush({ items: [], nextCursor: null, hasMore: false });

    // before: 0 is a valid cursor (!= null) — must be emitted
    s.listAuditLog({ before: 0 }).subscribe();
    const zero = http.expectOne((r) => r.url === '/api/admin/audit');
    expect(zero.request.params.get('before')).toBe('0');
    zero.flush({ items: [], nextCursor: null, hasMore: false });

    s.listAuditActors().subscribe();
    http.expectOne('/api/admin/audit/actors').flush([]);
  });

  it('GETs/PUTs notification settings', () => {
    s.getNotificationSettings().subscribe();
    http.expectOne('/api/admin/notification-settings').flush({ taskReminderEnabled: true, taskReminderAfterDays: 5, taskReminderRepeatDays: 7 });

    s.putNotificationSettings({ taskReminderEnabled: false }).subscribe();
    const req = http.expectOne('/api/admin/notification-settings');
    expect(req.request.method).toBe('PUT');
    req.flush({ taskReminderEnabled: false, taskReminderAfterDays: 5, taskReminderRepeatDays: 7 });
  });

  it('wires DSGVO/privacy erasure endpoints', () => {
    s.listErasures().subscribe();
    const noFilter = http.expectOne((r) => r.url === '/api/admin/privacy/erasures');
    expect(noFilter.request.params.get('status')).toBeNull();
    noFilter.flush([]);

    s.listErasures('open').subscribe();
    const filtered = http.expectOne((r) => r.url === '/api/admin/privacy/erasures');
    expect(filtered.request.params.get('status')).toBe('open');
    filtered.flush([]);

    s.executeErasure('e-1').subscribe();
    expect(http.expectOne('/api/admin/privacy/erasures/e-1/execute').request.method).toBe('POST');

    s.rejectErasure('e-1', 'nope').subscribe();
    const rej = http.expectOne('/api/admin/privacy/erasures/e-1/reject');
    expect(rej.request.body).toEqual({ reason: 'nope' });
    rej.flush({});

    // reason omitted → null
    s.rejectErasure('e-1').subscribe();
    expect(http.expectOne('/api/admin/privacy/erasures/e-1/reject').request.body).toEqual({ reason: null });

    s.erasePrincipal('p-1').subscribe();
    expect(http.expectOne('/api/admin/privacy/principals/p-1/erase').request.method).toBe('POST');
  });

  it('PATCHes renameRole/createRole/setPrincipalActive, DELETEs role, GETs webhooks', () => {
    s.renameRole('r-9', { de: 'Neu' }).subscribe();
    const rn = http.expectOne('/api/admin/roles/r-9');
    expect(rn.request.method).toBe('PATCH');
    expect(rn.request.body).toEqual({ label: { de: 'Neu' } });
    rn.flush({ id: 'r-9', key: 'k', label: { de: 'Neu' }, permissions: [] });

    s.createRole({ key: 'k', label: { de: 'K' }, permissions: ['x'] }).subscribe();
    const cr = http.expectOne('/api/admin/roles');
    expect(cr.request.method).toBe('POST');
    cr.flush({ id: 'r-new', key: 'k', label: { de: 'K' }, permissions: ['x'] });

    s.setPrincipalActive('p-9', false).subscribe();
    const sp = http.expectOne('/api/admin/principals/p-9');
    expect(sp.request.method).toBe('PATCH');
    expect(sp.request.body).toEqual({ active: false });
    sp.flush({ id: 'p-9', sub: 's', assignments: [] });

    s.deleteRole('r-9').subscribe();
    expect(http.expectOne('/api/admin/roles/r-9').request.method).toBe('DELETE');

    s.listWebhooks().subscribe();
    http.expectOne('/api/admin/webhooks').flush([]);
  });

  it('GETs/PUTs privacy settings and downloads the Auskunft blob', () => {
    s.getPrivacySettings().subscribe();
    http.expectOne('/api/admin/privacy/settings').flush({ defaultRetentionMonths: 24 });

    s.putPrivacySettings({ defaultRetentionMonths: 36 }).subscribe();
    const put = http.expectOne('/api/admin/privacy/settings');
    expect(put.request.method).toBe('PUT');
    put.flush({ defaultRetentionMonths: 36 });

    s.downloadAuskunft('a@b.org').subscribe();
    const dl = http.expectOne((r) => r.url === '/api/admin/privacy/auskunft');
    expect(dl.request.params.get('email')).toBe('a@b.org');
    expect(dl.request.responseType).toBe('blob');
    dl.flush(new Blob([]));
  });
});

describe('AdminApiService — mock mode, exhaustive store branches', () => {
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

  it('lists public gremium options and seeded forms/app-types', async () => {
    const s = svc();
    expect((await firstValueFrom(s.listGremienOptions())).length).toBeGreaterThan(0);
    expect((await firstValueFrom(s.listForms())).length).toBeGreaterThan(0);
    expect((await firstValueFrom(s.listApplicationTypes())).length).toBe(2);
    expect((await firstValueFrom(s.listApplicationTypesFull())).length).toBeGreaterThan(0);
  });

  it('deletes a gremium and returns empty mail recipients', async () => {
    const s = svc();
    const first = (await firstValueFrom(s.listGremien()))[0];
    await firstValueFrom(s.deleteGremium(first.id));
    expect((await firstValueFrom(s.listGremien())).some((g) => g.id === first.id)).toBe(false);
    expect(await firstValueFrom(s.getGremiumMailRecipients('g-x'))).toEqual({ recipients: [] });
    expect(await firstValueFrom(s.setGremiumMailRecipients('g-x', ['a@b']))).toEqual({ recipients: ['a@b'] });
  });

  it('updateGremium falls back to first gremium when id unknown', async () => {
    const s = svc();
    const all = await firstValueFrom(s.listGremien());
    const res = await firstValueFrom(s.updateGremium('does-not-exist', { name: 'Z' }));
    // unknown id → returns store[0] unchanged (not renamed)
    expect(res.id).toBe(all[0].id);
    expect(res.name).toBe(all[0].name);
  });

  it('renames a role, creates a role, and deletes it (#21/#38)', async () => {
    const s = svc();
    const roles = await firstValueFrom(s.listRoles());
    const renamed = await firstValueFrom(s.renameRole(roles[0].id, { de: 'Neu', en: 'New' }));
    expect(renamed.label['de']).toBe('Neu');

    const created = await firstValueFrom(s.createRole({ key: 'kk', label: { de: 'KK' } }));
    expect(created.key).toBe('kk');
    expect(created.permissions).toEqual([]);
    const withPerms = await firstValueFrom(s.createRole({ key: 'pp', label: { de: 'PP' }, permissions: ['flow.configure'] }));
    expect(withPerms.permissions).toEqual(['flow.configure']);

    await firstValueFrom(s.deleteRole(created.id));
    expect((await firstValueFrom(s.listRoles())).some((r) => r.id === created.id)).toBe(false);
  });

  it('activates/deactivates a principal, falling back when id unknown (#30)', async () => {
    const s = svc();
    const all = await firstValueFrom(s.listPrincipals());
    const updated = await firstValueFrom(s.setPrincipalActive(all[0].id, false));
    expect(updated.active).toBe(false);
    // unknown id → returns store[0] (no crash)
    const fallback = await firstValueFrom(s.setPrincipalActive('nope', true));
    expect(fallback.id).toBe(all[0].id);
  });

  it('assignRole with no validFrom/gremium uses defaults; revoke is a no-op when unknown', async () => {
    const s = svc();
    const target = (await firstValueFrom(s.listPrincipals())).find((p) => p.assignments.length === 0)!;
    const a = await firstValueFrom(s.assignRole({ principalId: target.id, roleId: 'r-member' }));
    expect(a.gremiumId).toBeNull();
    expect(a.validFrom).toBeNull();
    expect(a.validUntil).toBeNull();
    expect(a.delegateVoting).toBe(false);
    // revoke unknown id leaves assignments untouched (loops over all principals)
    await firstValueFrom(s.revokeRole('not-real'));
    expect((await firstValueFrom(s.listPrincipals())).find((p) => p.id === target.id)!.assignments.length).toBe(1);
  });

  it('returns an empty principal list when search matches nothing', async () => {
    const s = svc();
    expect(await firstValueFrom(s.listPrincipals('zzz-no-match'))).toEqual([]);
  });

  it('search tolerates principals with null email/displayName', async () => {
    const s = svc();
    const store = (s as unknown as { store: { principals: { id: string; sub: string; email: unknown; displayName: unknown; assignments: unknown[] }[] } }).store;
    store.principals.push({ id: 'p-null', sub: 'kc|nulluser', email: null, displayName: null, assignments: [] });
    // query that doesn't match sub → forces evaluation of the email/displayName `?? ''` branches
    const hits = await firstValueFrom(s.listPrincipals('nomatchwhatsoever'));
    expect(hits).toEqual([]);
    // a query matching only the sub still returns the null-field principal
    expect((await firstValueFrom(s.listPrincipals('nulluser'))).map((p) => p.id)).toContain('p-null');
  });

  it('saveRolePermissions / renameRole no-op safely when role id is unknown', async () => {
    const s = svc();
    const roles = await firstValueFrom(s.listRoles());
    // findIndex < 0 → no mutation; falls back to the first role (no crash)
    const sp = await firstValueFrom(s.saveRolePermissions('nope', ['x']));
    expect(sp.id).toBe(roles[0].id);
    // no role gained the bogus 'x' permission (no mutation happened)
    expect((await firstValueFrom(s.listRoles())).some((r) => r.permissions.includes('x'))).toBe(false);
    const rn = await firstValueFrom(s.renameRole('nope', { de: 'X' }));
    expect(rn.id).toBe(roles[0].id);
  });

  it('CRUDs application types in the mock store (#13)', async () => {
    const s = svc();
    const before = (await firstValueFrom(s.listApplicationTypesFull())).length;
    const created = await firstValueFrom(s.createApplicationType({ key: 'neu', name: { de: 'Neu' } }));
    expect(created.id).toBe('f-neu');
    expect(created.hasBudget).toBe(false);
    expect((await firstValueFrom(s.listApplicationTypesFull())).length).toBe(before + 1);

    // createApplicationType without a key → falls back to length index
    const noKey = await firstValueFrom(s.createApplicationType({ key: '', name: { de: 'X' }, gremiumId: 'g1', hasBudget: true }));
    expect(noKey.id).toMatch(/^f-/);
    expect(noKey.gremiumId).toBe('g1');
    expect(noKey.hasBudget).toBe(true);

    await firstValueFrom(s.updateApplicationType(created.id, { name: { de: 'Geändert' }, gremiumId: 'g-asta', hasBudget: true }));
    const after = (await firstValueFrom(s.listApplicationTypesFull())).find((t) => t.id === created.id)!;
    expect(after.name['de']).toBe('Geändert');
    expect(after.gremiumId).toBe('g-asta');
    expect(after.hasBudget).toBe(true);

    // update with empty body leaves the row untouched + unknown id is a no-op
    await firstValueFrom(s.updateApplicationType(created.id, {}));
    await firstValueFrom(s.updateApplicationType('ghost', { name: { de: 'X' } }));

    await firstValueFrom(s.deleteApplicationType(created.id));
    expect((await firstValueFrom(s.listApplicationTypesFull())).some((t) => t.id === created.id)).toBe(false);
  });

  it('loads a known form draft and an empty stub for an unknown type (#13)', async () => {
    const s = svc();
    const known = await firstValueFrom(s.getFormDraft('f-foerderung'));
    expect(known.fields.length).toBeGreaterThan(0);
    const empty = await firstValueFrom(s.getFormDraft('unknown-type'));
    expect(empty).toEqual({ applicationTypeId: 'unknown-type', fields: [] });
  });

  it('creates a form version, bumps the version, and toggles active (#13/#forms)', async () => {
    const s = svc();
    const fields: FormFieldDef[] = [{ key: 'a', type: 'text', label: { de: 'A' } }];
    const v1 = await firstValueFrom(s.createFormVersion('f-foerderung', fields, { de: 'D' }));
    expect(v1.id).toBe('formver-1');
    const draft = await firstValueFrom(s.getFormDraft('f-foerderung'));
    expect(draft.active).toBe(true);
    expect(draft.formVersionId).toBe('formver-1');

    // first version for a brand-new type (version starts at 1, description null)
    const fresh = await firstValueFrom(s.createFormVersion('brand-new', [], null));
    expect(fresh.id).toBe('formver-0');
    const freshDraft = await firstValueFrom(s.getFormDraft('brand-new'));
    expect(freshDraft.version).toBe(1);
    expect(freshDraft.description).toBeNull();

    const deactivated = await firstValueFrom(s.setFormActive('f-foerderung', false));
    expect(deactivated.active).toBe(false);
    // re-activating restores the type's activeFormVersionId from the draft
    const reactivated = await firstValueFrom(s.setFormActive('f-foerderung', true));
    expect(reactivated.active).toBe(true);
    const types = await firstValueFrom(s.listApplicationTypesFull());
    expect(types.find((t) => t.id === 'f-foerderung')!.activeFormVersionId).toBe('formver-1');

    // activate a draft that has no formVersionId → activeFormVersionId becomes null
    const store = (s as unknown as { store: { formDrafts: Record<string, { applicationTypeId: string; active?: boolean; fields: unknown[] }> } }).store;
    store.formDrafts['f-veranstaltung'] = { applicationTypeId: 'f-veranstaltung', fields: [] };
    const noVer = await firstValueFrom(s.setFormActive('f-veranstaltung', true));
    expect(noVer.active).toBe(true);
    expect((await firstValueFrom(s.listApplicationTypesFull())).find((t) => t.id === 'f-veranstaltung')!.activeFormVersionId).toBeNull();

    // setFormActive on a type with no draft yet → returns a synthesized stub
    const stub = await firstValueFrom(s.setFormActive('no-draft-type', true));
    expect(stub).toEqual({ applicationTypeId: 'no-draft-type', active: true, fields: [] });
  });

  it('returns null global flow and a deterministic mock flow id in mock mode (#28)', async () => {
    const s = svc();
    expect(await firstValueFrom(s.getGlobalFlow())).toBeNull();
    const created = await firstValueFrom(s.createGlobalFlowVersion({ states: [{ key: 's', label: {} }], transitions: [] }));
    expect(created.id).toBe('gflow-1');
  });

  it('CRUDs gremium-roles in the mock store (#42/#62)', async () => {
    const s = svc();
    expect(await firstValueFrom(s.listGremiumRoles('g-stupa'))).toEqual([]);
    const created = await firstValueFrom(s.createGremiumRole('g-stupa', { key: 'chair', name: { de: 'Vorsitz' } }));
    expect(created.gremiumId).toBe('g-stupa');
    expect((await firstValueFrom(s.listGremiumRoles('g-stupa'))).length).toBe(1);
    // filter excludes other gremium
    expect(await firstValueFrom(s.listGremiumRoles('g-asta'))).toEqual([]);

    const updated = await firstValueFrom(s.updateGremiumRole(created.id, { name: { de: 'Neu' } }));
    expect(updated.name['de']).toBe('Neu');
    // helper path
    const withPerms = await firstValueFrom(s.saveGremiumRolePermissions(created.id, ['vote.cast']));
    expect(withPerms.permissions).toEqual(['vote.cast']);
    // unknown id → synthesized fallback row (with name)
    const fallback = await firstValueFrom(s.updateGremiumRole('ghost', { name: { de: 'F' } }));
    expect(fallback.id).toBe('ghost');
    expect(fallback.name).toEqual({ de: 'F' });
    // unknown id with no name in body → fallback name defaults to {} (the `?? {}` branch)
    const fallbackNoName = await firstValueFrom(s.updateGremiumRole('ghost2', { permissions: ['x'] }));
    expect(fallbackNoName.id).toBe('ghost2');
    expect(fallbackNoName.name).toEqual({});

    await firstValueFrom(s.deleteGremiumRole(created.id));
    expect(await firstValueFrom(s.listGremiumRoles('g-stupa'))).toEqual([]);
  });

  it('deleteGremiumRole tolerates a nullish gremiumRoles store (defensive `?? []`)', async () => {
    const s = svc();
    const store = (s as unknown as { store: { gremiumRoles: unknown } }).store;
    store.gremiumRoles = undefined;
    await firstValueFrom(s.deleteGremiumRole('any'));
    // re-initialised to an array → no crash, list is empty
    expect(await firstValueFrom(s.listGremiumRoles('g-stupa'))).toEqual([]);
  });

  it('CRUDs deadline policies in the mock store', async () => {
    const s = svc();
    expect(await firstValueFrom(s.listDeadlinePolicies())).toEqual([]);
    const created = await firstValueFrom(s.createDeadlinePolicy({ key: 'sem', label: { de: 'Semester' }, kind: 'absolute' }));
    expect(created.id).toBe('dp-1');
    const updated = await firstValueFrom(s.updateDeadlinePolicy(created.id, { offsetDays: 5 }));
    expect(updated.offsetDays).toBe(5);
    // unknown id → synthesized fallback
    const fallback = await firstValueFrom(s.updateDeadlinePolicy('ghost', { offsetDays: 1 }));
    expect(fallback.id).toBe('ghost');
    await firstValueFrom(s.deleteDeadlinePolicy(created.id));
    expect(await firstValueFrom(s.listDeadlinePolicies())).toEqual([]);
  });

  it('returns empty memberships in mock mode', async () => {
    const s = svc();
    expect(await firstValueFrom(s.listGremiumMemberships('g-stupa'))).toEqual([]);
  });

  it('returns empty audit page/actors in mock mode', async () => {
    const s = svc();
    expect(await firstValueFrom(s.listAuditLog())).toEqual({ items: [], nextCursor: null, hasMore: false });
    expect(await firstValueFrom(s.listAuditActors())).toEqual([]);
  });

  it('returns default notification settings in mock mode', async () => {
    const s = svc();
    expect(await firstValueFrom(s.getNotificationSettings())).toEqual({
      taskReminderEnabled: true,
      taskReminderAfterDays: 5,
      taskReminderRepeatDays: 7,
    });
  });

  it('manages erasures and privacy settings in the mock store (DSGVO)', async () => {
    const s = svc();
    expect(await firstValueFrom(s.listErasures())).toEqual([]);
    expect(await firstValueFrom(s.listErasures('open'))).toEqual([]);

    // execute/reject on unknown id → synthesized {id} fallback, no crash
    const exec = await firstValueFrom(s.executeErasure('e-x'));
    expect(exec.id).toBe('e-x');
    const rej = await firstValueFrom(s.rejectErasure('e-x', 'reason'));
    expect(rej.id).toBe('e-x');
    const rejNull = await firstValueFrom(s.rejectErasure('e-x'));
    expect(rejNull.id).toBe('e-x');

    expect(await firstValueFrom(s.erasePrincipal('p-1'))).toBeUndefined();

    const settings = await firstValueFrom(s.getPrivacySettings());
    expect(settings.defaultRetentionMonths).toBe(24);
    const saved = await firstValueFrom(s.putPrivacySettings({ defaultRetentionMonths: 48 }));
    expect(saved.defaultRetentionMonths).toBe(48);
    // persisted in store
    expect((await firstValueFrom(s.getPrivacySettings())).defaultRetentionMonths).toBe(48);

    const blob = await firstValueFrom(s.downloadAuskunft('a@b.org'));
    expect(blob).toBeInstanceOf(Blob);
  });

  it('filters mock erasures by status when the store has rows', async () => {
    const s = svc();
    // seed the private store directly to exercise the status-filter branch
    const store = (s as unknown as { store: { erasures: { id: string; status: string }[] } }).store;
    store.erasures.push(
      { id: 'e-open', status: 'open' } as never,
      { id: 'e-done', status: 'executed' } as never,
    );
    expect((await firstValueFrom(s.listErasures())).length).toBe(2);
    const open = await firstValueFrom(s.listErasures('open'));
    expect(open.map((r) => r.id)).toEqual(['e-open']);

    // execute + reject existing rows take the mutation branch
    await firstValueFrom(s.executeErasure('e-open'));
    expect((await firstValueFrom(s.listErasures('executed'))).map((r) => r.id)).toContain('e-open');
    const rejected = await firstValueFrom(s.rejectErasure('e-done', 'r'));
    expect(rejected.status).toBe('rejected');
    expect(rejected.reason).toBe('r');
    const rejectedNull = await firstValueFrom(s.rejectErasure('e-done'));
    expect(rejectedNull.reason).toBeNull();
  });

  it('listGroupMappings/mail-templates always hit HTTP even in mock mode', () => {
    // these methods have no mock branch — they always call HttpClient
    const s = svc();
    const http = TestBed.inject(HttpTestingController);
    s.listGroupMappings().subscribe();
    http.expectOne('/api/admin/group-mappings').flush([]);
    s.listMailTemplates().subscribe();
    http.expectOne('/api/admin/mail-templates').flush([]);
    http.verify();
  });
});
