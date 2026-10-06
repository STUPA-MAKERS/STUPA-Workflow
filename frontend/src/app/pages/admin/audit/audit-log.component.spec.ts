import { Subject, of, throwError } from 'rxjs';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { AuthService } from '@core/auth/auth.service';
import { ToastService } from '@stupa-makers/ui-kit';
import type { AuditActor, AuditEntry, AuditPage, AuditVerification } from '../admin.models';
import { AdminApiService } from '../admin-api.service';
import { AUDIT_ACTIONS, AuditLogComponent, localDayBound } from './audit-log.component';

/**
 * Typed view on the protected surface of the component. The tests call the filter setters
 * and the paging helpers directly. All of them go through `load`.
 */
type Cmp = AuditLogComponent & {
  setAction(v: string): void;
  setActor(v: string): void;
  setSince(v: string): void;
  setUntil(v: string): void;
  resetFilters(): void;
  loadMore(): void;
  toggle(id: number): void;
  isOpen(id: number): boolean;
  actionLabel(action: string): string;
  targetTypeLabel(type: string): string;
  targetLink(e: AuditEntry): string[] | null;
  targetText(e: AuditEntry): string;
  actorLabel(e: AuditEntry): string;
  dataRows(e: AuditEntry): { key: string; label: string; value: string; known: boolean }[];
  activeFilterCount(): number;
  actionOptions(): { value: string; label: string }[];
  actionChip(): string;
  actorChip(): string;
  runVerify(): void;
  verifying(): boolean;
  verifyView(): { kind: string; title: string; sub: string } | null;
  loadError(): boolean;
  loading(): boolean;
  hasMore(): boolean;
  entries(): AuditEntry[];
};

/** The collapsed toggle of the first audit entry. The filter chip is a collapsed toggle
 *  too, so the query keeps only the entry rows. */
function entryToggle(): HTMLElement {
  const rows = screen
    .getAllByRole('button', { expanded: false })
    .filter((b) => b.classList.contains('al__row'));
  expect(rows.length).toBeGreaterThan(0);
  return rows[0];
}

function entry(id: number, over: Partial<AuditEntry> = {}): AuditEntry {
  return {
    id,
    at: '2026-06-07T09:00:00+00:00',
    actor: 'kc|root',
    actorName: 'Root Admin',
    action: 'role_change',
    targetType: 'principal',
    targetId: 'p-1',
    data: {},
    hash: 'h',
    prevHash: null,
    ...over,
  };
}

const CHECK: AuditVerification = {
  id: 'av-1',
  startedAt: '2026-06-07T02:30:00+00:00',
  finishedAt: '2026-06-07T02:30:04+00:00',
  valid: true,
  checked: 18412,
  brokenAt: null,
  reason: null,
  trigger: 'cron',
  triggeredBy: null,
};

interface SetupOpts {
  page?: AuditPage;
  actors?: AuditActor[];
  actorsError?: boolean;
  listAuditLog?: jest.Mock;
  latest?: jest.Mock;
  run?: jest.Mock;
  perms?: string[];
}

async function setup(opts: SetupOpts = {}) {
  const page = opts.page ?? { items: [entry(1)], nextCursor: null, hasMore: false };
  const listAuditLog = opts.listAuditLog ?? jest.fn(() => of(page));
  const listAuditActors = opts.actorsError
    ? jest.fn(() => throwError(() => new Error('boom')))
    : jest.fn(() => of(opts.actors ?? []));
  const latestAuditVerification = opts.latest ?? jest.fn(() => of(CHECK));
  const runAuditVerification =
    opts.run ?? jest.fn(() => of({ ...CHECK, id: 'av-2', trigger: 'manual' as const }));
  const api = { listAuditLog, listAuditActors, latestAuditVerification, runAuditVerification };
  const perms = new Set(opts.perms ?? ['audit.read', 'audit.verify']);
  const toast = { success: jest.fn(), error: jest.fn() };
  const view = await render(AuditLogComponent, {
    providers: [
      provideRouter([]),
      { provide: AdminApiService, useValue: api },
      { provide: AuthService, useValue: { can: (p: string) => perms.has(p) } },
      { provide: ToastService, useValue: toast },
    ],
  });
  const cmp = view.fixture.componentInstance as unknown as Cmp;
  return { ...view, cmp, listAuditLog, listAuditActors, api, toast };
}

/**
 * Copy of the `AuditAction` values in `backend/app/modules/audit/actions.py`, in file order.
 * When the backend adds an action, add it here, to `AUDIT_ACTIONS` and to the de and en
 * labels `admin.audit.action.<key>`.
 */
const BACKEND_AUDIT_ACTIONS = [
  'login',
  'status_change',
  'vote_cast',
  'config_change',
  'config_activation',
  'config_revert',
  'role_change',
  'delegation_grant',
  'delegation_revoke',
  'delegation_use',
  'delegation_substitute_add',
  'delegation_substitute_remove',
  'export',
  'meeting_delete',
  'meeting_create',
  'meeting_update',
  'agenda_item_add',
  'agenda_item_update',
  'agenda_item_remove',
  'agenda_reorder',
  'attendance_set',
  'attendance_reset',
  'application_delete',
  'application_create',
  'application_create_on_behalf',
  'guest_application_discard',
  'application_update',
  'application_archive',
  'application_unarchive',
  'application_share',
  'application_share_revoke',
  'webhook_config',
  'attachment_upload',
  'attachment_quarantine',
  'attachment_delete',
  'comment_update',
  'comment_delete',
  'protocol_delete',
  'protocol_finalize',
  'protokollant_handover',
  'vote_delete',
  'vote_open',
  'vote_close',
  'vote_cancel',
  'vote_branch_blocked',
  'pii_access',
  'pii_deletion',
  'pii_export',
  'anonymization',
  'erasure_requested',
  'erasure_executed',
  'erasure_rejected',
  'principal_erased',
  'principal_merge',
  'retention_anonymize',
  'budget_node_create',
  'budget_node_update',
  'budget_node_delete',
  'budget_fiscal_year_delete',
  'budget_allocation_set',
  'budget_expense_create',
  'budget_expense_update',
  'budget_expense_delete',
  'budget_transfer_create',
  'budget_invoice_create',
  'budget_invoice_update',
  'budget_invoice_delete',
  'budget_assign',
  'budget_move_fiscal_year',
  'backup_create',
  'backup_delete',
  'backup_export',
  'backup_import',
  'backup_restore',
] as const;

describe('AuditLogComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  /** A real application-type id: a `form` audit target keeps the id of its type. */
  const TYPE_UUID = 'a257b8e0-0c78-43cb-938f-a4924f68443f';

  it('lists the entries as rows: time, action, actor and target', async () => {
    const { fixture, listAuditLog } = await setup({
      page: { items: [entry(1)], nextCursor: null, hasMore: false },
    });
    expect(listAuditLog).toHaveBeenCalledWith(
      expect.objectContaining({ limit: 50, before: undefined }),
    );
    const row = entryToggle();
    expect(row.textContent).toContain('07.06.2026');
    expect(row.textContent).toContain('Rollen/Rechte');
    expect(row.textContent).toContain('Root Admin');
    expect(row.textContent).toContain('Benutzer · p-1');
    row.click();
    fixture.detectChanges();
    expect(screen.getAllByText('Rollen/Rechte').length).toBe(2);
  });

  it('shows the raw key of an unknown action', async () => {
    await setup({
      page: { items: [entry(1, { action: 'mystery_event', actorName: null })], nextCursor: null, hasMore: false },
    });
    expect(screen.getByText('mystery_event')).toBeInTheDocument();
    // Without a name the actor is the sub.
    expect(screen.getByText('kc|root')).toBeInTheDocument();
  });

  it('shows the empty state when there are no entries', async () => {
    await setup({ page: { items: [], nextCursor: null, hasMore: false } });
    expect(screen.getByText('Keine Audit-Einträge.')).toBeInTheDocument();
  });

  it('offers "load more" while more entries remain', async () => {
    await setup({ page: { items: [entry(1)], nextCursor: 1, hasMore: true } });
    expect(screen.getByRole('button', { name: 'Mehr laden' })).toBeInTheDocument();
  });

  it('prefers the resolved target label in the row', async () => {
    await setup({
      page: {
        items: [
          entry(1, {
            action: 'status_change',
            targetType: 'application',
            targetId: 'a-1',
            targetLabel: 'Beamer kaufen',
          }),
        ],
        nextCursor: null,
        hasMore: false,
      },
    });
    expect(screen.getByText('Antrag · Beamer kaufen')).toBeInTheDocument();
    expect(screen.queryByText(/a-1/)).not.toBeInTheDocument();
  });

  it('expands the details on click', async () => {
    const { fixture } = await setup({
      page: { items: [entry(1, { data: { rows: 7 } })], nextCursor: null, hasMore: false },
    });
    expect(screen.queryByText('rows')).not.toBeInTheDocument();
    entryToggle().click();
    fixture.detectChanges();
    expect(screen.getByText('rows')).toBeInTheDocument();
    expect(screen.getByText('7')).toBeInTheDocument();
  });

  it('renders embedded data UUIDs and the actor as "<name> · <uuid>"', async () => {
    const { fixture } = await setup({
      page: {
        items: [
          entry(1, {
            data: { gremiumId: 'g-1' },
            resolvedIds: { 'g-1': 'Finanzausschuss' },
          }),
        ],
        nextCursor: null,
        hasMore: false,
      },
    });
    entryToggle().click();
    fixture.detectChanges();
    expect(screen.getByText('Finanzausschuss · g-1')).toBeInTheDocument();
    expect(screen.getByText('Root Admin · kc|root')).toBeInTheDocument();
  });

  it('falls back to the raw UUID in data chips when unresolved', async () => {
    const { fixture } = await setup({
      page: { items: [entry(1, { data: { gremiumId: 'g-unknown' } })], nextCursor: null, hasMore: false },
    });
    entryToggle().click();
    fixture.detectChanges();
    expect(screen.getByText('g-unknown')).toBeInTheDocument();
  });

  it('loads the actor list on init', async () => {
    const { cmp } = await setup({ actors: [{ sub: 'kc|a', name: 'Alice' }] });
    expect((cmp as unknown as { actors(): AuditActor[] }).actors()).toEqual([
      { sub: 'kc|a', name: 'Alice' },
    ]);
  });

  it('falls back to an empty actor list when the actors request fails', async () => {
    const { cmp } = await setup({ actorsError: true });
    expect((cmp as unknown as { actors(): AuditActor[] }).actors()).toEqual([]);
  });

  it('setAction reloads with the action filter', async () => {
    const { cmp, listAuditLog } = await setup();
    listAuditLog.mockClear();
    cmp.setAction('login');
    expect(listAuditLog).toHaveBeenCalledWith(
      expect.objectContaining({ action: 'login', before: undefined }),
    );
  });

  it('setActor reloads with the actor filter', async () => {
    const { cmp, listAuditLog } = await setup();
    listAuditLog.mockClear();
    cmp.setActor('kc|bob');
    expect(listAuditLog).toHaveBeenCalledWith(expect.objectContaining({ actor: 'kc|bob' }));
  });

  it('setSince expands the date to a start-of-day bound', async () => {
    const { cmp, listAuditLog } = await setup();
    listAuditLog.mockClear();
    cmp.setSince('2026-06-01');
    // The server wants an aware time: the local midnight goes out as UTC.
    expect(listAuditLog).toHaveBeenCalledWith(
      expect.objectContaining({ since: localDayBound('2026-06-01', false) }),
    );
    expect(localDayBound('2026-06-01', false)).toBe(new Date(2026, 5, 1).toISOString());
    expect(localDayBound('2026-06-01', false)).not.toContain('+');
  });

  it('setUntil expands the date to an end-of-day bound', async () => {
    const { cmp, listAuditLog } = await setup();
    listAuditLog.mockClear();
    cmp.setUntil('2026-06-30');
    expect(listAuditLog).toHaveBeenCalledWith(
      expect.objectContaining({ until: localDayBound('2026-06-30', true) }),
    );
    expect(localDayBound('2026-06-30', true)).toBe(new Date(2026, 5, 30, 23, 59, 59, 999).toISOString());
  });

  it('omits empty date bounds (undefined, not the T-suffixed string)', async () => {
    const { listAuditLog } = await setup();
    expect(listAuditLog).toHaveBeenCalledWith(
      expect.objectContaining({ since: undefined, until: undefined, action: undefined, actor: undefined }),
    );
  });

  it('resetFilters clears every filter and reloads', async () => {
    const { cmp, listAuditLog } = await setup();
    cmp.setAction('login');
    cmp.setActor('kc|bob');
    cmp.setSince('2026-06-01');
    cmp.setUntil('2026-06-30');
    expect(cmp.activeFilterCount()).toBe(4);
    listAuditLog.mockClear();
    cmp.resetFilters();
    expect(cmp.activeFilterCount()).toBe(0);
    expect(listAuditLog).toHaveBeenLastCalledWith(
      expect.objectContaining({
        action: undefined,
        actor: undefined,
        since: undefined,
        until: undefined,
      }),
    );
  });

  it('activeFilterCount counts each populated filter independently', async () => {
    const { cmp } = await setup();
    expect(cmp.activeFilterCount()).toBe(0);
    cmp.setSince('2026-06-01');
    expect(cmp.activeFilterCount()).toBe(1);
  });

  it('exposes the full action catalog as filter options', async () => {
    const { cmp } = await setup();
    const opts = cmp.actionOptions();
    const values = opts.map((o) => o.value);
    expect(values).toContain('login');
    expect(values).toContain('budget_move_fiscal_year');
    expect(opts.length).toBeGreaterThan(20);
  });

  it('loadMore appends the next page using the before cursor', async () => {
    const second: AuditPage = { items: [entry(2)], nextCursor: null, hasMore: false };
    const listAuditLog = jest
      .fn()
      .mockReturnValueOnce(of<AuditPage>({ items: [entry(1)], nextCursor: 1, hasMore: true }))
      .mockReturnValueOnce(of(second));
    const { cmp } = await setup({ listAuditLog });
    expect(cmp.entries().map((e) => e.id)).toEqual([1]);
    expect(cmp.hasMore()).toBe(true);

    cmp.loadMore();
    expect(listAuditLog).toHaveBeenLastCalledWith(expect.objectContaining({ before: 1 }));
    expect(cmp.entries().map((e) => e.id)).toEqual([1, 2]);
    expect(cmp.hasMore()).toBe(false);
  });

  it('loadMore sends before: undefined when the cursor is null but more remain', async () => {
    // Defensive branch: hasMore is true while nextCursor is null, so before falls back to
    // undefined.
    const listAuditLog = jest
      .fn()
      .mockReturnValueOnce(of<AuditPage>({ items: [entry(1)], nextCursor: null, hasMore: true }))
      .mockReturnValueOnce(of<AuditPage>({ items: [entry(2)], nextCursor: null, hasMore: false }));
    const { cmp } = await setup({ listAuditLog });
    cmp.loadMore();
    expect(listAuditLog).toHaveBeenLastCalledWith(expect.objectContaining({ before: undefined }));
    expect(cmp.entries().map((e) => e.id)).toEqual([1, 2]);
  });

  it('loadMore is a no-op when there are no more entries', async () => {
    const { cmp, listAuditLog } = await setup({
      page: { items: [entry(1)], nextCursor: null, hasMore: false },
    });
    listAuditLog.mockClear();
    cmp.loadMore();
    expect(listAuditLog).not.toHaveBeenCalled();
  });

  it('skips concurrent loads while a request is in flight', async () => {
    const subj = new Subject<AuditPage>();
    // The first call from the constructor reload hangs. A filter change must not fire a second.
    const listAuditLog = jest.fn(() => subj.asObservable());
    const { cmp } = await setup({ listAuditLog });
    expect(cmp.loading()).toBe(true);
    expect(listAuditLog).toHaveBeenCalledTimes(1);
    // A filter setter triggers reload and load(true), but the loading guard holds.
    cmp.setAction('login');
    expect(listAuditLog).toHaveBeenCalledTimes(1);
    subj.next({ items: [], nextCursor: null, hasMore: false });
    subj.complete();
    expect(cmp.loading()).toBe(false);
  });

  it('flags a load error and shows the alert', async () => {
    const { cmp, fixture } = await setup({
      listAuditLog: jest.fn(() => throwError(() => new Error('nope'))),
    });
    expect(cmp.loadError()).toBe(true);
    expect(cmp.loading()).toBe(false);
    fixture.detectChanges();
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('toggle opens then closes a single entry', async () => {
    const { cmp } = await setup();
    expect(cmp.isOpen(1)).toBe(false);
    cmp.toggle(1);
    expect(cmp.isOpen(1)).toBe(true);
    cmp.toggle(1);
    expect(cmp.isOpen(1)).toBe(false);
  });

  it('actionLabel localizes known actions and echoes unknown ones', async () => {
    const { cmp } = await setup();
    expect(cmp.actionLabel('status_change')).toBe('Statuswechsel');
    expect(cmp.actionLabel('made_up_action')).toBe('made_up_action');
  });

  it('mirrors the backend action catalog and labels every action in de and en', async () => {
    expect([...AUDIT_ACTIONS].sort()).toEqual([...BACKEND_AUDIT_ACTIONS].sort());
    for (const locale of ['de', 'en']) {
      localStorage.setItem('ap.locale', locale);
      TestBed.resetTestingModule();
      const { cmp } = await setup();
      for (const action of AUDIT_ACTIONS) {
        // The label never falls back to the raw key.
        expect(cmp.actionLabel(action)).not.toBe(action);
      }
    }
  });

  it('labels and links the target types of the recorded actions', async () => {
    localStorage.setItem('ap.locale', 'de');
    const { cmp } = await setup();
    expect(cmp.targetTypeLabel('fiscal_year')).toBe('Haushaltsjahr');
    expect(cmp.targetTypeLabel('protocol')).toBe('Protokoll');
    expect(cmp.targetTypeLabel('comment')).toBe('Kommentar');
    expect(cmp.targetTypeLabel('meeting')).toBe('Sitzung');
    expect(cmp.targetLink(entry(2, { targetType: 'meeting', targetId: 'm-1' }))).toEqual([
      '/meetings',
      'm-1',
    ]);
  });

  it('targetTypeLabel localizes known types and echoes unknown ones', async () => {
    const { cmp } = await setup();
    expect(cmp.targetTypeLabel('gremium')).toBe('Gremium');
    expect(cmp.targetTypeLabel('export')).toBe('Export');
    expect(cmp.targetTypeLabel('backup')).toBe('Sicherung');
    expect(cmp.targetTypeLabel('made_up_type')).toBe('made_up_type');
  });

  it('targetLink resolves a route per target type', async () => {
    const { cmp } = await setup();
    expect(cmp.targetLink(entry(1, { targetType: 'application', targetId: 'a-9' }))).toEqual([
      '/applications',
      'a-9',
    ]);
    expect(cmp.targetLink(entry(1, { targetType: 'vote', targetId: 'v-9' }))).toEqual([
      '/voting',
      'v-9',
    ]);
    expect(cmp.targetLink(entry(1, { targetType: 'gremium', targetId: 'g-9' }))).toEqual([
      '/admin/gremien',
    ]);
    expect(cmp.targetLink(entry(1, { targetType: 'budget_expense', targetId: 'e-9' }))).toEqual([
      '/expenses',
    ]);
    expect(cmp.targetLink(entry(1, { targetType: 'invoice', targetId: 'i-9' }))).toEqual([
      '/invoices',
    ]);
    // The guest settings live on the deadlines admin page (Z1).
    expect(
      cmp.targetLink(entry(1, { targetType: 'guest_application_settings', targetId: '1' })),
    ).toEqual(['/admin/deadlines']);
    expect(cmp.targetTypeLabel('guest_application_settings')).toBe('Anträge ohne Konto');
  });

  it('targetLink resolves the admin-list routes for the remaining target types', async () => {
    const { cmp } = await setup();
    const cases: [string, string[]][] = [
      ['application_type', ['/admin/forms']],
      ['role', ['/admin/roles']],
      ['role_assignment', ['/admin/users']],
      ['principal', ['/admin/users']],
      ['group_mapping', ['/admin/users']],
      ['webhook', ['/admin/webhooks']],
      ['site_config', ['/admin/branding']],
      ['budget', ['/budget']],
      ['budget_allocation', ['/budget']],
      ['budget_transfer', ['/budget']],
      ['fiscal_year', ['/budget']],
      ['flow', ['/admin/flow']],
      ['form', ['/admin/forms', 'x-1']],
      ['cd_variant', ['/admin/cd-variants']],
      ['notification_settings', ['/admin/notifications']],
      ['backup', ['/admin/backups']],
      ['erasure_request', ['/admin/privacy']],
      ['oauth_token', ['/admin/oauth-grants']],
      ['meeting_delegation', ['/admin/delegations']],
      ['delegation_substitute', ['/admin/delegations']],
    ];
    for (const [type, route] of cases) {
      expect(cmp.targetLink(entry(1, { targetType: type, targetId: 'x-1' }))).toEqual(route);
    }
  });

  it('targetLink returns null when there is no target', async () => {
    const { cmp } = await setup();
    expect(cmp.targetLink(entry(1, { targetType: null, targetId: null }))).toBeNull();
    expect(cmp.targetLink(entry(1, { targetType: 'application', targetId: null }))).toBeNull();
  });

  it('targetLink returns null for a target type without a registered route', async () => {
    const { cmp } = await setup();
    expect(cmp.targetLink(entry(1, { targetType: 'mystery', targetId: 'm-1' }))).toBeNull();
  });

  it('renders an "open target" link in the details when a route exists', async () => {
    const { fixture } = await setup({
      page: {
        items: [entry(1, { targetType: 'application', targetId: 'a-1' })],
        nextCursor: null,
        hasMore: false,
      },
    });
    entryToggle().click();
    fixture.detectChanges();
    const link = screen.getByRole('link');
    expect(link.getAttribute('href')).toBe('/applications/a-1');
  });

  it('targetText falls back to the localized type and a readable id', async () => {
    const { cmp } = await setup();
    expect(cmp.targetText(entry(1, { targetLabel: null }))).toBe('Benutzer · p-1');
    expect(
      cmp.targetText(entry(1, { action: 'config_change', targetType: 'flow', targetId: 'global', targetLabel: null })),
    ).toBe('Ablauf · global');
    expect(
      cmp.targetText(entry(1, { action: 'export', targetType: 'export', targetId: 'antraege.csv', targetLabel: null })),
    ).toContain('antraege.csv');
  });

  it('shows the resolved form name and never the raw application-type UUID', async () => {
    await setup({
      page: {
        items: [
          entry(1, {
            action: 'config_change',
            targetType: 'form',
            targetId: TYPE_UUID,
            targetLabel: 'Finanzantrag',
          }),
        ],
        nextCursor: null,
        hasMore: false,
      },
    });
    expect(screen.getByText('Formular · Finanzantrag')).toBeInTheDocument();
    expect(screen.queryByText(new RegExp(TYPE_UUID))).not.toBeInTheDocument();
  });

  it('drops a UUID target id from the row but keeps it in the details', async () => {
    const { fixture } = await setup({
      page: {
        items: [
          entry(1, {
            action: 'config_change',
            targetType: 'form',
            targetId: TYPE_UUID,
            targetLabel: null,
          }),
        ],
        nextCursor: null,
        hasMore: false,
      },
    });
    expect(screen.getByText('Formular')).toBeInTheDocument();
    expect(screen.queryByText(new RegExp(TYPE_UUID))).not.toBeInTheDocument();
    entryToggle().click();
    fixture.detectChanges();
    expect(screen.getByText(new RegExp(TYPE_UUID))).toBeInTheDocument();
  });

  it('shows the target id in the details even without a target type', async () => {
    const { fixture } = await setup({
      page: {
        items: [entry(1, { targetType: null, targetId: TYPE_UUID })],
        nextCursor: null,
        hasMore: false,
      },
    });
    entryToggle().click();
    fixture.detectChanges();
    expect(screen.getByText(new RegExp(TYPE_UUID))).toBeInTheDocument();
  });

  it('targetText uses the type alone, the id alone, or a dash', async () => {
    const { cmp } = await setup();
    expect(cmp.targetText(entry(1, { targetType: 'principal', targetId: null }))).toBe('Benutzer');
    expect(cmp.targetText(entry(1, { targetType: null, targetId: 'only-id' }))).toBe('only-id');
    expect(cmp.targetText(entry(1, { targetType: null, targetId: null }))).toBe('—');
  });

  it('actorLabel resolves the actor name, then the sub, then "System"', async () => {
    const { cmp } = await setup();
    expect(cmp.actorLabel(entry(1))).toBe('Root Admin');
    expect(cmp.actorLabel(entry(1, { actorName: null }))).toBe('kc|root');
    expect(cmp.actorLabel(entry(1, { actorName: null, actor: null }))).toBe('System');
  });

  it('dataRows stringifies primitives and JSON-encodes objects', async () => {
    const { cmp } = await setup();
    const rows = cmp
      .dataRows(entry(1, { data: { count: 3, flag: true, nested: { a: 1 }, note: 'hi' } }))
      .map((r) => [r.label, r.value]);
    expect(rows).toContainEqual(['count', '3']);
    expect(rows).toContainEqual(['flag', 'true']);
    expect(rows).toContainEqual(['nested', '{"a":1}']);
    expect(rows).toContainEqual(['note', 'hi']);
  });

  it('dataRows labels known keys and leaves the revision id to the target line', async () => {
    localStorage.setItem('ap.locale', 'de');
    const { cmp } = await setup();
    const rows = cmp.dataRows(entry(1, { data: { revisionId: 'rev-12', version: 12, other: 'x' } }));
    expect(rows).toEqual([
      { key: 'version', label: 'Revision', value: '12', known: true },
      { key: 'other', label: 'other', value: 'x', known: false },
    ]);
  });

  it('dataRows yields an empty list when data is null/absent', async () => {
    const { cmp } = await setup();
    expect(cmp.dataRows(entry(1, { data: null as unknown as Record<string, unknown> }))).toEqual([]);
  });

  // --- the chain check --------------------------------------------------------

  it('shows the newest stored check: intact, when, trigger and entries', async () => {
    const { cmp, container } = await setup();
    const v = cmp.verifyView();
    expect(v?.kind).toBe('ok');
    expect(v?.title).toBe('Audit-Kette intakt');
    expect(v?.sub).toContain('Zuletzt geprüft am 07.06.2026');
    expect(v?.sub).toContain('nächtliche Prüfung');
    expect(v?.sub).toContain('18.412 Einträge');
    expect(container.querySelector('.al__verify')).toHaveClass('al__verify--ok');
  });

  it('shows a broken chain as an error with the entry of the break', async () => {
    const { cmp } = await setup({
      latest: jest.fn(() => of({ ...CHECK, valid: false, brokenAt: 9, reason: 'hash_mismatch' })),
    });
    expect(cmp.verifyView()?.kind).toBe('error');
    expect(cmp.verifyView()?.title).toBe('Audit-Kette unterbrochen');
    expect(cmp.verifyView()?.sub).toMatch(/^Bruch bei Eintrag 9 · /);
  });

  it('says "not checked yet" before the first check', async () => {
    const never = await setup({ latest: jest.fn(() => of(null)) });
    expect(never.cmp.verifyView()).toEqual({ kind: 'muted', title: 'Audit-Kette noch nicht geprüft', sub: '' });
  });

  it('says "unknown" when the read of the check fails', async () => {
    const { cmp } = await setup({ latest: jest.fn(() => throwError(() => new Error('x'))) });
    expect(cmp.verifyView()?.title).toBe('Zustand der Audit-Kette unbekannt');
  });

  it('shows a placeholder while the check loads', async () => {
    const { cmp, container } = await setup({ latest: jest.fn(() => new Subject()) });
    expect(cmp.verifyView()).toBeNull();
    expect(container.querySelector('.al__verifySkel')).not.toBeNull();
  });

  it('"Jetzt prüfen" checks the chain and shows the new result', async () => {
    const { api, toast, cmp } = await setup();
    await userEvent.click(screen.getByRole('button', { name: /Jetzt prüfen/ }));
    expect(api.runAuditVerification).toHaveBeenCalled();
    expect(cmp.verifyView()?.sub).toContain('manuelle Prüfung');
    expect(toast.success).toHaveBeenCalledWith('Audit-Kette geprüft: intakt.');
    expect(cmp.verifying()).toBe(false);
  });

  it('toasts a broken result of "Jetzt prüfen"', async () => {
    const { toast, cmp } = await setup({
      run: jest.fn(() => of({ ...CHECK, valid: false, brokenAt: 3 })),
    });
    cmp.runVerify();
    expect(toast.success).toHaveBeenCalledWith('Audit-Kette geprüft: unterbrochen.');
  });

  it.each([
    [409, 'Es läuft schon eine Prüfung. Versuche es gleich noch einmal.'],
    [429, 'Die nächste Prüfung ist erst in einigen Minuten möglich.'],
    [500, 'Die Prüfung ist fehlgeschlagen.'],
  ])('names the reason when "Jetzt prüfen" answers %s', async (status, text) => {
    const { toast, cmp } = await setup({ run: jest.fn(() => throwError(() => ({ status }))) });
    cmp.runVerify();
    expect(toast.error).toHaveBeenCalledWith(text);
    expect(cmp.verifying()).toBe(false);
  });

  it('ignores a second "Jetzt prüfen" while one runs', async () => {
    const run = jest.fn(() => new Subject());
    const { cmp } = await setup({ run });
    cmp.runVerify();
    cmp.runVerify();
    expect(run).toHaveBeenCalledTimes(1);
  });

  it('hides "Jetzt prüfen" without audit.verify', async () => {
    await setup({ perms: ['audit.read'] });
    expect(screen.queryByRole('button', { name: /Jetzt prüfen/ })).toBeNull();
  });

  // --- the filter chips -------------------------------------------------------

  it('filters through the action and actor chips', async () => {
    const { listAuditLog, cmp } = await setup({ actors: [{ sub: 'kc|a', name: 'Alice' }, { sub: 'kc|b', name: null }] });
    expect(cmp.actionChip()).toBe('Aktion: Alle Aktionen');
    await userEvent.click(screen.getByRole('button', { name: 'Aktion: Alle Aktionen' }));
    await userEvent.click(screen.getByRole('option', { name: 'Statuswechsel' }));
    expect(listAuditLog).toHaveBeenLastCalledWith(expect.objectContaining({ action: 'status_change' }));
    expect(cmp.actionChip()).toBe('Aktion: Statuswechsel');
    await userEvent.click(screen.getByRole('button', { name: 'Akteur: Alle Akteure' }));
    // An actor without a name shows its sub.
    expect(screen.getByRole('option', { name: 'kc|b' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('option', { name: 'Alice' }));
    expect(listAuditLog).toHaveBeenLastCalledWith(expect.objectContaining({ actor: 'kc|a' }));
    expect(cmp.actorChip()).toBe('Akteur: Alice');
    // "Zurücksetzen" shows while a filter is set and clears them all.
    await userEvent.click(screen.getByRole('button', { name: 'Zurücksetzen' }));
    expect(cmp.activeFilterCount()).toBe(0);
    expect(screen.queryByRole('button', { name: 'Zurücksetzen' })).toBeNull();
  });

  it('filters by day through the date chips', async () => {
    const { listAuditLog, fixture } = await setup();
    const input = fixture.nativeElement.querySelectorAll('app-date-chip input[type=date]')[0] as HTMLInputElement;
    input.value = '2026-06-01';
    input.dispatchEvent(new Event('change'));
    fixture.detectChanges();
    expect(listAuditLog).toHaveBeenLastCalledWith(
      expect.objectContaining({ since: localDayBound('2026-06-01', false) }),
    );
    expect(screen.getByRole('button', { name: 'Von: 01.06.2026' })).toBeInTheDocument();
  });

  it('observes the sentinel and loads more when it intersects', async () => {
    let trigger: ((entries: { isIntersecting: boolean }[]) => void) | null = null;
    const disconnect = jest.fn();
    const observe = jest.fn();
    class IOStub {
      constructor(cb: (entries: { isIntersecting: boolean }[]) => void) {
        trigger = cb;
      }
      observe = observe;
      disconnect = disconnect;
    }
    const original = (globalThis as { IntersectionObserver?: unknown }).IntersectionObserver;
    (globalThis as { IntersectionObserver?: unknown }).IntersectionObserver =
      IOStub as unknown as typeof IntersectionObserver;

    const second: AuditPage = { items: [entry(2)], nextCursor: null, hasMore: false };
    const listAuditLog = jest
      .fn()
      .mockReturnValueOnce(of<AuditPage>({ items: [entry(1)], nextCursor: 1, hasMore: true }))
      .mockReturnValueOnce(of(second));
    const { cmp } = await setup({ listAuditLog });

    expect(observe).toHaveBeenCalled();
    trigger?.([{ isIntersecting: false }]);
    expect(listAuditLog).toHaveBeenCalledTimes(1);
    trigger?.([{ isIntersecting: true }]);
    expect(listAuditLog).toHaveBeenCalledTimes(2);
    expect(cmp.entries().map((e) => e.id)).toEqual([1, 2]);

    (globalThis as { IntersectionObserver?: unknown }).IntersectionObserver = original;
  });
});
