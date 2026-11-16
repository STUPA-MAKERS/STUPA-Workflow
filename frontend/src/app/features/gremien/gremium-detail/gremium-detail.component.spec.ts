import { Component, input, output } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { screen, within } from '@testing-library/angular';
import { NEVER, of, throwError } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import { GremienApiService, type GremiumOverview } from '@core/api/gremien.service';
import { AuthService } from '@core/auth/auth.service';
import { MEDIA } from '@stupa-makers/ui-kit';
import { runAxe } from '../../../../testing/a11y';
import { gremienApiMock, gremium } from '../../../../testing/gremien-fixtures';
import { matchMediaQueries } from '../../../../testing/meeting-fixtures';
import { PageFrameService } from '../../../layout/page-frame.service';
import type { CalendarSubscribeComponent } from '../../meetings/calendar-subscribe/calendar-subscribe.component';
import { CreateMeetingDialogComponent } from '../../meetings/create-meeting-dialog/create-meeting-dialog.component';
import { TodosApiService, type TodoBoard, type TodoBoardSummary } from '@core/api/todos.service';
import { board, tile } from '../../../../testing/todo-fixtures';
import { GremienComponent } from '../gremien-page/gremien.component';
import { GremiumDetailComponent } from './gremium-detail.component';

@Component({ selector: 'app-create-meeting-dialog', standalone: true, template: '' })
class CreateMeetingStub {
  readonly open = input(false);
  readonly gremiumId = input('');
  readonly closed = output<void>();
}

@Component({ standalone: true, template: '<p>Ziel</p>' })
class TargetStub {}

const ITEMS: GremiumOverview[] = [
  gremium(),
  gremium({
    id: 'g-2',
    name: 'Wahlausschuss',
    slug: 'wa',
    isMember: false,
    roleKey: null,
    roleName: null,
    memberCount: 1,
    live: true,
    quorumPercent: null,
    protocolsPublic: false,
    allowVoteDelegation: false,
    nextMeeting: { id: 'm-live', title: 'Wahlsitzung', date: '2026-10-15', startTime: '10:00:00', status: 'live' },
  }),
];

interface StartOptions {
  media?: string[];
  plan?: boolean;
  admin?: boolean;
  overview?: jest.Mock;
  /** The boards the person reads in the Gremium. */
  boards?: readonly Partial<TodoBoardSummary>[];
  board?: TodoBoard;
}

async function start(url: string, opts: StartOptions = {}) {
  localStorage.setItem('ap.locale', 'de');
  const restore = matchMediaQueries(...(opts.media ?? []));
  const api = gremienApiMock({ overview: opts.overview ?? jest.fn(() => of(ITEMS)) });
  const auth = {
    can: jest.fn((p: string) => (p === 'admin.gremien' && opts.admin === true) || p === 'gremium.view_all'),
    canInGremium: jest.fn((_id: string, p: string) => opts.plan === true && p === 'session.manage'),
  };
  const todos = {
    boards: jest.fn(() => of(opts.boards ?? [])),
    board: jest.fn(() => of(opts.board)),
    linked: jest.fn(() => of([])),
  };
  TestBed.overrideComponent(GremiumDetailComponent, {
    remove: { imports: [CreateMeetingDialogComponent] },
    add: { imports: [CreateMeetingStub] },
  });
  TestBed.configureTestingModule({
    providers: [
      provideRouter([
        {
          path: 'committees',
          component: GremienComponent,
          children: [{ path: ':id', component: GremiumDetailComponent }],
        },
        { path: 'meetings', component: TargetStub },
        { path: 'meetings/:id', component: TargetStub },
        { path: 'voting', component: TargetStub },
        { path: 'todos/:id', component: TargetStub },
        { path: 'admin/committees/:id/members', component: TargetStub },
      ]),
      { provide: GremienApiService, useValue: api },
      { provide: AuthService, useValue: auth },
      { provide: ApiClient, useValue: {} },
      { provide: TodosApiService, useValue: todos },
    ],
  });
  const harness = await RouterTestingHarness.create();
  await harness.navigateByUrl(url);
  const settle = async () => {
    harness.detectChanges();
    await harness.fixture.whenStable();
    harness.detectChanges();
  };
  await settle();
  const router = TestBed.inject(Router);
  const detail = () =>
    harness.fixture.debugElement.query((d) => d.componentInstance instanceof GremiumDetailComponent)
      ?.componentInstance as GremiumDetailComponent;
  return { harness, api, auth, todos, restore, settle, router, detail, frame: TestBed.inject(PageFrameService) };
}

describe('GremiumDetailComponent', () => {
  let restore: (() => void) | null = null;
  afterEach(() => {
    restore?.();
    restore = null;
    localStorage.clear();
  });

  it('shows the head with role, facts and actions, and the meetings tab', async () => {
    const s = await start('/committees/g-1', { media: [MEDIA.wide] });
    restore = s.restore;
    const d = s.detail();
    expect(d.split()).toBe(true);
    expect(screen.getByRole('heading', { level: 2, name: 'Studierendenparlament' })).toBeTruthy();
    expect(d.roleLabel()).toBe('Mitglied');
    expect(d.facts()).toEqual([
      'Deine Rolle: Mitglied',
      '31 Mitglieder',
      'Beschlussfähig ab 50 %',
      'Protokolle öffentlich',
      'Stimmübertragung erlaubt',
    ]);
    expect(d.tab()).toBe('meetings');
    expect(s.api.meetings).toHaveBeenCalledWith('g-1');
    expect(s.api.members).not.toHaveBeenCalled();
    expect(d.tabs().map((t) => t.label)).toEqual(['Sitzungen', 'Mitglieder', 'Anwesenheit', 'Beschlüsse']);
    expect(s.frame.crumbLabel()).toEqual({ url: '/committees/g-1', label: 'Studierendenparlament' });
    const sheet = within(s.harness.fixture.nativeElement.querySelector('app-gremium-detail') as HTMLElement);
    expect(sheet.getByRole('button', { name: 'Sitzungen abonnieren' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Gremium verwalten' })).toBeNull();
    expect(screen.queryByRole('button', { name: /Sitzung planen/ })).toBeNull();
    expect(d.menu()[0].items.map((i) => i.id)).toEqual(['meetings', 'votes']);
    expect(await runAxe(s.harness.routeNativeElement as HTMLElement)).toHaveNoViolations();

    screen.getByRole('button', { name: 'Nächste Sitzung' }).click();
    await s.settle();
    expect(s.router.url).toBe('/meetings/m-9');
    expect(s.frame.crumbLabel()).toBeNull();
  });

  it('keeps the tab in the URL and the visited panels rendered', async () => {
    const s = await start('/committees/g-1');
    restore = s.restore;
    const d = s.detail();
    d.selectTab('members');
    await s.settle();
    expect(s.router.url).toBe('/committees/g-1?tab=members');
    expect(s.api.members).toHaveBeenCalledWith('g-1', false);
    d.selectTab('attendance');
    await s.settle();
    expect([...d.visited()]).toEqual(['meetings', 'members', 'attendance']);
    expect(s.api.attendance).toHaveBeenCalled();
    d.selectTab('decisions');
    await s.settle();
    expect(s.api.decisions).toHaveBeenCalled();
    d.selectTab('meetings');
    await s.settle();
    expect(s.router.url).toBe('/committees/g-1');
    expect(d.tab()).toBe('meetings');
  });

  it('opens an unknown tab of the URL as the meetings', async () => {
    const s = await start('/committees/g-1?tab=uebersicht');
    restore = s.restore;
    expect(s.detail().tab()).toBe('meetings');
  });

  it('starts afresh for another gremium', async () => {
    const s = await start('/committees/g-1?tab=members');
    restore = s.restore;
    const d = s.detail();
    expect([...d.visited()]).toEqual(['members']);
    await s.router.navigateByUrl('/committees/g-2');
    await s.settle();
    expect([...d.visited()]).toEqual(['meetings']);
    expect(d.roleLabel()).toBe('');
    expect(d.facts()).toEqual(['1 Mitglied']);
    expect(screen.getByRole('button', { name: 'Zur laufenden Sitzung' })).toBeTruthy();
  });

  it('plans a meeting with session.manage and opens the administration with admin.gremien', async () => {
    const s = await start('/committees/g-1', { plan: true, admin: true });
    restore = s.restore;
    const d = s.detail();
    screen.getByRole('button', { name: /Sitzung planen/ }).click();
    s.harness.detectChanges();
    expect(d.createOpen()).toBe(true);
    const stub = s.harness.fixture.debugElement.query((x) => x.componentInstance instanceof CreateMeetingStub)
      .componentInstance as CreateMeetingStub;
    expect(stub.open()).toBe(true);
    expect(stub.gremiumId()).toBe('g-1');
    stub.closed.emit();
    expect(d.createOpen()).toBe(false);

    screen.getByRole('button', { name: 'Gremium verwalten' }).click();
    await s.settle();
    expect(s.router.url).toBe('/admin/committees/g-1/members');
  });

  it('runs every entry of the ⋮ menu', async () => {
    const s = await start('/committees/g-1');
    restore = s.restore;
    const d = s.detail();
    const abo = { open: jest.fn() } as unknown as CalendarSubscribeComponent;
    d.onMenu({ id: 'calendar', label: '' }, abo);
    expect(abo.open).toHaveBeenCalled();

    d.onMenu({ id: 'votes', label: '' }, abo);
    await s.settle();
    expect(s.router.url).toBe('/voting?committee=g-1');

    await s.router.navigateByUrl('/committees/g-1');
    await s.settle();
    s.detail().onMenu({ id: 'admin', label: '' }, abo);
    await s.settle();
    expect(s.router.url).toBe('/admin/committees/g-1/members');

    await s.router.navigateByUrl('/committees/g-1');
    await s.settle();
    s.detail().onMenu({ id: 'next', label: '' }, abo);
    await s.settle();
    expect(s.router.url).toBe('/meetings/m-9');

    await s.router.navigateByUrl('/committees/g-1');
    await s.settle();
    s.detail().onMenu({ id: 'meetings', label: '' }, abo);
    await s.settle();
    expect(s.router.url).toBe('/meetings');
  });

  it('moves the actions into the ⋮ menu on a phone', async () => {
    const s = await start('/committees/g-1', { media: [MEDIA.phone], plan: true, admin: true });
    restore = s.restore;
    const d = s.detail();
    expect(screen.queryByRole('button', { name: 'Sitzungen abonnieren' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Gremium verwalten' })).toBeNull();
    expect(d.showNext()).toBe(false);
    expect(d.menu()[0].items.map((i) => i.id)).toEqual(['calendar', 'next', 'admin', 'meetings', 'votes']);
  });

  it('keeps "Nächste Sitzung" as the one action on a phone without planning', async () => {
    const s = await start('/committees/g-2', { media: [MEDIA.phone] });
    restore = s.restore;
    const d = s.detail();
    expect(d.showNext()).toBe(true);
    expect(d.menu()[0].items.map((i) => i.id)).toEqual(['calendar', 'meetings', 'votes']);
  });

  /** Spec 000758: the detail leaves out the parts of a feature that is off. */
  it('opens on the members without Sitzungen, Abstimmungen, Boards and Kalender', async () => {
    localStorage.setItem('ap.features.off', JSON.stringify(['meetings', 'voting', 'todos', 'calendar']));
    const s = await start('/committees/g-1', { media: [MEDIA.phone], plan: true, boards: [{ id: 'b-1', kind: 'gremium' }] });
    restore = s.restore;
    const d = s.detail();
    expect(d.tabs().map((t) => t.label)).toEqual(['Mitglieder']);
    expect(d.tab()).toBe('members');
    expect(s.api.meetings).not.toHaveBeenCalled();
    expect(s.todos.boards).not.toHaveBeenCalled();
    expect(d.canPlan()).toBe(false);
    expect(d.showNext()).toBe(false);
    expect(d.menu()[0].items.map((i) => i.id)).toEqual([]);
    expect(screen.queryByRole('button', { name: /Sitzung planen/ })).toBeNull();
  });

  it('keeps the first tab out of the URL while Sitzungen is off', async () => {
    localStorage.setItem('ap.features.off', JSON.stringify(['meetings']));
    const s = await start('/committees/g-1?tab=attendance', { media: [MEDIA.wide] });
    restore = s.restore;
    const d = s.detail();
    expect(d.tab()).toBe('members');
    expect(d.tabs().map((t) => t.label)).toEqual(['Mitglieder', 'Beschlüsse']);
    d.selectTab('decisions');
    await s.settle();
    expect(s.router.url).toBe('/committees/g-1?tab=decisions');
    d.selectTab('members');
    await s.settle();
    expect(s.router.url).toBe('/committees/g-1');
    const sheet = within(s.harness.fixture.nativeElement.querySelector('app-gremium-detail') as HTMLElement);
    expect(sheet.getByRole('button', { name: 'Sitzungen abonnieren' })).toBeTruthy();
  });

  it('says when the gremium is not there, or the list failed', async () => {
    const s = await start('/committees/g-x');
    restore = s.restore;
    expect(screen.getByText('Gremium nicht gefunden')).toBeTruthy();
    s.detail().openNext();
    s.detail().openAdmin();
    await s.settle();
    expect(s.router.url).toBe('/admin/committees/g-x/members');
  });

  it('shows the list error in the sheet', async () => {
    const s = await start('/committees/g-1', { overview: jest.fn(() => throwError(() => new Error('x'))) });
    restore = s.restore;
    expect(screen.getAllByText('Die Gremien konnten nicht geladen werden.').length).toBeGreaterThan(0);
  });

  it('shows a skeleton while the list loads', async () => {
    const s = await start('/committees/g-1', { overview: jest.fn(() => NEVER) });
    restore = s.restore;
    expect(s.harness.routeNativeElement?.querySelector('.gd--busy')).toBeTruthy();
  });

  describe('tab To-Dos (spec 000551)', () => {
    const boards = [{ id: 'b-7', name: 'Studierendenparlament', kind: 'gremium' as const, gremiumId: 'g-1', canWrite: false }];
    const gremiumBoard = board({
      id: 'b-7',
      cards: [
        tile({ id: 'k-2', columnId: 'c-2', rank: 'a', title: 'In Arbeit zuerst?' }),
        tile({ id: 'k-1', columnId: 'c-1', rank: 'b', title: 'Raum buchen' }),
        tile({ id: 'k-3', columnId: 'c-4', title: 'Bus anfragen' }),
      ],
    });

    it('shows the open cards of the board of the Gremium, in board order', async () => {
      const s = await start('/committees/g-1?tab=todos', { boards, board: gremiumBoard });
      restore = s.restore;
      const d = s.detail();
      expect(s.todos.boards).toHaveBeenCalledWith('g-1');
      expect(d.tab()).toBe('todos');
      expect(d.tabs().map((t) => t.label)).toEqual(['Sitzungen', 'Mitglieder', 'Anwesenheit', 'Beschlüsse', 'To-Dos']);
      expect(s.todos.board).toHaveBeenCalledWith('b-7');
      const links = screen.getAllByRole('link').filter((a) => a.getAttribute('href')?.startsWith('/todos?card='));
      expect(links.map((a) => a.textContent?.trim())).toEqual(['Raum buchen', 'In Arbeit zuerst?']);
      expect(screen.queryByText('Bus anfragen')).toBeNull();
      expect(d.menu()[0].items.map((i) => i.id)).toEqual(['board', 'meetings', 'votes']);
      d.onMenu({ id: 'board', label: '' }, { open: jest.fn() } as unknown as CalendarSubscribeComponent);
      await s.settle();
      expect(s.router.url).toBe('/todos/b-7');
    });

    it('has no tab To-Dos when the person reads no board of the Gremium', async () => {
      const s = await start('/committees/g-1?tab=todos', { boards: [] });
      restore = s.restore;
      const d = s.detail();
      expect(d.tab()).toBe('meetings');
      expect(d.tabs().map((t) => t.id)).not.toContain('todos');
      expect(d.menu()[0].items.map((i) => i.id)).toEqual(['meetings', 'votes']);
    });

    it('has no tab To-Dos when the boards fail to load', async () => {
      TestBed.overrideProvider(TodosApiService, {
        useValue: { boards: jest.fn(() => throwError(() => new Error('x'))), board: jest.fn(), linked: jest.fn() },
      });
      const s = await start('/committees/g-1?tab=todos');
      restore = s.restore;
      expect(s.detail().tabs().map((t) => t.id)).not.toContain('todos');
    });

    it('shows the empty state when the board fails to load', async () => {
      TestBed.overrideProvider(TodosApiService, {
        useValue: {
          boards: jest.fn(() => of(boards)),
          board: jest.fn(() => throwError(() => new Error('x'))),
          linked: jest.fn(() => of([])),
        },
      });
      const s = await start('/committees/g-1?tab=todos');
      restore = s.restore;
      expect(screen.getByText('Keine offenen To-Dos')).toBeTruthy();
    });

    it('says so when the board has no open card', async () => {
      const s = await start('/committees/g-1?tab=todos', { boards, board: board({ id: 'b-7', cards: [] }) });
      restore = s.restore;
      expect(screen.getByText('Keine offenen To-Dos')).toBeTruthy();
    });
  });
});
