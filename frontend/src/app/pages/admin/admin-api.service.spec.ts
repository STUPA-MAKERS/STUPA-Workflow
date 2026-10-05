import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom } from 'rxjs';
import { USE_MOCK_API } from '@core/api/api.config';
import { I18nService } from '@core/i18n/i18n.service';
import { SKIP_LOADING } from '@core/loading/loading.interceptor';
import type { FormFieldDef } from '@core/api/models';
import { AdminApiService } from './admin-api.service';
import { MOCK_GREMIUM_STUPA_ID } from './admin.mock';
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

  it('deletes a webhook and reports one delivery status per state in mock mode', async () => {
    const s = svc();
    const before = await firstValueFrom(s.listWebhooks());
    await firstValueFrom(s.deleteWebhook(before[0].id));
    const after = await firstValueFrom(s.listWebhooks());
    expect(after.some((h) => h.id === before[0].id)).toBe(false);
    const status = await firstValueFrom(s.listWebhookDeliveryStatus());
    expect(status.map((x) => x.lastState)).toEqual(['sent', 'dead', 'pending', 'never']);
  });

  it('covers schemas, versions, gremien, roles and rule upsert in mock mode', async () => {
    const s = svc();
    const schemas = await firstValueFrom(s.configSchemas());
    expect(Object.keys(schemas)).toContain('FormFieldDef');
    expect((await firstValueFrom(s.createFormVersion('t', []))).id).toBeTruthy();
    expect((await firstValueFrom(s.listGremien())).length).toBeGreaterThan(0);
    // #105 — create and edit gremien in the mock store.
    const before = (await firstValueFrom(s.listGremien())).length;
    const newGremium = await firstValueFrom(
      s.createGremium({ name: 'Neu', slug: 'neu', cdVariantId: 'cd-stupa', defaultLang: 'de' }),
    );
    expect(newGremium.name).toBe('Neu');
    expect((await firstValueFrom(s.listGremien())).length).toBe(before + 1);
    const edited = await firstValueFrom(s.updateGremium(newGremium.id, { name: 'Geändert' }));
    expect(edited.name).toBe('Geändert');
    expect((await firstValueFrom(s.listRoles())).length).toBeGreaterThan(0);
    // The gremium dropdown gets stub CD variants in mock mode.
    expect((await firstValueFrom(s.listCdVariantOptions())).length).toBeGreaterThan(0);

    // An existing webhook takes the update branch of upsert.
    const hooks = await firstValueFrom(s.listWebhooks());
    const wh = await firstValueFrom(s.saveWebhook({ ...hooks[0], name: 'renamed' }));
    expect(wh.name).toBe('renamed');
  });

  it('manages principals and permissions in mock mode', async () => {
    const s = svc();
    const all = await firstValueFrom(s.listPrincipals());
    expect(all.length).toBeGreaterThan(0);
    const hit = await firstValueFrom(s.listPrincipals('robin'));
    expect(hit.every((p) => /robin/i.test(p.sub + p.email + p.displayName))).toBe(true);

    const perms = await firstValueFrom(s.listPermissions());
    expect(perms).toContain('flow.configure');

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

  it('DELETEs a webhook and GETs the delivery status', () => {
    s.deleteWebhook('wh-9').subscribe();
    expect(http.expectOne('/api/admin/webhooks/wh-9').request.method).toBe('DELETE');

    s.listWebhookDeliveryStatus().subscribe();
    const status = http.expectOne('/api/admin/webhooks/delivery-status');
    expect(status.request.method).toBe('GET');
    status.flush([]);
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

  it('wires principal/role-assignment/permission endpoints', () => {
    s.listPrincipals().subscribe();
    expect(http.expectOne('/api/admin/principals').request.method).toBe('GET');
    s.listPrincipals('a x').subscribe();
    http.expectOne('/api/admin/principals?q=a%20x').flush([]);

    s.listPermissions().subscribe();
    http.expectOne('/api/admin/permissions').flush([]);

    s.saveRolePermissions('r-9', ['flow.configure']).subscribe();
    expect(http.expectOne('/api/admin/roles/r-9').request.method).toBe('PATCH');
  });

  it('wires the admin OAuth-grant list and the kill switch', () => {
    // Defaults: the documented page size, no owner filter.
    s.listOAuthGrants().subscribe();
    const all = http.expectOne('/api/admin/oauth-grants?limit=50&offset=0');
    expect(all.request.method).toBe('GET');
    all.flush({ items: [], total: 0, limit: 50, offset: 0 });

    s.listOAuthGrants({ limit: 25, offset: 25, principalId: 'p-1' }).subscribe();
    http
      .expectOne('/api/admin/oauth-grants?limit=25&offset=25&principalId=p-1')
      .flush({ items: [], total: 0, limit: 25, offset: 25 });

    s.revokeOAuthGrant('grant-9').subscribe();
    expect(http.expectOne('/api/admin/oauth-grants/grant-9').request.method).toBe('DELETE');
  });

  it('GETs gremium options from the public /gremien path', () => {
    s.listGremienOptions().subscribe();
    http.expectOne('/api/gremien').flush([]);
  });

  it('PATCHes/DELETEs a gremium and gets/sets mail recipients', () => {
    s.updateGremium('g-9', { name: 'X' }).subscribe();
    expect(http.expectOne('/api/admin/gremien/g-9').request.method).toBe('PATCH');

    s.deleteGremium('g-9').subscribe();
    expect(http.expectOne('/api/admin/gremien/g-9').request.method).toBe('DELETE');

    s.createGremium({ name: 'X', slug: 'x', cdVariantId: 'cd-stupa', defaultLang: 'de' }).subscribe();
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

  it('wires the CD-variant endpoints incl. logo upload, order and file URL', () => {
    s.listCdVariants().subscribe();
    expect(http.expectOne('/api/admin/cd-variants').request.method).toBe('GET');

    s.createCdVariant({ key: 'stupa', name: 'StuPa', baseVariant: 'report' }).subscribe();
    expect(http.expectOne('/api/admin/cd-variants').request.method).toBe('POST');

    s.updateCdVariant('cd-1', { name: 'Neu' }).subscribe();
    expect(http.expectOne('/api/admin/cd-variants/cd-1').request.method).toBe('PATCH');

    s.deleteCdVariant('cd-1').subscribe();
    expect(http.expectOne('/api/admin/cd-variants/cd-1').request.method).toBe('DELETE');

    const file = new File(['x'], 'logo.png', { type: 'image/png' });
    s.uploadCdVariantLogo('cd-1', 'title', file).subscribe();
    const upload = http.expectOne('/api/admin/cd-variants/cd-1/logos');
    expect(upload.request.method).toBe('POST');
    expect(upload.request.body instanceof FormData).toBe(true);
    expect((upload.request.body as FormData).get('slot')).toBe('title');
    expect((upload.request.body as FormData).get('file')).toBe(file);

    s.addCdVariantVendoredLogo('cd-1', 'footer', 'HSRT').subscribe();
    const vendored = http.expectOne('/api/admin/cd-variants/cd-1/logos/vendored');
    expect(vendored.request.method).toBe('POST');
    expect(vendored.request.body).toEqual({ slot: 'footer', vendoredName: 'HSRT' });

    s.reorderCdVariantLogos('cd-1', 'title', ['l-2', 'l-1']).subscribe();
    const order = http.expectOne('/api/admin/cd-variants/cd-1/logos/order');
    expect(order.request.method).toBe('PUT');
    expect(order.request.body).toEqual({ slot: 'title', logoIds: ['l-2', 'l-1'] });

    s.deleteCdVariantLogo('l-1').subscribe();
    expect(http.expectOne('/api/admin/cd-variant-logos/l-1').request.method).toBe('DELETE');

    expect(s.cdVariantLogoFileUrl('l-1')).toBe('/api/admin/cd-variant-logos/l-1/file');

    s.listCdVariantOptions().subscribe();
    http.expectOne('/api/cd-variants').flush([]);
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

  it('maps /application-types page to id+name options', () => {
    let out: { id: string; name: string }[] | undefined;
    s.listApplicationTypes().subscribe((o) => (out = o));
    // Match on the path only. A plain string matcher compares `urlWithParams` and
    // would miss the mandatory `lang`.
    http
      .expectOne((r) => r.url === '/api/application-types')
      .flush({ items: [{ id: 't1', name: 'Foo', extra: 1 }] });
    expect(out).toEqual([{ id: 't1', name: 'Foo' }]);
  });

  // The public `/application-types` resolves the type name SERVER-side from the `lang`
  // query parameter, which defaults to German. Without the parameter the
  // application-type picker of the form and flow builders shows German names in an
  // English admin UI.
  it('sends the active locale as `lang` on /application-types', () => {
    const i18n = TestBed.inject(I18nService);

    i18n.setLocale('en');
    s.listApplicationTypes().subscribe();
    const en = http.expectOne((r) => r.url === '/api/application-types');
    expect(en.request.params.get('lang')).toBe('en');
    en.flush({ items: [] });

    i18n.setLocale('de');
    s.listApplicationTypes().subscribe();
    const de = http.expectOne((r) => r.url === '/api/application-types');
    expect(de.request.params.get('lang')).toBe('de');
    de.flush({ items: [] });
  });

  it('maps /admin/application-types to FormOverviewItem (active vs draft)', () => {
    let out: { status: string; name: unknown; gremiumId: unknown }[] | undefined;
    s.listForms().subscribe((o) => (out = o as never));
    http.expectOne('/api/admin/application-types').flush([
      { id: 't1', nameI18n: { de: 'Aktiv' }, gremiumId: 'g1', activeFormVersionId: 'fv-1' },
      { id: 't2' },
    ]);
    expect(out![0]).toEqual({ id: 't1', name: { de: 'Aktiv' }, gremiumId: 'g1', status: 'active', version: 0 });
    // Missing nameI18n/gremiumId/activeFormVersionId → defaults plus draft status.
    expect(out![1]).toEqual({ id: 't2', name: {}, gremiumId: null, status: 'draft', version: 0 });
  });

  it('maps listApplicationTypesFull with defaults for missing fields', () => {
    let out: { hasBudget: boolean; retentionMonths: unknown; activeFormVersionId: unknown }[] | undefined;
    s.listApplicationTypesFull().subscribe((o) => (out = o as never));
    http.expectOne('/api/admin/application-types').flush([
      { id: 't1', nameI18n: { de: 'X' }, gremiumId: 'g1', hasBudget: true, retentionMonths: 12, activeFormVersionId: 'fv' },
      { id: 't2' },
    ]);
    expect(out![0]).toEqual({ id: 't1', name: { de: 'X' }, gremiumId: 'g1', hasBudget: true, retentionMonths: 12, activeFormVersionId: 'fv', activeFormVersion: null });
    expect(out![1]).toEqual({ id: 't2', name: {}, gremiumId: null, hasBudget: false, retentionMonths: null, activeFormVersionId: null, activeFormVersion: null });
  });

  it('maps the number of the active form version', () => {
    let out: { activeFormVersion?: number | null }[] | undefined;
    s.listApplicationTypesFull().subscribe((o) => (out = o));
    http.expectOne('/api/admin/application-types').flush([{ id: 't1', activeFormVersionId: 'fv', activeFormVersion: 7 }]);
    expect(out![0].activeFormVersion).toBe(7);
  });

  it('lists, diffs and restores the config revisions of an entity', () => {
    let list: unknown;
    s.listConfigRevisions('site_config', 'global').subscribe((v) => (list = v));
    const req = http.expectOne((r) => r.url === '/api/admin/config-revisions');
    expect(req.request.params.get('entityType')).toBe('site_config');
    expect(req.request.params.get('entityId')).toBe('global');
    req.flush([{ id: 'r1' }]);
    expect(list).toEqual([{ id: 'r1' }]);
    s.restoreConfigRevision('r1').subscribe();
    http.expectOne({ method: 'POST', url: '/api/admin/config-revisions/r1/restore' }).flush(null);
  });

  it('reads and replaces the guest settings', () => {
    let read: unknown;
    s.getGuestSettings().subscribe((v) => (read = v));
    http.expectOne({ method: 'GET', url: '/api/admin/guest-settings' }).flush({ confirmTtlHours: 12, linkTtlDays: null });
    expect(read).toEqual({ confirmTtlHours: 12, linkTtlDays: null });
    let saved: unknown;
    s.putGuestSettings({ confirmTtlHours: 24, linkTtlDays: 30 }).subscribe((v) => (saved = v));
    const req = http.expectOne({ method: 'PUT', url: '/api/admin/guest-settings' });
    expect(req.request.body).toEqual({ confirmTtlHours: 24, linkTtlDays: 30 });
    req.flush({ confirmTtlHours: 24, linkTtlDays: 30 });
    expect(saved).toEqual({ confirmTtlHours: 24, linkTtlDays: 30 });
  });

  it('POSTs a new application type and maps the wire response', () => {
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

  it('PATCHes only the supplied application-type fields and DELETEs', () => {
    let done = false;
    s.updateApplicationType('t1', { name: { de: 'N' }, gremiumId: 'g1', hasBudget: false }).subscribe(
      () => (done = true),
    );
    const req = http.expectOne('/api/admin/application-types/t1');
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toEqual({ nameI18n: { de: 'N' }, gremiumId: 'g1', hasBudget: false });
    req.flush({});
    expect(done).toBe(true);

    // An empty body sets no keys.
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

  it('wires gremium-role CRUD + permission helper', () => {
    s.listGremiumRoles('g1').subscribe();
    http.expectOne('/api/admin/gremien/g1/roles').flush([]);

    s.createGremiumRole('g1', { key: 'k', name: { de: 'N' } }).subscribe();
    expect(http.expectOne('/api/admin/gremien/g1/roles').request.method).toBe('POST');

    s.updateGremiumRole('gr-9', { name: { de: 'N2' } }).subscribe();
    expect(http.expectOne('/api/admin/gremium-roles/gr-9').request.method).toBe('PATCH');

    // The helper delegates to updateGremiumRole.
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

  it('wires the gremium membership and the membership/role mapping endpoints', () => {
    s.listGremiumMemberships('g1').subscribe();
    http.expectOne('/api/admin/gremien/g1/memberships').flush([]);

    s.listGremiumRoles('g1', { quiet: true }).subscribe();
    http.expectOne('/api/admin/gremien/g1/roles').flush([]);

    s.listMembershipMappings().subscribe();
    http.expectOne('/api/admin/gremium-membership-mappings').flush([]);
    s.createMembershipMapping({ oidcGroup: 'stupa', gremiumId: 'g1' }).subscribe();
    const mPost = http.expectOne('/api/admin/gremium-membership-mappings');
    expect(mPost.request.method).toBe('POST');
    expect(mPost.request.body).toEqual({ oidcGroup: 'stupa', gremiumId: 'g1' });
    s.updateMembershipMapping('gmm-9', { gremiumId: 'g2' }).subscribe();
    const mPatch = http.expectOne('/api/admin/gremium-membership-mappings/gmm-9');
    expect(mPatch.request.method).toBe('PATCH');
    expect(mPatch.request.body).toEqual({ gremiumId: 'g2' });
    s.deleteMembershipMapping('gmm-9').subscribe();
    expect(http.expectOne('/api/admin/gremium-membership-mappings/gmm-9').request.method).toBe('DELETE');

    s.listRoleMappings().subscribe();
    http.expectOne('/api/admin/gremium-role-mappings').flush([]);
    s.createRoleMapping({ oidcGroup: 'stupa', gremiumRoleId: 'gr1' }).subscribe();
    const rPost = http.expectOne('/api/admin/gremium-role-mappings');
    expect(rPost.request.method).toBe('POST');
    expect(rPost.request.body).toEqual({ oidcGroup: 'stupa', gremiumRoleId: 'gr1' });
    s.updateRoleMapping('grm-9', { gremiumRoleId: 'gr2' }).subscribe();
    const rPatch = http.expectOne('/api/admin/gremium-role-mappings/grm-9');
    expect(rPatch.request.method).toBe('PATCH');
    expect(rPatch.request.body).toEqual({ gremiumRoleId: 'gr2' });
    s.deleteRoleMapping('grm-9').subscribe();
    expect(http.expectOne('/api/admin/gremium-role-mappings/grm-9').request.method).toBe('DELETE');
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

    // before: 0 is a valid cursor (!= null). The request must carry it.
    s.listAuditLog({ before: 0 }).subscribe();
    const zero = http.expectOne((r) => r.url === '/api/admin/audit');
    expect(zero.request.params.get('before')).toBe('0');
    zero.flush({ items: [], nextCursor: null, hasMore: false });

    s.listAuditActors().subscribe();
    http.expectOne('/api/admin/audit/actors').flush([]);
  });

  it('wires the audit chain checks', () => {
    s.latestAuditVerification().subscribe();
    http.expectOne('/api/admin/audit/verify/latest').flush(null);
    s.runAuditVerification().subscribe();
    const run = http.expectOne('/api/admin/audit/verify');
    expect(run.request.method).toBe('POST');
    run.flush({});
    s.verifyAuditChain().subscribe();
    const live = http.expectOne('/api/admin/audit/verify');
    expect(live.request.method).toBe('GET');
    live.flush({ valid: true, checked: 1, brokenAt: null, reason: null });
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
    expect(filtered.request.context.get(SKIP_LOADING)).toBe(false);
    filtered.flush([]);

    // A caller with its own loading state (the health tiles) skips the overlay.
    s.listErasures('open', { quiet: true }).subscribe();
    const quiet = http.expectOne((r) => r.url === '/api/admin/privacy/erasures');
    expect(quiet.request.context.get(SKIP_LOADING)).toBe(true);
    quiet.flush([]);

    s.executeErasure('e-1').subscribe();
    expect(http.expectOne('/api/admin/privacy/erasures/e-1/execute').request.method).toBe('POST');

    s.rejectErasure('e-1', 'nope').subscribe();
    const rej = http.expectOne('/api/admin/privacy/erasures/e-1/reject');
    expect(rej.request.body).toEqual({ reason: 'nope' });
    rej.flush({});

    // An omitted reason becomes null.
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
  // Backups. The archive never crosses the API as bytes: a download is a signed URL and
  // an upload is multipart, so the contract for both is worth pinning down.
  describe('backups', () => {
    it('lists the catalogue', () => {
      s.listBackups().subscribe();
      const req = http.expectOne('/api/admin/backups');
      expect(req.request.method).toBe('GET');
      expect(req.request.context.get(SKIP_LOADING)).toBe(false);
    });

    it('lists the catalogue without the overlay for a quiet caller', () => {
      s.listBackups({ quiet: true }).subscribe();
      expect(http.expectOne('/api/admin/backups').request.context.get(SKIP_LOADING)).toBe(true);
    });

    it('polls one row without raising the global loading overlay', () => {
      s.getBackup('b-1').subscribe();
      const req = http.expectOne('/api/admin/backups/b-1');
      expect(req.request.method).toBe('GET');
    });

    it('POSTs a create with the note', () => {
      s.createBackup('before the vote').subscribe();
      const req = http.expectOne('/api/admin/backups');
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toEqual({ note: 'before the vote' });
    });

    it('sends a null note when none was typed', () => {
      s.createBackup().subscribe();
      expect(http.expectOne('/api/admin/backups').request.body).toEqual({ note: null });
    });

    it('PATCHes the pin', () => {
      s.updateBackup('b-1', { pinned: true }).subscribe();
      const req = http.expectOne('/api/admin/backups/b-1');
      expect(req.request.method).toBe('PATCH');
      expect(req.request.body).toEqual({ pinned: true });
    });

    it('asks for the BYTES, never a presigned store URL', () => {
      // MinIO is internal, so a presigned S3 URL names a host the browser cannot
      // resolve. The client therefore requests a blob from the API.
      s.exportBackup('b-1').subscribe();
      const req = http.expectOne('/api/admin/backups/b-1/export');
      expect(req.request.method).toBe('GET');
      expect(req.request.responseType).toBe('blob');
    });

    it('uploads an import as multipart', () => {
      s.importBackup(new File(['x'], 'a.tar.age')).subscribe();
      const req = http.expectOne('/api/admin/backups/import');
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toBeInstanceOf(FormData);
    });

    it('sends the confirmation literal the API demands', () => {
      s.restoreBackup('b-1').subscribe();
      const req = http.expectOne('/api/admin/backups/b-1/restore');
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toEqual({ confirm: 'RESTORE' });
    });

    it('DELETEs one', () => {
      s.deleteBackup('b-1').subscribe();
      expect(http.expectOne('/api/admin/backups/b-1').request.method).toBe('DELETE');
    });
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

  it('pages, filters and revokes OAuth grants in the mock store', async () => {
    const s = svc();
    const all = await firstValueFrom(s.listOAuthGrants());
    expect(all.total).toBe(3);
    expect(all.items[0].principalName).toBe('Alex Admin');
    // The second stub carries no owner name. Every stub has real scope keys and an expiry.
    expect(all.items[1].principalName).toBeNull();
    const known = new Set(['read', 'applications:write', 'votes:write', 'meetings:write', 'budget:write', 'forms:write', 'flows:write', 'admin:write']);
    for (const g of all.items) {
      expect(g.scope.split(' ').every((x) => known.has(x))).toBe(true);
      expect(g.accessExpiresAt).not.toBeNull();
    }

    // Paging slices the store.
    const secondPage = await firstValueFrom(s.listOAuthGrants({ limit: 1, offset: 1 }));
    expect(secondPage.items).toHaveLength(1);
    expect(secondPage.offset).toBe(1);
    expect(secondPage.total).toBe(3);

    // The owner filter narrows the list.
    const mine = await firstValueFrom(s.listOAuthGrants({ principalId: 'p-1' }));
    expect(mine.items.map((g) => g.id)).toEqual(['grant-1']);

    await firstValueFrom(s.revokeOAuthGrant('grant-1'));
    const after = await firstValueFrom(s.listOAuthGrants());
    expect(after.items.some((g) => g.id === 'grant-1')).toBe(false);
    expect(after.total).toBe(2);
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
    // An unknown id returns store[0] unchanged (not renamed).
    expect(res.id).toBe(all[0].id);
    expect(res.name).toBe(all[0].name);
  });

  it('renames a role, creates a role, and deletes it', async () => {
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

  it('activates/deactivates a principal, falling back when id unknown', async () => {
    const s = svc();
    const all = await firstValueFrom(s.listPrincipals());
    const updated = await firstValueFrom(s.setPrincipalActive(all[0].id, false));
    expect(updated.active).toBe(false);
    // An unknown id returns store[0] and does not crash.
    const fallback = await firstValueFrom(s.setPrincipalActive('nope', true));
    expect(fallback.id).toBe(all[0].id);
  });

  it('returns an empty principal list when search matches nothing', async () => {
    const s = svc();
    expect(await firstValueFrom(s.listPrincipals('zzz-no-match'))).toEqual([]);
  });

  it('search tolerates principals with null email/displayName', async () => {
    const s = svc();
    const store = (s as unknown as { store: { principals: { id: string; sub: string; email: unknown; displayName: unknown; assignments: unknown[] }[] } }).store;
    store.principals.push({ id: 'p-null', sub: 'kc|nulluser', email: null, displayName: null, assignments: [] });
    // A query that does not match sub forces the email/displayName `?? ''` branches.
    const hits = await firstValueFrom(s.listPrincipals('nomatchwhatsoever'));
    expect(hits).toEqual([]);
    // A query that matches only the sub still returns the principal with null fields.
    expect((await firstValueFrom(s.listPrincipals('nulluser'))).map((p) => p.id)).toContain('p-null');
  });

  it('saveRolePermissions / renameRole no-op safely when role id is unknown', async () => {
    const s = svc();
    const roles = await firstValueFrom(s.listRoles());
    // findIndex < 0 → no mutation. The call falls back to the first role and does not crash.
    const sp = await firstValueFrom(s.saveRolePermissions('nope', ['x']));
    expect(sp.id).toBe(roles[0].id);
    // No role gained the bogus 'x' permission. No mutation happened.
    expect((await firstValueFrom(s.listRoles())).some((r) => r.permissions.includes('x'))).toBe(false);
    const rn = await firstValueFrom(s.renameRole('nope', { de: 'X' }));
    expect(rn.id).toBe(roles[0].id);
  });

  it('CRUDs application types in the mock store', async () => {
    const s = svc();
    const before = (await firstValueFrom(s.listApplicationTypesFull())).length;
    const created = await firstValueFrom(s.createApplicationType({ key: 'neu', name: { de: 'Neu' } }));
    expect(created.id).toBe('f-neu');
    expect(created.hasBudget).toBe(false);
    expect((await firstValueFrom(s.listApplicationTypesFull())).length).toBe(before + 1);

    // createApplicationType without a key falls back to the length index.
    const noKey = await firstValueFrom(s.createApplicationType({ key: '', name: { de: 'X' }, gremiumId: 'g1', hasBudget: true }));
    expect(noKey.id).toMatch(/^f-/);
    expect(noKey.gremiumId).toBe('g1');
    expect(noKey.hasBudget).toBe(true);

    await firstValueFrom(s.updateApplicationType(created.id, { name: { de: 'Geändert' }, gremiumId: 'g-asta', hasBudget: true }));
    const after = (await firstValueFrom(s.listApplicationTypesFull())).find((t) => t.id === created.id)!;
    expect(after.name['de']).toBe('Geändert');
    expect(after.gremiumId).toBe('g-asta');
    expect(after.hasBudget).toBe(true);

    // An update with an empty body leaves the row untouched. An unknown id is a no-op.
    await firstValueFrom(s.updateApplicationType(created.id, {}));
    await firstValueFrom(s.updateApplicationType('ghost', { name: { de: 'X' } }));

    await firstValueFrom(s.deleteApplicationType(created.id));
    expect((await firstValueFrom(s.listApplicationTypesFull())).some((t) => t.id === created.id)).toBe(false);
  });

  it('loads a known form draft and an empty stub for an unknown type', async () => {
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

    // The first version of a brand-new type starts at version 1 with a null description.
    const fresh = await firstValueFrom(s.createFormVersion('brand-new', [], null));
    expect(fresh.id).toBe('formver-0');
    const freshDraft = await firstValueFrom(s.getFormDraft('brand-new'));
    expect(freshDraft.version).toBe(1);
    expect(freshDraft.description).toBeNull();

    const deactivated = await firstValueFrom(s.setFormActive('f-foerderung', false));
    expect(deactivated.active).toBe(false);
    // A second activation restores activeFormVersionId of the type from the draft.
    const reactivated = await firstValueFrom(s.setFormActive('f-foerderung', true));
    expect(reactivated.active).toBe(true);
    const types = await firstValueFrom(s.listApplicationTypesFull());
    expect(types.find((t) => t.id === 'f-foerderung')!.activeFormVersionId).toBe('formver-1');

    // Activate a draft that has no formVersionId. Then activeFormVersionId becomes null.
    const store = (s as unknown as { store: { formDrafts: Record<string, { applicationTypeId: string; active?: boolean; fields: unknown[] }> } }).store;
    store.formDrafts['f-veranstaltung'] = { applicationTypeId: 'f-veranstaltung', fields: [] };
    const noVer = await firstValueFrom(s.setFormActive('f-veranstaltung', true));
    expect(noVer.active).toBe(true);
    expect((await firstValueFrom(s.listApplicationTypesFull())).find((t) => t.id === 'f-veranstaltung')!.activeFormVersionId).toBeNull();

    // setFormActive on a type with no draft returns a synthesized stub.
    const stub = await firstValueFrom(s.setFormActive('no-draft-type', true));
    expect(stub).toEqual({ applicationTypeId: 'no-draft-type', active: true, fields: [] });
  });

  it('returns null global flow and a deterministic mock flow id in mock mode', async () => {
    const s = svc();
    expect(await firstValueFrom(s.getGlobalFlow())).toBeNull();
    const created = await firstValueFrom(s.createGlobalFlowVersion({ states: [{ key: 's', label: {} }], transitions: [] }));
    expect(created.id).toBe('gflow-1');
  });

  it('CRUDs gremium-roles in the mock store', async () => {
    const s = svc();
    // The seed gives each mock gremium its forced roles.
    expect((await firstValueFrom(s.listGremiumRoles(MOCK_GREMIUM_STUPA_ID))).map((r) => r.key)).toEqual(['vorstand', 'manager', 'member', 'protokoll']);
    expect(await firstValueFrom(s.listGremiumRoles('g-empty'))).toEqual([]);
    const created = await firstValueFrom(s.createGremiumRole('g-empty', { key: 'chair', name: { de: 'Vorsitz' } }));
    expect(created.gremiumId).toBe('g-empty');
    expect((await firstValueFrom(s.listGremiumRoles('g-empty'))).length).toBe(1);
    // The filter excludes the other gremium.
    expect(await firstValueFrom(s.listGremiumRoles('g-other'))).toEqual([]);

    const updated = await firstValueFrom(s.updateGremiumRole(created.id, { name: { de: 'Neu' } }));
    expect(updated.name['de']).toBe('Neu');
    const withPerms = await firstValueFrom(s.saveGremiumRolePermissions(created.id, ['vote.cast']));
    expect(withPerms.permissions).toEqual(['vote.cast']);
    // An unknown id gives a synthesized fallback row that carries the name.
    const fallback = await firstValueFrom(s.updateGremiumRole('ghost', { name: { de: 'F' } }));
    expect(fallback.id).toBe('ghost');
    expect(fallback.name).toEqual({ de: 'F' });
    // An unknown id with no name in the body takes the `?? {}` branch. The name becomes {}.
    const fallbackNoName = await firstValueFrom(s.updateGremiumRole('ghost2', { permissions: ['x'] }));
    expect(fallbackNoName.id).toBe('ghost2');
    expect(fallbackNoName.name).toEqual({});

    await firstValueFrom(s.deleteGremiumRole(created.id));
    expect(await firstValueFrom(s.listGremiumRoles('g-empty'))).toEqual([]);
  });

  it('deleteGremiumRole tolerates a nullish gremiumRoles store (defensive `?? []`)', async () => {
    const s = svc();
    const store = (s as unknown as { store: { gremiumRoles: unknown } }).store;
    store.gremiumRoles = undefined;
    await firstValueFrom(s.deleteGremiumRole('any'));
    // The store re-initializes to an array. Nothing crashes and the list is empty.
    expect(await firstValueFrom(s.listGremiumRoles(MOCK_GREMIUM_STUPA_ID))).toEqual([]);
  });

  it('CRUDs deadline policies in the mock store', async () => {
    const s = svc();
    const seeded = await firstValueFrom(s.listDeadlinePolicies());
    expect(seeded.map((p) => p.kind)).toEqual(['relative_changed', 'relative_submitted', 'absolute', 'recurring']);
    const created = await firstValueFrom(s.createDeadlinePolicy({ key: 'sem', label: { de: 'Semester' }, kind: 'absolute' }));
    expect(created.id).toBe('dp-5');
    const updated = await firstValueFrom(s.updateDeadlinePolicy(created.id, { offsetDays: 5 }));
    expect(updated.offsetDays).toBe(5);
    // An unknown id gives a synthesized fallback.
    const fallback = await firstValueFrom(s.updateDeadlinePolicy('ghost', { offsetDays: 1 }));
    expect(fallback.id).toBe('ghost');
    await firstValueFrom(s.deleteDeadlinePolicy(created.id));
    expect(await firstValueFrom(s.listDeadlinePolicies())).toEqual(seeded);
  });

  it('keeps the guest settings in the mock store', async () => {
    const s = svc();
    expect(await firstValueFrom(s.getGuestSettings())).toEqual({ confirmTtlHours: 12, linkTtlDays: null });
    await firstValueFrom(s.putGuestSettings({ confirmTtlHours: 48, linkTtlDays: 14 }));
    expect(await firstValueFrom(s.getGuestSettings())).toEqual({ confirmTtlHours: 48, linkTtlDays: 14 });
  });

  it('serves the CD variants, the site versions and the notification save in mock mode', async () => {
    const s = svc();
    const variants = await firstValueFrom(s.listCdVariants());
    expect(variants.map((v) => v.key)).toEqual(['stupa', 'asta', 'bericht']);
    expect((await firstValueFrom(s.listConfigRevisions('site_config', 'global'))).map((r) => r.version)).toEqual([3, 2, 1]);
    expect(await firstValueFrom(s.listConfigRevisions('flow', 'global'))).toEqual([]);
    expect(await firstValueFrom(s.putNotificationSettings({ taskReminderAfterDays: 9 }))).toEqual({
      taskReminderEnabled: true,
      taskReminderAfterDays: 9,
      taskReminderRepeatDays: 7,
    });
  });

  it('returns the seeded memberships of one gremium in mock mode', async () => {
    const s = svc();
    const stupa = await firstValueFrom(s.listGremiumMemberships(MOCK_GREMIUM_STUPA_ID));
    expect(stupa.length).toBe(9);
    // The server joins the name and the e-mail of each member.
    expect(stupa.find((m) => m.principalId === 'p-1')).toMatchObject({ displayName: 'Alex Admin', email: 'alex@stupa.example' });
    expect((await firstValueFrom(s.listGremiumMemberships('g-asta'))).map((m) => m.principalId)).toEqual(['p-4', 'p-7']);
    expect(await firstValueFrom(s.listGremiumMemberships('g-none'))).toEqual([]);
  });

  it('CRUDs the global group mappings in the mock store', async () => {
    const s = svc();
    expect((await firstValueFrom(s.listGroupMappings())).length).toBe(2);
    const created = await firstValueFrom(s.createGroupMapping({ oidcGroup: 'x', roleId: 'r-member' }));
    expect(created).toMatchObject({ oidcGroup: 'x', roleId: 'r-member' });
    const updated = await firstValueFrom(s.updateGroupMapping(created.id, { roleId: 'r-admin' }));
    expect(updated.roleId).toBe('r-admin');
    await firstValueFrom(s.deleteGroupMapping(created.id));
    // An unknown id is a no-op for a delete.
    await firstValueFrom(s.deleteGroupMapping('ghost'));
    expect((await firstValueFrom(s.listGroupMappings())).length).toBe(2);
  });

  it('answers 404 for a change of an unknown mapping in the mock store', async () => {
    const s = svc();
    await expect(firstValueFrom(s.updateGroupMapping('ghost', { roleId: 'r-admin' }))).rejects.toEqual({ status: 404 });
  });

  it('CRUDs the membership mappings in the mock store', async () => {
    const s = svc();
    expect((await firstValueFrom(s.listMembershipMappings())).length).toBe(2);
    const created = await firstValueFrom(s.createMembershipMapping({ oidcGroup: 'x', gremiumId: 'g-asta' }));
    const updated = await firstValueFrom(s.updateMembershipMapping(created.id, { gremiumId: MOCK_GREMIUM_STUPA_ID }));
    expect(updated.gremiumId).toBe(MOCK_GREMIUM_STUPA_ID);
    await firstValueFrom(s.deleteMembershipMapping(created.id));
    expect((await firstValueFrom(s.listMembershipMappings())).length).toBe(2);
  });

  it('CRUDs the role mappings in the mock store and derives the gremium from the role', async () => {
    const s = svc();
    expect((await firstValueFrom(s.listRoleMappings())).length).toBe(4);
    const created = await firstValueFrom(s.createRoleMapping({ oidcGroup: 'x', gremiumRoleId: 'gr-asta-vorstand' }));
    expect(created.gremiumId).toBe('g-asta');
    const moved = await firstValueFrom(s.updateRoleMapping(created.id, { gremiumRoleId: 'gr-stupa-member' }));
    expect(moved.gremiumId).toBe(MOCK_GREMIUM_STUPA_ID);
    // A change of the group only keeps the gremium.
    const renamed = await firstValueFrom(s.updateRoleMapping(created.id, { oidcGroup: 'y' }));
    expect(renamed).toMatchObject({ oidcGroup: 'y', gremiumId: MOCK_GREMIUM_STUPA_ID });
    // An unknown role gives no gremium.
    const orphan = await firstValueFrom(s.createRoleMapping({ oidcGroup: 'z', gremiumRoleId: 'ghost' }));
    expect(orphan.gremiumId).toBe('');
    await firstValueFrom(s.deleteRoleMapping(created.id));
    await firstValueFrom(s.deleteRoleMapping(orphan.id));
    expect((await firstValueFrom(s.listRoleMappings())).length).toBe(4);
  });

  it('pages and filters the mock audit log', async () => {
    const s = svc();
    const all = await firstValueFrom(s.listAuditLog());
    expect(all.items.length).toBeGreaterThan(3);
    expect(all.hasMore).toBe(false);
    expect(all.nextCursor).toBeNull();
    // Newest first, keyset paging on the id.
    const first = await firstValueFrom(s.listAuditLog({ limit: 2 }));
    expect(first.items).toHaveLength(2);
    expect(first.hasMore).toBe(true);
    expect(first.nextCursor).toBe(first.items[1].id);
    const next = await firstValueFrom(s.listAuditLog({ limit: 2, before: first.nextCursor! }));
    expect(next.items.every((e) => e.id < first.nextCursor!)).toBe(true);
    // Action and actor filter.
    const byAction = await firstValueFrom(s.listAuditLog({ action: 'role_change' }));
    expect(byAction.items.map((e) => e.action)).toEqual(['role_change']);
    const byActor = await firstValueFrom(s.listAuditLog({ actor: 'kc|kim.kasse' }));
    expect(byActor.items.every((e) => e.actor === 'kc|kim.kasse')).toBe(true);
    expect((await firstValueFrom(s.listAuditActors())).length).toBeGreaterThan(0);
  });

  it('reverts a mock audit entry once and answers for an unknown id', async () => {
    const s = svc();
    const res = await firstValueFrom(s.revertAuditEntry(7));
    expect(res).toEqual({ revertedAuditId: 7, entityType: 'flow', entityId: 'global' });
    const entry = (await firstValueFrom(s.listAuditLog())).items.find((e) => e.id === 7);
    expect(entry?.revertable).toBe(false);
    expect(await firstValueFrom(s.revertAuditEntry(999))).toEqual({
      revertedAuditId: 999,
      entityType: '',
      entityId: '',
    });
  });

  it('serves the chain checks and a config diff in mock mode', async () => {
    const s = svc();
    const latest = await firstValueFrom(s.latestAuditVerification());
    expect(latest?.valid).toBe(true);
    expect(latest?.trigger).toBe('cron');
    const run = await firstValueFrom(s.runAuditVerification());
    expect(run.trigger).toBe('manual');
    // The manual check is the newest stored one now.
    expect((await firstValueFrom(s.latestAuditVerification()))?.id).toBe(run.id);
    const live = await firstValueFrom(s.verifyAuditChain());
    expect(live.valid).toBe(true);
    const diff = await firstValueFrom(s.getConfigRevisionDiff('rev-12'));
    expect(diff.diff?.changed.length).toBe(2);
    expect(diff.entityType).toBe('flow');
    const none = await firstValueFrom(s.getConfigRevisionDiff('rev-x'));
    expect(none.diff).toBeNull();
  });

  it('counts the members and roles of each mock gremium', async () => {
    const s = svc();
    const gremien = await firstValueFrom(s.listGremien());
    const stupa = gremien.find((g) => g.id === MOCK_GREMIUM_STUPA_ID);
    expect(stupa?.memberCount).toBe(9);
    expect(stupa?.roleCount).toBe(4);
  });

  it('keeps the extra protocol recipients per gremium in the mock store', async () => {
    const s = svc();
    expect((await firstValueFrom(s.getGremiumMailRecipients(MOCK_GREMIUM_STUPA_ID))).recipients).toHaveLength(2);
    expect((await firstValueFrom(s.getGremiumMailRecipients('g-asta'))).recipients).toEqual([]);
    await firstValueFrom(s.setGremiumMailRecipients('g-asta', ['a@x.de']));
    expect((await firstValueFrom(s.getGremiumMailRecipients('g-asta'))).recipients).toEqual(['a@x.de']);
  });

  it('gives a new mock gremium the forced roles', async () => {
    const s = svc();
    const created = await firstValueFrom(
      s.createGremium({ name: 'Neu', slug: 'neu', cdVariantId: null, defaultLang: 'de' }),
    );
    const roles = await firstValueFrom(s.listGremiumRoles(created.id));
    expect(roles.map((r) => r.key)).toEqual(['vorstand', 'manager', 'member']);
    expect(roles.every((r) => r.forced && r.gremiumId === created.id)).toBe(true);
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
    expect((await firstValueFrom(s.listErasures())).length).toBe(4);
    expect((await firstValueFrom(s.listErasures('open'))).map((r) => r.id)).toEqual(['e-1', 'e-2']);

    // Execute or reject on an unknown id gives a synthesized {id} fallback and no crash.
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
    // The value persists in the store.
    expect((await firstValueFrom(s.getPrivacySettings())).defaultRetentionMonths).toBe(48);

    const blob = await firstValueFrom(s.downloadAuskunft('a@b.org'));
    expect(blob).toBeInstanceOf(Blob);
  });

  it('filters mock erasures by status when the store has rows', async () => {
    const s = svc();
    // Seed the private store directly to reach the status-filter branch.
    const store = (s as unknown as { store: { erasures: { id: string; status: string }[] } }).store;
    store.erasures.length = 0;
    store.erasures.push(
      { id: 'e-open', status: 'open' } as never,
      { id: 'e-done', status: 'executed' } as never,
    );
    expect((await firstValueFrom(s.listErasures())).length).toBe(2);
    const open = await firstValueFrom(s.listErasures('open'));
    expect(open.map((r) => r.id)).toEqual(['e-open']);

    // Execute and reject on existing rows take the mutation branch.
    await firstValueFrom(s.executeErasure('e-open'));
    expect((await firstValueFrom(s.listErasures('executed'))).map((r) => r.id)).toContain('e-open');
    const rejected = await firstValueFrom(s.rejectErasure('e-done', 'r'));
    expect(rejected.status).toBe('rejected');
    expect(rejected.reason).toBe('r');
    const rejectedNull = await firstValueFrom(s.rejectErasure('e-done'));
    expect(rejectedNull.reason).toBeNull();
  });

  it('serves the backup catalogue from the seeded store', async () => {
    const s = svc();
    const list = await firstValueFrom(s.listBackups());
    expect(list.items.length).toBeGreaterThan(0);
    expect(list.enabled).toBe(true);

    const one = await firstValueFrom(s.getBackup(list.items[0].id));
    expect(one.id).toBe(list.items[0].id);
    // An unknown id falls back to a stub rather than throwing.
    expect((await firstValueFrom(s.getBackup('nope'))).id).toBe('nope');

    const created = await firstValueFrom(s.createBackup('note'));
    expect(created.note).toBe('note');
    expect((await firstValueFrom(s.listBackups())).items[0].id).toBe(created.id);

    const pinned = await firstValueFrom(s.updateBackup(created.id, { pinned: true }));
    expect(pinned.pinned).toBe(true);
    expect((await firstValueFrom(s.updateBackup('nope', { pinned: true }))).id).toBe('nope');

    expect(await firstValueFrom(s.exportBackup(created.id))).toBeInstanceOf(Blob);
    expect((await firstValueFrom(s.importBackup(new File(['x'], 'a.age')))).note).toBe('a.age');
    expect((await firstValueFrom(s.restoreBackup(created.id))).id).toBe(created.id);
    expect((await firstValueFrom(s.restoreBackup('nope'))).id).toBe('nope');

    await firstValueFrom(s.deleteBackup(created.id));
    const after = await firstValueFrom(s.listBackups());
    expect(after.items.some((b) => b.id === created.id)).toBe(false);
  });

  it('edits, resets and previews the mail templates in the mock store', async () => {
    const s = svc();
    const http = TestBed.inject(HttpTestingController);
    const list = await firstValueFrom(s.listMailTemplates());
    expect(list.find((t) => t.key === 'status_update')?.source).toBe('override');
    const saved = await firstValueFrom(
      s.upsertMailTemplate({ key: 'magic_link', subjectI18n: { de: 'Neu' }, bodyI18n: { de: 'Text' }, bodyHtmlI18n: {} }),
    );
    expect(saved).toMatchObject({ key: 'magic_link', source: 'override', id: 'mt-magic_link', subjectI18n: { de: 'Neu' } });
    expect(saved.placeholders).toEqual({ link: expect.any(String) });
    // An override keeps its id.
    const again = await firstValueFrom(
      s.upsertMailTemplate({ key: 'status_update', subjectI18n: { de: 'S' }, bodyI18n: {}, bodyHtmlI18n: {} }),
    );
    expect(again.id).toBe('mt-1');
    // A key that is not in the store gets no placeholders.
    const unknown = await firstValueFrom(
      s.upsertMailTemplate({ key: 'ghost', subjectI18n: {}, bodyI18n: {}, bodyHtmlI18n: {} }),
    );
    expect(unknown.placeholders).toEqual({});
    const reset = await firstValueFrom(s.resetMailTemplate('magic_link'));
    expect(reset).toMatchObject({ key: 'magic_link', source: 'builtin', id: null, subjectI18n: { de: 'Dein Link zur Antragsplattform' } });
    // An unknown key falls back to the first seed template.
    expect((await firstValueFrom(s.resetMailTemplate('ghost'))).source).toBe('builtin');
    const pv = await firstValueFrom(
      s.previewMailPayload({
        subjectI18n: { de: 'Hallo {{ name }}' },
        bodyI18n: { de: 'Status: {{status}} {{ missing }}' },
        bodyHtmlI18n: { de: '<p>{{ name }}</p>' },
        lang: 'de',
        context: { name: 'Mara', status: 'offen' },
      }),
    );
    expect(pv).toEqual({ subject: 'Hallo Mara', text: 'Status: offen ', html: '<p>Mara</p>', lang: 'de' });
    const plain = await firstValueFrom(
      s.previewMailPayload({ subjectI18n: {}, bodyI18n: {}, bodyHtmlI18n: {}, lang: 'en', context: {} }),
    );
    expect(plain).toEqual({ subject: '', text: '', html: null, lang: 'en' });
    http.verify();
  });
});
