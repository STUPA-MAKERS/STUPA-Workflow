import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { screen } from '@testing-library/angular';
import { of, throwError } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import { GremienApiService, type GremiumOverview } from '@core/api/gremien.service';
import { AuthService } from '@core/auth/auth.service';
import { MEDIA } from '@stupa-makers/ui-kit';
import { runAxe } from '../../../../testing/a11y';
import { gremienApiMock, gremium } from '../../../../testing/gremien-fixtures';
import { matchMediaQueries } from '../../../../testing/meeting-fixtures';
import { PageFrameService } from '../../../layout/page-frame.service';
import type { CalendarSubscribeComponent } from '../../meetings/calendar-subscribe/calendar-subscribe.component';
import { GremienNoneComponent } from '../gremien-none/gremien-none.component';
import { GREMIUM_VIEW_ALL, GremienComponent } from './gremien.component';

@Component({ standalone: true, template: '<p>Detail</p>' })
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
    logoUrl: '/api/gremien/g-2/logo',
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
  opts: { items?: GremiumOverview[]; viewAll?: boolean; media?: string[]; overview?: jest.Mock } = {},
) {
  localStorage.setItem('ap.locale', 'de');
  const restore = matchMediaQueries(...(opts.media ?? []));
  const api = gremienApiMock({ overview: opts.overview ?? jest.fn(() => of(opts.items ?? ITEMS)) });
  const auth = { can: jest.fn((p: string) => opts.viewAll === true && p === GREMIUM_VIEW_ALL) };
  TestBed.configureTestingModule({
    providers: [
      provideRouter([
        {
          path: 'gremien',
          component: GremienComponent,
          children: [
            { path: '', component: GremienNoneComponent },
            { path: ':id', component: DetailStub },
          ],
        },
      ]),
      { provide: GremienApiService, useValue: api },
      { provide: AuthService, useValue: auth },
      { provide: ApiClient, useValue: {} },
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
  return { harness, cmp, api, restore, settle, router: TestBed.inject(Router), frame: TestBed.inject(PageFrameService) };
}

describe('GremienComponent', () => {
  let restore: (() => void) | null = null;
  afterEach(() => {
    restore?.();
    restore = null;
    localStorage.clear();
  });

  it('opens the first own gremium by itself when the panes sit side by side', async () => {
    const s = await start('/gremien', { media: [MEDIA.wide] });
    restore = s.restore;
    expect(s.cmp.split()).toBe(true);
    expect(s.frame.fill()).toBe(true);
    expect(s.router.url).toBe('/gremien/g-1');
    expect(s.cmp.selectedId()).toBe('g-1');
    expect(screen.getByText('Detail')).toBeTruthy();
    s.harness.fixture.destroy();
    expect(s.frame.fill()).toBe(false);
  });

  it('shows the own gremien with role, members and the next meeting', async () => {
    const s = await start('/gremien');
    restore = s.restore;
    expect(s.cmp.split()).toBe(false);
    expect(s.router.url).toBe('/gremien');
    expect(s.api.overview).toHaveBeenCalledTimes(1);
    const rows = s.cmp.mine();
    expect(rows.map((r) => r.sub)).toEqual(['Mitglied · 31 Mitglieder', 'Vorstand · 1 Mitglied']);
    expect(rows[0].next).toEqual({ kind: 'date', text: 'Di, 20.10.', title: 'Nächste Sitzung: 34. Sitzung' });
    expect(rows[1].next).toEqual({ kind: 'live' });
    // Without gremium.view_all no other gremium and no chip.
    expect(s.cmp.others()).toEqual([]);
    expect(s.cmp.viewAll()).toBe(false);
    expect(screen.queryByText('Weitere Gremien')).toBeNull();
    expect(screen.getByText('Sitzung läuft')).toBeTruthy();
    const link = screen.getByRole('link', { name: /Studierendenparlament/ });
    expect(link.getAttribute('href')).toBe('/gremien/g-1');
    expect(s.cmp.searchPlaceholder()).toBe('2 Gremien durchsuchen');
    expect(await runAxe(s.harness.routeNativeElement as HTMLElement)).toHaveNoViolations();
  });

  it('shows every gremium with gremium.view_all, and only the own ones on request', async () => {
    const s = await start('/gremien', { viewAll: true });
    restore = s.restore;
    expect(s.cmp.others().map((r) => r.item.id)).toEqual(['g-3']);
    expect(s.cmp.others()[0].sub).toBe('12 Mitglieder');
    expect(s.cmp.others()[0].next).toEqual({ kind: 'none' });
    expect(screen.getByText('Weitere Gremien')).toBeTruthy();
    expect(screen.getByText('Keine Sitzung geplant')).toBeTruthy();
    expect(s.cmp.scopeText()).toBe('Anzeigen: Alle Gremien');
    expect(s.cmp.searchPlaceholder()).toBe('3 Gremien durchsuchen');
    s.cmp.setScope('mine');
    s.harness.detectChanges();
    expect(s.cmp.scopeText()).toBe('Anzeigen: Meine Gremien');
    expect(s.cmp.others()).toEqual([]);
    expect(s.cmp.searchPlaceholder()).toBe('2 Gremien durchsuchen');
    s.cmp.setScope('anything');
    expect(s.cmp.scope()).toBe('all');
  });

  it('searches the name and the slug in the browser', async () => {
    const s = await start('/gremien', { viewAll: true });
    restore = s.restore;
    s.cmp.query.set('WAHL');
    expect(s.cmp.mine().map((r) => r.item.id)).toEqual(['g-2']);
    expect(s.cmp.others()).toEqual([]);
    s.cmp.query.set('fs-inf');
    expect(s.cmp.others().map((r) => r.item.id)).toEqual(['g-3']);
    s.cmp.query.set('zzz');
    s.harness.detectChanges();
    expect(screen.getByText('Kein Gremium passt zur Suche.')).toBeTruthy();
  });

  it('says that the person is in no gremium', async () => {
    const s = await start('/gremien', { items: [], media: [MEDIA.wide] });
    restore = s.restore;
    expect(s.router.url).toBe('/gremien');
    expect(screen.getAllByText('Keine Gremien').length).toBeGreaterThan(0);
  });

  it('reports a failed read and reads again', async () => {
    const overview = jest.fn(() => throwError(() => new Error('x')));
    const s = await start('/gremien', { overview });
    restore = s.restore;
    expect(screen.getByRole('alert')).toHaveTextContent('Die Gremien konnten nicht geladen werden.');
    overview.mockReturnValue(of(ITEMS));
    screen.getByRole('button', { name: /Erneut versuchen/ }).click();
    s.harness.detectChanges();
    expect(screen.queryByRole('alert')).toBeNull();
    expect(s.cmp.mine()).toHaveLength(2);
  });

  it('follows the open gremium and closes it, keeping the query', async () => {
    const s = await start('/gremien/g-2?tab=mitglieder');
    restore = s.restore;
    expect(s.cmp.selectedId()).toBe('g-2');
    s.cmp.closeDetail();
    await s.settle();
    expect(s.router.url).toBe('/gremien?tab=mitglieder');
    expect(s.cmp.selectedId()).toBeNull();
  });

  it('puts the calendar into the ⋮ menu on a phone', async () => {
    const s = await start('/gremien', { media: [MEDIA.phone] });
    restore = s.restore;
    expect(screen.queryByRole('button', { name: 'Sitzungen abonnieren' })).toBeNull();
    expect(s.cmp.phoneMenu()[0].items.map((i) => i.id)).toEqual(['calendar']);
    const abo = { open: jest.fn() } as unknown as CalendarSubscribeComponent;
    s.cmp.onPhoneMenu({ id: 'other', label: 'x' }, abo);
    expect(abo.open).not.toHaveBeenCalled();
    s.cmp.onPhoneMenu({ id: 'calendar', label: 'x' }, abo);
    expect(abo.open).toHaveBeenCalled();
  });

  it('shows the calendar button on a wider screen', async () => {
    const s = await start('/gremien');
    restore = s.restore;
    expect(screen.getByRole('button', { name: 'Sitzungen abonnieren' })).toBeTruthy();
  });
});
