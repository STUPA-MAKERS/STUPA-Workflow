import { type Team, TeamsApiService } from '@core/api/teams.service';
import { ChangeDetectionStrategy, Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { screen } from '@testing-library/angular';
import { of, throwError } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import { GremienApiService, type GremiumOverview } from '@core/api/gremien.service';
import { AuthService } from '@core/auth/auth.service';
import { MEDIA, PageFrame } from '@stupa-makers/ui-kit';
import { runAxe } from '../../../../testing/a11y';
import { freeTeam, gremienApiMock, gremium, teamsApiMock } from '../../../../testing/gremien-fixtures';
import { matchMediaQueries } from '../../../../testing/meeting-fixtures';
import type { CalendarSubscribeComponent } from '../../meetings/calendar-subscribe/calendar-subscribe.component';
import { GremienNoneComponent } from '../gremien-none/gremien-none.component';
import { GREMIUM_VIEW_ALL, GremienComponent } from './gremien.component';
import { loadErrorToast, retryLoadError } from '../../../../testing/load-error';
import { IMAGE_PRELOADER, type ImagePreloader } from '@shared/util/preload-images';

@Component({
  changeDetection: ChangeDetectionStrategy.Eager,
  standalone: true, template: '<p>Detail</p>'
})
class DetailStub {}

const ITEMS: GremiumOverview[] = [
  gremium(),
  gremium({
    id: 'g-2',
    name: 'Wahlausschuss',
    slug: 'wa',
    roleKey: 'vorstand',
    roleName: { de: 'Vorstand', en: 'Board' },
    memberCount: 1,
    live: true,
    logoUrl: '/api/committees/g-2/logo',
  }),
  gremium({
    id: 'g-3',
    name: 'Fachschaft Informatik',
    slug: 'fs-inf',
    isMember: false,
    roleKey: null,
    roleName: null,
    memberCount: 12,
    nextMeeting: null,
  }),
];

async function start(
  url: string,
  opts: {
    items?: GremiumOverview[];
    viewAll?: boolean;
    media?: string[];
    overview?: jest.Mock;
    preload?: ImagePreloader;
    /** Teams besides the inherent teams of the Gremien. */
    teams?: readonly Team[];
    create?: boolean;
  } = {},
) {
  localStorage.setItem('ap.locale', 'de');
  const restore = matchMediaQueries(...(opts.media ?? []));
  const api = gremienApiMock({ overview: opts.overview ?? jest.fn(() => of(opts.items ?? ITEMS)) });
  const auth = {
    can: jest.fn(
      (p: string) => (opts.viewAll === true && p === GREMIUM_VIEW_ALL) || (opts.create === true && p === 'team.create'),
    ),
  };
  const teamsApi = teamsApiMock(api, opts.teams ?? []);
  TestBed.configureTestingModule({
    providers: [
      provideRouter([
        {
          path: 'teams',
          component: GremienComponent,
          children: [
            { path: '', component: GremienNoneComponent },
            { path: ':id', component: DetailStub },
          ],
        },
      ]),
      { provide: GremienApiService, useValue: api },
      { provide: TeamsApiService, useValue: teamsApi },
      { provide: AuthService, useValue: auth },
      { provide: ApiClient, useValue: {} },
      { provide: IMAGE_PRELOADER, useValue: opts.preload ?? (() => Promise.resolve()) },
    ],
  });
  const harness = await RouterTestingHarness.create();
  const cmp = await harness.navigateByUrl(url, GremienComponent);
  harness.detectChanges();
  const settle = async () => {
    await harness.fixture.whenStable();
    harness.detectChanges();
  };
  await settle();
  return { harness, cmp, api, teamsApi, restore, settle, router: TestBed.inject(Router), frame: TestBed.inject(PageFrame) };
}

describe('GremienComponent', () => {
  let restore: (() => void) | null = null;
  afterEach(() => {
    restore?.();
    restore = null;
    localStorage.clear();
  });

  it('opens no gremium by itself when the panes sit side by side (000664)', async () => {
    const s = await start('/teams', { media: [MEDIA.wide] });
    restore = s.restore;
    expect(s.cmp.split()).toBe(true);
    expect(s.frame.fill()).toBe(true);
    expect(s.router.url).toBe('/teams');
    expect(s.cmp.selectedId()).toBeNull();
    expect(screen.queryByText('Detail')).toBeNull();
    s.harness.fixture.destroy();
    expect(s.frame.fill()).toBe(false);
  });

  it('§NF/performance/loading/001280: keeps the skeleton until the logos of the first answer have loaded', async () => {
    let done!: () => void;
    const preload = jest.fn(() => new Promise<void>((r) => (done = r)));
    const s = await start('/teams', { preload });
    restore = s.restore;
    expect(preload).toHaveBeenCalledWith(['/api/committees/g-2/logo']);
    expect(s.cmp.showSkeleton()).toBe(true);
    expect(screen.queryByText('Wahlausschuss')).toBeNull();
    done();
    await s.settle();
    expect(s.cmp.showSkeleton()).toBe(false);
    expect(screen.getByText('Wahlausschuss')).toBeTruthy();
  });

  it('§NF/performance/loading/001280: does not wait without a logo', async () => {
    const preload = jest.fn(() => Promise.resolve());
    const s = await start('/teams', { preload, items: [gremium()] });
    restore = s.restore;
    expect(preload).not.toHaveBeenCalled();
    expect(s.cmp.showSkeleton()).toBe(false);
  });

  /** Without gremium.view_all there is no other gremium and no chip. */
  it('shows the own gremien with their members, and Läuft for a running meeting', async () => {
    const s = await start('/teams');
    restore = s.restore;
    expect(s.cmp.split()).toBe(false);
    expect(s.router.url).toBe('/teams');
    expect(s.api.overview).toHaveBeenCalledTimes(1);
    const rows = s.cmp.mine();
    expect(rows.map((r) => r.sub)).toEqual(['31 Mitglieder', '1 Mitglied']);
    expect(rows.map((r) => r.live)).toEqual([false, true]);
    expect(screen.queryByText('Di, 20.10.')).toBeNull();
    expect(s.cmp.others()).toEqual([]);
    expect(s.cmp.viewAll()).toBe(false);
    expect(screen.queryByText('Weitere Teams')).toBeNull();
    // The head of the group names the group only, without a count of the rows.
    expect(screen.getByRole('heading', { level: 2, name: 'Meine Teams' }).textContent?.trim()).toBe('Meine Teams');
    expect(screen.getByText('Sitzung läuft')).toBeTruthy();
    const link = screen.getByRole('link', { name: /Studierendenparlament/ });
    expect(link.getAttribute('href')).toBe('/teams/g-1');
    expect(s.cmp.searchPlaceholder()).toBe('2 Teams durchsuchen');
    expect(await runAxe(s.harness.routeNativeElement as HTMLElement)).toHaveNoViolations();
  });

  it('shows every gremium with gremium.view_all, and only the own ones on request', async () => {
    const s = await start('/teams', { viewAll: true });
    restore = s.restore;
    expect(s.cmp.others().map((r) => r.item?.id)).toEqual(['g-3']);
    expect(s.cmp.others()[0].sub).toBe('12 Mitglieder');
    expect(s.cmp.others()[0].live).toBe(false);
    expect(screen.getByText('Weitere Teams')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Teams' })).toBeInTheDocument();
    expect(s.cmp.searchPlaceholder()).toBe('3 Teams durchsuchen');
    s.cmp.setScope('mine');
    s.harness.detectChanges();
    expect(screen.getByRole('button', { name: 'Teams: Nur meine' })).toBeInTheDocument();
    expect(s.cmp.others()).toEqual([]);
    expect(s.cmp.searchPlaceholder()).toBe('2 Teams durchsuchen');
    s.cmp.setScope('anything');
    expect(s.cmp.scope()).toBe('all');
  });

  it('searches the name and the slug in the browser', async () => {
    const s = await start('/teams', { viewAll: true });
    restore = s.restore;
    s.cmp.query.set('WAHL');
    expect(s.cmp.mine().map((r) => r.item?.id)).toEqual(['g-2']);
    expect(s.cmp.others()).toEqual([]);
    s.cmp.query.set('fs-inf');
    expect(s.cmp.others().map((r) => r.item?.id)).toEqual(['g-3']);
    s.cmp.query.set('zzz');
    s.harness.detectChanges();
    expect(screen.getByText('Kein Team passt zur Suche.')).toBeTruthy();
  });

  it('says that the person is in no gremium', async () => {
    const s = await start('/teams', { items: [], media: [MEDIA.wide] });
    restore = s.restore;
    expect(s.router.url).toBe('/teams');
    expect(screen.getAllByText('Keine Teams').length).toBeGreaterThan(0);
  });

  it('reports a failed read and reads again', async () => {
    const overview = jest.fn((): ReturnType<GremienApiService['overview']> => throwError(() => new Error('x')));
    const s = await start('/teams', { overview });
    restore = s.restore;
    expect(loadErrorToast()).toContain('Die Teams konnten nicht geladen werden.');
    overview.mockReturnValue(of(ITEMS));
    retryLoadError();
    s.harness.detectChanges();
    expect(loadErrorToast()).toBeNull();
    expect(s.cmp.mine()).toHaveLength(2);
  });

  it('follows the open gremium and closes it, keeping the query', async () => {
    const s = await start('/teams/g-2?tab=members');
    restore = s.restore;
    expect(s.cmp.selectedId()).toBe('g-2');
    s.cmp.closeDetail();
    await s.settle();
    expect(s.router.url).toBe('/teams?tab=members');
    expect(s.cmp.selectedId()).toBeNull();
  });

  it('puts the calendar into the ⋮ menu on a phone', async () => {
    const s = await start('/teams', { media: [MEDIA.phone] });
    restore = s.restore;
    expect(screen.queryByRole('button', { name: 'Sitzungen abonnieren' })).toBeNull();
    // §ui-kit:000675: a phone list row ends with its last text, not with an arrow.
    expect((s.harness.routeNativeElement as HTMLElement).querySelector('app-row-chevron')).toBeNull();
    expect(s.cmp.phoneMenu().map((sec) => sec.items.map((i) => i.id))).toEqual([['calendar'], ['refresh']]);
    const abo = { open: jest.fn() } as unknown as CalendarSubscribeComponent;
    s.cmp.onPhoneMenu({ id: 'other', label: 'x' }, abo);
    expect(abo.open).not.toHaveBeenCalled();
    s.cmp.onPhoneMenu({ id: 'calendar', label: 'x' }, abo);
    expect(abo.open).toHaveBeenCalled();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const refresh = jest.spyOn((s.cmp as any).store, 'refresh');
    s.cmp.onPhoneMenu({ id: 'refresh', label: 'Aktualisieren' }, abo);
    expect(refresh).toHaveBeenCalled();
  });

  it('shows the calendar button on a wider screen', async () => {
    const s = await start('/teams');
    restore = s.restore;
    expect(screen.getByRole('button', { name: 'Sitzungen abonnieren' })).toBeTruthy();
  });

  describe('teams (spec 003072)', () => {
    it('puts each sub-team right under its parent, with its members, no role and no parent text', async () => {
      const teams = [
        freeTeam({ id: 't-1', name: 'Ersti-Woche' }),
        freeTeam({ id: 't-2', name: 'Party', parentId: 't-1', parentName: 'Ersti-Woche', canManage: false }),
        freeTeam({ id: 't-3', name: 'Presse', parentId: 'g-1', parentName: 'StuPa', canManage: false }),
        freeTeam({ id: 't-4', name: 'Solo', memberCount: 1 }),
        freeTeam({ id: 't-5', name: 'Zombie', gremiumId: 'g-gone', memberCount: null }),
      ];
      const s = await start('/teams', { teams, items: [gremium()] });
      restore = s.restore;
      expect(s.cmp.mine().map((r) => [r.team.name, r.depth, r.sub])).toEqual([
        ['Studierendenparlament', 0, '31 Mitglieder'],
        ['Presse', 1, '3 Mitglieder'],
        ['Ersti-Woche', 0, '3 Mitglieder'],
        ['Party', 1, '3 Mitglieder'],
        ['Solo', 0, '1 Mitglied'],
        ['Zombie', 0, ''],
      ]);
      const party = screen.getByRole('link', { name: 'Party' }).closest('app-list-item') as HTMLElement;
      expect(party.getAttribute('aria-level')).toBe('2');
      expect(screen.getByRole('link', { name: 'Party' }).getAttribute('href')).toBe('/teams/t-2');
      expect(await runAxe(s.harness.fixture.nativeElement)).toHaveNoViolations();
    });

    it('opens the inherent team of an old link to a Gremium, and the list for an unknown one', async () => {
      const s = await start('/teams?gremium=g-1', { items: [gremium()] });
      restore = s.restore;
      await s.settle();
      expect(s.router.url).toBe('/teams/g-1');
      await s.router.navigateByUrl('/teams?gremium=g-x');
      await s.settle();
      expect(s.router.url).toBe('/teams');
    });

    it('creates a team with team.create and opens it', async () => {
      const s = await start('/teams', { create: true, media: [MEDIA.wide] });
      restore = s.restore;
      expect(s.cmp.canCreate()).toBe(true);
      screen.getByRole('button', { name: 'Team anlegen' }).click();
      s.harness.detectChanges();
      expect(s.cmp.createOpen()).toBe(true);
      s.cmp.created({ team: freeTeam({ id: 't-new' }), members: [], subTeams: [] });
      await s.settle();
      expect(s.teamsApi.list).toHaveBeenCalledTimes(2);
      expect(s.router.url).toBe('/teams/t-new');
    });

    it('puts "Team anlegen" into the ⋮ menu on a phone, and hides it without team.create', async () => {
      const s = await start('/teams', { create: true, media: [MEDIA.phone] });
      restore = s.restore;
      expect(s.cmp.phoneMenu()[0].items.map((i) => i.id)).toEqual(['create', 'calendar']);
      s.cmp.onPhoneMenu({ id: 'create', label: 'Team anlegen' }, {} as CalendarSubscribeComponent);
      expect(s.cmp.createOpen()).toBe(true);
    });
  });
});

