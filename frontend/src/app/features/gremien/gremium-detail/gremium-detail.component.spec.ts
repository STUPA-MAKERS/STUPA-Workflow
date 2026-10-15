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
}

async function start(url: string, opts: StartOptions = {}) {
  localStorage.setItem('ap.locale', 'de');
  const restore = matchMediaQueries(...(opts.media ?? []));
  const api = gremienApiMock({ overview: opts.overview ?? jest.fn(() => of(ITEMS)) });
  const auth = {
    can: jest.fn((p: string) => (p === 'admin.gremien' && opts.admin === true) || p === 'gremium.view_all'),
    canInGremium: jest.fn((_id: string, p: string) => opts.plan === true && p === 'session.manage'),
  };
  TestBed.overrideComponent(GremiumDetailComponent, {
    remove: { imports: [CreateMeetingDialogComponent] },
    add: { imports: [CreateMeetingStub] },
  });
  TestBed.configureTestingModule({
    providers: [
      provideRouter([
        {
          path: 'gremien',
          component: GremienComponent,
          children: [{ path: ':id', component: GremiumDetailComponent }],
        },
        { path: 'meetings', component: TargetStub },
        { path: 'meetings/:id', component: TargetStub },
        { path: 'voting', component: TargetStub },
        { path: 'admin/gremien/:id/members', component: TargetStub },
      ]),
      { provide: GremienApiService, useValue: api },
      { provide: AuthService, useValue: auth },
      { provide: ApiClient, useValue: {} },
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
  return { harness, api, auth, restore, settle, router, detail, frame: TestBed.inject(PageFrameService) };
}

describe('GremiumDetailComponent', () => {
  let restore: (() => void) | null = null;
  afterEach(() => {
    restore?.();
    restore = null;
    localStorage.clear();
  });

  it('shows the head with role, facts and actions, and the meetings tab', async () => {
    const s = await start('/gremien/g-1', { media: [MEDIA.wide] });
    restore = s.restore;
    const d = s.detail();
    expect(d.split()).toBe(true);
    expect(screen.getByRole('heading', { level: 2, name: 'Studierendenparlament' })).toBeTruthy();
    expect(d.roleLabel()).toBe('Mitglied');
    expect(screen.getByText('Mitglied', { selector: 'strong' })).toBeTruthy();
    expect(d.facts()).toEqual([
      '31 Mitglieder',
      'Beschlussfähig ab 50 %',
      'Protokolle öffentlich',
      'Stimmübertragung erlaubt',
    ]);
    expect(d.tab()).toBe('sitzungen');
    expect(s.api.meetings).toHaveBeenCalledWith('g-1');
    expect(s.api.members).not.toHaveBeenCalled();
    expect(d.meetingCount()).toBe(1);
    expect(d.tabs().map((t) => t.count)).toEqual([1, 31, undefined, undefined]);
    expect(s.frame.crumbLabel()).toEqual({ url: '/gremien/g-1', label: 'Studierendenparlament' });
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
    const s = await start('/gremien/g-1');
    restore = s.restore;
    const d = s.detail();
    d.selectTab('mitglieder');
    await s.settle();
    expect(s.router.url).toBe('/gremien/g-1?tab=mitglieder');
    expect(s.api.members).toHaveBeenCalledWith('g-1', false);
    d.selectTab('anwesenheit');
    await s.settle();
    expect([...d.visited()]).toEqual(['sitzungen', 'mitglieder', 'anwesenheit']);
    expect(s.api.attendance).toHaveBeenCalled();
    d.selectTab('beschluesse');
    await s.settle();
    expect(s.api.decisions).toHaveBeenCalled();
    d.selectTab('sitzungen');
    await s.settle();
    expect(s.router.url).toBe('/gremien/g-1');
    expect(d.tab()).toBe('sitzungen');
  });

  it('opens an unknown tab of the URL as the meetings', async () => {
    const s = await start('/gremien/g-1?tab=uebersicht');
    restore = s.restore;
    expect(s.detail().tab()).toBe('sitzungen');
  });

  it('starts afresh for another gremium', async () => {
    const s = await start('/gremien/g-1?tab=mitglieder');
    restore = s.restore;
    const d = s.detail();
    expect([...d.visited()]).toEqual(['mitglieder']);
    await s.router.navigateByUrl('/gremien/g-2');
    await s.settle();
    expect([...d.visited()]).toEqual(['sitzungen']);
    expect(d.roleLabel()).toBe('');
    expect(d.facts()).toEqual(['1 Mitglied']);
    expect(screen.getByRole('button', { name: 'Zur laufenden Sitzung' })).toBeTruthy();
  });

  it('plans a meeting with session.manage and opens the administration with admin.gremien', async () => {
    const s = await start('/gremien/g-1', { plan: true, admin: true });
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
    expect(s.router.url).toBe('/admin/gremien/g-1/members');
  });

  it('runs every entry of the ⋮ menu', async () => {
    const s = await start('/gremien/g-1');
    restore = s.restore;
    const d = s.detail();
    const abo = { open: jest.fn() } as unknown as CalendarSubscribeComponent;
    d.onMenu({ id: 'calendar', label: '' }, abo);
    expect(abo.open).toHaveBeenCalled();

    d.onMenu({ id: 'votes', label: '' }, abo);
    await s.settle();
    expect(s.router.url).toBe('/voting?gremium=g-1');

    await s.router.navigateByUrl('/gremien/g-1');
    await s.settle();
    s.detail().onMenu({ id: 'admin', label: '' }, abo);
    await s.settle();
    expect(s.router.url).toBe('/admin/gremien/g-1/members');

    await s.router.navigateByUrl('/gremien/g-1');
    await s.settle();
    s.detail().onMenu({ id: 'next', label: '' }, abo);
    await s.settle();
    expect(s.router.url).toBe('/meetings/m-9');

    await s.router.navigateByUrl('/gremien/g-1');
    await s.settle();
    s.detail().onMenu({ id: 'meetings', label: '' }, abo);
    await s.settle();
    expect(s.router.url).toBe('/meetings');
  });

  it('moves the actions into the ⋮ menu on a phone', async () => {
    const s = await start('/gremien/g-1', { media: [MEDIA.phone], plan: true, admin: true });
    restore = s.restore;
    const d = s.detail();
    expect(screen.queryByRole('button', { name: 'Sitzungen abonnieren' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Gremium verwalten' })).toBeNull();
    expect(d.showNext()).toBe(false);
    expect(d.menu()[0].items.map((i) => i.id)).toEqual(['calendar', 'next', 'admin', 'meetings', 'votes']);
  });

  it('keeps "Nächste Sitzung" as the one action on a phone without planning', async () => {
    const s = await start('/gremien/g-2', { media: [MEDIA.phone] });
    restore = s.restore;
    const d = s.detail();
    expect(d.showNext()).toBe(true);
    expect(d.menu()[0].items.map((i) => i.id)).toEqual(['calendar', 'meetings', 'votes']);
  });

  it('says when the gremium is not there, or the list failed', async () => {
    const s = await start('/gremien/g-x');
    restore = s.restore;
    expect(screen.getByText('Gremium nicht gefunden')).toBeTruthy();
    s.detail().openNext();
    s.detail().openAdmin();
    await s.settle();
    expect(s.router.url).toBe('/admin/gremien/g-x/members');
  });

  it('shows the list error in the sheet', async () => {
    const s = await start('/gremien/g-1', { overview: jest.fn(() => throwError(() => new Error('x'))) });
    restore = s.restore;
    expect(screen.getAllByText('Die Gremien konnten nicht geladen werden.').length).toBeGreaterThan(0);
  });

  it('shows a skeleton while the list loads', async () => {
    const s = await start('/gremien/g-1', { overview: jest.fn(() => NEVER) });
    restore = s.restore;
    expect(s.harness.routeNativeElement?.querySelector('.gd--busy')).toBeTruthy();
  });
});
