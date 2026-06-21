import { Subject, of, throwError } from 'rxjs';
import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import { I18nService } from '@core/i18n/i18n.service';
import type { AuditActor, AuditEntry, AuditPage } from '../admin.models';
import { AdminApiService } from '../admin-api.service';
import { AuditLogComponent } from './audit-log.component';

/**
 * Typed view onto the component's protected surface so tests can drive the
 * filter setters / paging helpers directly (they all funnel through `load`).
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
  dayLabel(g: { date: Date }): string;
  icon(action: string): string;
  actionLabel(action: string): string;
  targetTypeLabel(type: string): string;
  targetLink(e: AuditEntry): string[] | null;
  message(e: AuditEntry): string;
  dataPairs(e: AuditEntry): [string, string][];
  activeFilterCount(): number;
  actionOptions(): { value: string; label: string }[];
  groups(): { key: string; date: Date; entries: AuditEntry[] }[];
  loadError(): boolean;
  loading(): boolean;
  hasMore(): boolean;
  entries(): AuditEntry[];
};

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

interface SetupOpts {
  page?: AuditPage;
  actors?: AuditActor[];
  actorsError?: boolean;
  listAuditLog?: jest.Mock;
}

async function setup(opts: SetupOpts = {}) {
  const page = opts.page ?? { items: [entry(1)], nextCursor: null, hasMore: false };
  const listAuditLog = opts.listAuditLog ?? jest.fn(() => of(page));
  const listAuditActors = opts.actorsError
    ? jest.fn(() => throwError(() => new Error('boom')))
    : jest.fn(() => of(opts.actors ?? []));
  const api = { listAuditLog, listAuditActors };
  const view = await render(AuditLogComponent, {
    providers: [provideRouter([]), { provide: AdminApiService, useValue: api }],
  });
  const cmp = view.fixture.componentInstance as unknown as Cmp;
  return { ...view, cmp, listAuditLog, listAuditActors };
}

describe('AuditLogComponent (#45)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  // --- initial load + rendering --------------------------------------------
  it('lists audit entries with cursor paging and human-readable rendering', async () => {
    const { fixture, listAuditLog } = await setup({
      page: { items: [entry(1)], nextCursor: null, hasMore: false },
    });
    expect(listAuditLog).toHaveBeenCalledWith(
      expect.objectContaining({ limit: 50, before: undefined }),
    );
    expect(
      screen.getByText(/Root Admin hat Rollen\/Rechte geändert \(principal:p-1\)\./),
    ).toBeInTheDocument();
    screen.getByRole('button', { expanded: false }).click();
    fixture.detectChanges();
    expect(screen.getAllByText('Rollen/Rechte').length).toBeGreaterThan(0);
  });

  it('renders a fallback message for unknown action types', async () => {
    await setup({
      page: { items: [entry(1, { action: 'mystery_event', actorName: null })], nextCursor: null, hasMore: false },
    });
    expect(screen.getByText(/mystery_event \(principal:p-1\)/)).toBeInTheDocument();
  });

  it('shows the empty state when there are no entries', async () => {
    await setup({ page: { items: [], nextCursor: null, hasMore: false } });
    expect(screen.getByText('Keine Audit-Einträge.')).toBeInTheDocument();
  });

  it('offers "load more" while more entries remain', async () => {
    await setup({ page: { items: [entry(1)], nextCursor: 1, hasMore: true } });
    expect(screen.getByRole('button', { name: 'Mehr laden' })).toBeInTheDocument();
  });

  it('prefers the resolved target label in the sentence', async () => {
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
    expect(screen.getByText(/Beamer kaufen/)).toBeInTheDocument();
    expect(screen.queryByText(/application:a-1/)).not.toBeInTheDocument();
  });

  it('groups entries under a day heading and expands details on click', async () => {
    const { fixture } = await setup({
      page: { items: [entry(1, { data: { rows: 7 } })], nextCursor: null, hasMore: false },
    });
    expect(screen.getByRole('heading', { level: 2 }).textContent).toMatch(/2026/);
    expect(screen.queryByText('rows')).not.toBeInTheDocument();
    screen.getByRole('button', { expanded: false }).click();
    fixture.detectChanges();
    expect(screen.getByText('rows')).toBeInTheDocument();
    expect(screen.getByText('7')).toBeInTheDocument();
  });

  it('renders embedded data UUIDs and the actor as "<name> · <uuid>" (#no-uuids-in-ui)', async () => {
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
    screen.getByRole('button', { expanded: false }).click();
    fixture.detectChanges();
    // data-Chip: aufgelöste UUID als „<Name> · <uuid>".
    expect(screen.getByText('Finanzausschuss · g-1')).toBeInTheDocument();
    // Akteur-Detail: Klarname · sub.
    expect(screen.getByText('Root Admin · kc|root')).toBeInTheDocument();
  });

  it('falls back to the raw UUID in data chips when unresolved', async () => {
    const { fixture } = await setup({
      page: { items: [entry(1, { data: { gremiumId: 'g-unknown' } })], nextCursor: null, hasMore: false },
    });
    screen.getByRole('button', { expanded: false }).click();
    fixture.detectChanges();
    expect(screen.getByText('g-unknown')).toBeInTheDocument();
  });

  // --- actors load (success + error) ---------------------------------------
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

  // --- filter setters reload with the right query params -------------------
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
    expect(listAuditLog).toHaveBeenCalledWith(
      expect.objectContaining({ since: '2026-06-01T00:00:00' }),
    );
  });

  it('setUntil expands the date to an end-of-day bound', async () => {
    const { cmp, listAuditLog } = await setup();
    listAuditLog.mockClear();
    cmp.setUntil('2026-06-30');
    expect(listAuditLog).toHaveBeenCalledWith(
      expect.objectContaining({ until: '2026-06-30T23:59:59' }),
    );
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

  // --- cursor paging + loadMore --------------------------------------------
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
    // Defensive branch: hasMore true while nextCursor is null → before falls back to undefined.
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
    // First call (constructor reload) hangs; a filter change must not fire a second.
    const listAuditLog = jest.fn(() => subj.asObservable());
    const { cmp } = await setup({ listAuditLog });
    expect(cmp.loading()).toBe(true);
    expect(listAuditLog).toHaveBeenCalledTimes(1);
    // A filter setter triggers reload → load(true), but the loading guard holds.
    cmp.setAction('login');
    expect(listAuditLog).toHaveBeenCalledTimes(1);
    subj.next({ items: [], nextCursor: null, hasMore: false });
    subj.complete();
    expect(cmp.loading()).toBe(false);
  });

  // --- error path -----------------------------------------------------------
  it('flags a load error and shows the alert', async () => {
    const { cmp, fixture } = await setup({
      listAuditLog: jest.fn(() => throwError(() => new Error('nope'))),
    });
    expect(cmp.loadError()).toBe(true);
    expect(cmp.loading()).toBe(false);
    fixture.detectChanges();
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  // --- toggle / isOpen ------------------------------------------------------
  it('toggle opens then closes a single entry', async () => {
    const { cmp } = await setup();
    expect(cmp.isOpen(1)).toBe(false);
    cmp.toggle(1);
    expect(cmp.isOpen(1)).toBe(true);
    cmp.toggle(1);
    expect(cmp.isOpen(1)).toBe(false);
  });

  // --- dayLabel branches ----------------------------------------------------
  it('dayLabel returns Today / Yesterday / a full date', async () => {
    const { cmp } = await setup();
    const today = new Date();
    const yesterday = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1);
    const old = new Date(2020, 0, 15);
    expect(cmp.dayLabel({ date: today })).toBe('Heute');
    expect(cmp.dayLabel({ date: yesterday })).toBe('Gestern');
    expect(cmp.dayLabel({ date: old })).toMatch(/2020/);
  });

  it('dayLabel uses the en-US locale when the UI is English', async () => {
    localStorage.setItem('ap.locale', 'en');
    const { cmp, fixture } = await setup();
    fixture.debugElement.injector.get(I18nService).setLocale('en');
    const old = new Date(2020, 0, 15);
    expect(cmp.dayLabel({ date: old })).toMatch(/2020/);
    expect(cmp.dayLabel({ date: new Date() })).toBe('Today');
  });

  // --- icon -----------------------------------------------------------------
  it('icon maps known actions and falls back to the audit glyph', async () => {
    const { cmp } = await setup();
    expect(cmp.icon('login')).toBe('key');
    expect(cmp.icon('budget_expense_create')).toBe('euro');
    expect(cmp.icon('totally_unknown')).toBe('audit');
  });

  // --- actionLabel ----------------------------------------------------------
  it('actionLabel localizes known actions and echoes unknown ones', async () => {
    const { cmp } = await setup();
    expect(cmp.actionLabel('status_change')).toBe('Statuswechsel');
    expect(cmp.actionLabel('made_up_action')).toBe('made_up_action');
  });

  // --- targetTypeLabel ------------------------------------------------------
  it('targetTypeLabel localizes known types and echoes unknown ones', async () => {
    const { cmp } = await setup();
    expect(cmp.targetTypeLabel('gremium')).toBe('Gremium');
    expect(cmp.targetTypeLabel('made_up_type')).toBe('made_up_type');
  });

  // --- targetLink branches --------------------------------------------------
  it('targetLink resolves a route per target type', async () => {
    const { cmp } = await setup();
    expect(cmp.targetLink(entry(1, { targetType: 'application', targetId: 'a-9' }))).toEqual([
      '/applications',
      'a-9',
    ]);
    expect(cmp.targetLink(entry(1, { targetType: 'vote', targetId: 'v-9' }))).toEqual([
      '/voting/vote',
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
    screen.getByRole('button', { expanded: false }).click();
    fixture.detectChanges();
    const link = screen.getByRole('link');
    expect(link.getAttribute('href')).toBe('/applications/a-1');
  });

  // --- message / targetLabel fallbacks --------------------------------------
  it('message falls back to type:id when no resolved label is present', async () => {
    const { cmp } = await setup();
    expect(cmp.message(entry(1, { targetLabel: null }))).toMatch(/principal:p-1/);
  });

  it('targetLabel uses just the target type when no id is present', async () => {
    const { cmp } = await setup();
    // unknown action → fallback msg "{actor}: {action} ({target})." with target = type only
    expect(
      cmp.message(entry(1, { action: 'mystery', targetType: 'principal', targetId: null })),
    ).toMatch(/\(principal\)/);
  });

  it('targetLabel uses just the target id when no type is present', async () => {
    const { cmp } = await setup();
    expect(
      cmp.message(entry(1, { action: 'mystery', targetType: null, targetId: 'only-id' })),
    ).toMatch(/\(only-id\)/);
  });

  it('targetLabel uses an em-dash when neither type nor id is present', async () => {
    const { cmp } = await setup();
    expect(
      cmp.message(entry(1, { action: 'mystery', targetType: null, targetId: null })),
    ).toMatch(/\(—\)/);
  });

  it('message resolves the actor name, then sub, then the system label', async () => {
    const { cmp } = await setup();
    expect(cmp.message(entry(1))).toMatch(/Root Admin/);
    expect(cmp.message(entry(1, { actorName: null }))).toMatch(/kc\|root/);
    expect(cmp.message(entry(1, { actorName: null, actor: null }))).toMatch(/System/);
  });

  // --- dataPairs ------------------------------------------------------------
  it('dataPairs stringifies primitives and JSON-encodes objects', async () => {
    const { cmp } = await setup();
    const pairs = cmp.dataPairs(
      entry(1, { data: { count: 3, flag: true, nested: { a: 1 }, note: 'hi' } }),
    );
    expect(pairs).toContainEqual(['count', '3']);
    expect(pairs).toContainEqual(['flag', 'true']);
    expect(pairs).toContainEqual(['nested', '{"a":1}']);
    expect(pairs).toContainEqual(['note', 'hi']);
  });

  it('dataPairs yields an empty list when data is null/absent', async () => {
    const { cmp } = await setup();
    expect(cmp.dataPairs(entry(1, { data: null as unknown as Record<string, unknown> }))).toEqual([]);
  });

  // --- groups grouping logic ------------------------------------------------
  it('groups consecutive same-day entries together and splits across days', async () => {
    const { cmp } = await setup({
      page: {
        items: [
          entry(1, { at: '2026-06-07T09:00:00+00:00' }),
          entry(2, { at: '2026-06-07T11:00:00+00:00' }),
          entry(3, { at: '2026-06-05T08:00:00+00:00' }),
        ],
        nextCursor: null,
        hasMore: false,
      },
    });
    const groups = cmp.groups();
    expect(groups).toHaveLength(2);
    expect(groups[0].entries.map((e) => e.id)).toEqual([1, 2]);
    expect(groups[1].entries.map((e) => e.id)).toEqual([3]);
  });

  // --- IntersectionObserver wiring ------------------------------------------
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
    // Not intersecting → no extra load.
    trigger?.([{ isIntersecting: false }]);
    expect(listAuditLog).toHaveBeenCalledTimes(1);
    // Intersecting → loadMore → second page appended.
    trigger?.([{ isIntersecting: true }]);
    expect(listAuditLog).toHaveBeenCalledTimes(2);
    expect(cmp.entries().map((e) => e.id)).toEqual([1, 2]);

    (globalThis as { IntersectionObserver?: unknown }).IntersectionObserver = original;
  });
});
