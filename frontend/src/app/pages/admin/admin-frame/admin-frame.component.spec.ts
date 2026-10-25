import { Component } from '@angular/core';
import { of } from 'rxjs';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter, withComponentInputBinding } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { render, screen } from '@testing-library/angular';
import { MEDIA } from '@stupa-makers/ui-kit';
import { drag, mediaMatching } from '../../../../testing/touch';
import userEvent from '@testing-library/user-event';
import { AuthService } from '@core/auth/auth.service';
import { AdminApiService } from '../admin-api.service';
import { PageFrameService } from '../../../layout/page-frame.service';
import { ADMIN_PAGES } from './admin-pages';
import { AdminFrameComponent } from './admin-frame.component';

@Component({ selector: 'app-stub-page', standalone: true, template: '<h1>Seite</h1>' })
class StubPageComponent {}

function fakeAuth(perms: string[]): Partial<AuthService> {
  const set = new Set(perms);
  return { can: (p: string) => set.has(p), canAny: (...p: string[]) => p.some((x) => set.has(x)) };
}

/** Every permission of an admin page. */
const ALL = [...new Set(ADMIN_PAGES.flatMap((p) => p.permissions))];

/**
 * Let `matchMedia` report a wide viewport, a phone or the width between. jsdom has none
 * of its own.
 */
function matchWide(wide: boolean, phone = false): void {
  window.matchMedia = ((query: string) => ({
    matches:
      (wide && query.includes('min-width: 1200px')) ||
      (phone && query.includes('max-width: 768px')),
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

async function setup(perms: string[], url = '/admin/users', wide = true, phone = false) {
  matchWide(wide, phone);
  const api = {
    latestAuditVerification: jest.fn(() => of(null)),
    verifyAuditChain: jest.fn(() => of({ valid: true, checked: 1, brokenAt: null, reason: null })),
    listBackups: jest.fn(() => of({ items: [], enabled: true, restoreEnabled: true, retentionCount: 14 })),
    listErasures: jest.fn(() => of([])),
  };
  const view = await render(AdminFrameComponent, {
    providers: [
      provideRouter([
        {
          path: 'admin',
          children: [
            { path: '', component: StubPageComponent, pathMatch: 'full' },
            { path: 'flow', component: StubPageComponent, data: { adminNav: false, adminPane: true } },
            { path: 'plain', component: StubPageComponent, data: { adminNav: false } },
            { path: 'cost-centres', component: StubPageComponent },
            { path: 'gremien/g1/members', component: StubPageComponent, data: { parent: ['admin', 'admin/gremien'] } },
            { path: 'users', component: StubPageComponent, data: { parent: ['admin'] } },
            {
              path: 'forms/:id',
              component: StubPageComponent,
              data: { parent: ['admin', 'admin/forms'] },
            },
            { path: '**', component: StubPageComponent },
          ],
        },
      ]),
      { provide: AuthService, useValue: fakeAuth(perms) },
      { provide: AdminApiService, useValue: api },
    ],
  });
  await view.fixture.ngZone!.run(() => view.fixture.debugElement.injector.get(Router).navigateByUrl(url));
  view.fixture.detectChanges();
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  return view;
}

function navLinks(): HTMLAnchorElement[] {
  const nav = screen.getByRole('navigation', { name: 'Verwaltungsbereiche' });
  return [...nav.querySelectorAll<HTMLAnchorElement>('a.af__item')];
}

describe('AdminFrameComponent swipe back on a phone', () => {
  afterEach(() => {
    jest.useRealTimers();
    jest.restoreAllMocks();
  });

  async function swipe(view: Awaited<ReturnType<typeof setup>>): Promise<Router> {
    const router = view.fixture.debugElement.injector.get(Router);
    jest.spyOn(window, 'scrollTo').mockImplementation(() => undefined);
    const nav = jest.spyOn(router, 'navigateByUrl').mockResolvedValue(true);
    mediaMatching([MEDIA.phone, MEDIA.coarse]);
    jest.useFakeTimers();
    const page = view.container.querySelector('.af__page') as HTMLElement;
    drag(page, { x: 4, y: 300 }, [{ x: 30, y: 300 }, { x: 300, y: 300 }], { release: false });
    view.fixture.detectChanges();
    expect(page).toHaveClass('af__page--swiping');
    drag(page, { x: 0, y: 0 }, []);
    jest.advanceTimersByTime(280);
    expect(nav).toHaveBeenCalledTimes(1);
    return router;
  }

  it('leads an admin page back to its nearest breadcrumb', async () => {
    const view = await setup(ALL, '/admin/gremien/g1/members', false);
    const router = await swipe(view);
    expect(router.navigateByUrl).toHaveBeenCalledWith('/admin/gremien');
  });

  it('leads an admin page without a parent to the home page', async () => {
    const view = await setup(ALL, '/admin/backups', false);
    const router = await swipe(view);
    expect(router.navigateByUrl).toHaveBeenCalledWith('/admin');
  });

  it('puts the sheet back in place after the navigation', async () => {
    const view = await setup(ALL, '/admin/users', false);
    const router = await swipe(view);
    expect(router.navigateByUrl).toHaveBeenCalledWith('/admin');
    jest.mocked(router.navigateByUrl).mockRestore();
    jest.useRealTimers();
    await view.fixture.ngZone!.run(() => router.navigateByUrl('/admin/backups'));
    view.fixture.detectChanges();
    const page = view.container.querySelector('.af__page') as HTMLElement;
    expect(page).not.toHaveClass('af__page--swiping');
    expect(page.style.left).toBe('');
  });

  it.each([
    ['/admin', false],
    ['/admin/users', true],
    ['/admin/flow', false],
  ] as const)('has no swipe on %s (wide: %p)', async (url, wide) => {
    const view = await setup(ALL, url, wide);
    mediaMatching([MEDIA.phone, MEDIA.coarse]);
    const page = view.container.querySelector('.af__page') as HTMLElement;
    drag(page, { x: 4, y: 300 }, [{ x: 30, y: 300 }, { x: 300, y: 300 }], { release: false });
    view.fixture.detectChanges();
    expect(page).not.toHaveClass('af__page--swiping');
  });
});

describe('AdminFrameComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('lists every admin page in its group for a principal with all rights', async () => {
    await setup(ALL);
    const hrefs = navLinks().map((a) => a.getAttribute('href'));
    expect(hrefs).toEqual(ADMIN_PAGES.map((p) => `/admin/${p.link}`));
    for (const group of [
      'Personen und Rechte',
      'Gremien',
      'Anträge',
      'Finanzen',
      'Erscheinungsbild',
      'Kommunikation',
      'Sicherheit und Daten',
    ]) {
      expect(screen.getByRole('heading', { name: group, level: 2 })).toBeInTheDocument();
    }
    // The cost centres sit inside the frame.
    expect(hrefs).toContain('/admin/cost-centres');
  });

  it('shows only the pages of the held permissions, and leaves out empty groups', async () => {
    await setup(['form.configure', 'admin.types']);
    expect(navLinks().map((a) => a.getAttribute('href'))).toEqual(['/admin/forms', '/admin/flow']);
    expect(screen.queryByRole('heading', { name: 'Finanzen' })).toBeNull();
  });

  it('marks the active page', async () => {
    await setup(ALL, '/admin/roles');
    const active = navLinks().filter((a) => a.getAttribute('aria-current') === 'page');
    expect(active.map((a) => a.getAttribute('href'))).toEqual(['/admin/roles']);
    expect(active[0]).toHaveClass('af__item--on');
  });

  it('scrolls the column, not the window, so that the active entry shows', async () => {
    // jsdom has no layout: every entry sits 40 px under the one before it, the column
    // shows 200 px and starts at 0.
    const rect = jest
      .spyOn(HTMLElement.prototype, 'getBoundingClientRect')
      .mockImplementation(function (this: HTMLElement) {
        const links = [...document.querySelectorAll('a.af__item')];
        const i = links.indexOf(this);
        const top = i < 0 ? 0 : i * 40;
        const height = i < 0 ? 200 : 40;
        return { top, bottom: top + height, height, left: 0, right: 0, width: 0, x: 0, y: top } as DOMRect;
      });
    const scrollWindow = jest.spyOn(window, 'scrollTo').mockImplementation(() => undefined);
    try {
      const view = await setup(ALL, '/admin/users');
      const body = view.container.querySelector<HTMLElement>('.af__navBody')!;
      Object.defineProperty(body, 'clientHeight', { configurable: true, value: 200 });
      // The first entry is in view: the column stays.
      expect(body.scrollTop).toBe(0);
      await view.fixture.ngZone!.run(() =>
        view.fixture.debugElement.injector.get(Router).navigateByUrl('/admin/backups'),
      );
      view.fixture.detectChanges();
      await view.fixture.whenStable();
      const i = navLinks().findIndex((a) => a.getAttribute('href') === '/admin/backups');
      expect(i).toBeGreaterThan(5);
      // The entry is out of view: the column puts it in the middle.
      expect(body.scrollTop).toBe(i * 40 - 80);
      expect(scrollWindow).not.toHaveBeenCalled();
    } finally {
      rect.mockRestore();
      scrollWindow.mockRestore();
    }
  });

  it('filters the entries by title and description, and says when nothing matches', async () => {
    await setup(ALL);
    const search = screen.getByRole('searchbox', { name: 'Einstellungen durchsuchen' });
    await userEvent.type(search, 'löschanträge');
    expect(navLinks().map((a) => a.getAttribute('href'))).toEqual(['/admin/privacy']);
    await userEvent.clear(search);
    await userEvent.type(search, 'webhook');
    expect(navLinks().map((a) => a.getAttribute('href'))).toEqual(['/admin/webhooks']);
    await userEvent.clear(search);
    await userEvent.type(search, 'xyz');
    expect(navLinks()).toHaveLength(0);
    expect(screen.getByText('Keine Einstellung gefunden.')).toBeInTheDocument();
  });

  it('is the overview on the home page: h1, Zustand and a line per entry', async () => {
    // One column: the navigation is the page, with a description per entry.
    const view = await setup(ALL, '/admin', false);
    expect(screen.getByRole('heading', { name: 'Verwaltung', level: 1 })).toBeInTheDocument();
    expect(view.container.querySelector('app-admin-health')).not.toBeNull();
    expect(screen.getByText('Benutzer und Rollenzuweisungen')).toBeInTheDocument();
    expect(view.container.querySelector('.af__page')).toHaveClass('af__hidden');
    expect(view.container.querySelector('.af')).toHaveClass('af--home');
    // The search hides the tiles: they are no entries. They stay in the DOM, so a
    // cleared search does not load them again.
    const api = view.fixture.debugElement.injector.get(AdminApiService) as unknown as {
      listBackups: jest.Mock;
    };
    expect(api.listBackups).toHaveBeenCalledTimes(1);
    await userEvent.type(screen.getByRole('searchbox'), 'audit');
    expect(view.container.querySelector('app-admin-health')).toHaveClass('af__hidden');
    await userEvent.clear(screen.getByRole('searchbox'));
    expect(view.container.querySelector('app-admin-health')).not.toHaveClass('af__hidden');
    expect(api.listBackups).toHaveBeenCalledTimes(1);
  });

  it('keeps the navigation beside the cost centres at every wide size', async () => {
    const view = await setup(ALL, '/admin/cost-centres', true);
    expect(screen.getByRole('navigation', { name: 'Verwaltungsbereiche' })).toBeInTheDocument();
    expect(view.container.querySelector('.af')).toHaveClass('af--split');
  });

  it('leaves out the navigation for a page with adminNav: false, and keeps the crumb', async () => {
    const view = await setup(ALL, '/admin/flow');
    expect(screen.queryByRole('navigation')).toBeNull();
    expect(view.container.querySelector('.af')).not.toHaveClass('af--split');
    // Without the column the breadcrumb "Verwaltung" is the way back.
    expect(view.fixture.debugElement.injector.get(PageFrameService).crumbRoot()).toBeNull();
    // Back on a normal page the column returns.
    await view.fixture.ngZone!.run(() =>
      view.fixture.debugElement.injector.get(Router).navigateByUrl('/admin/users'),
    );
    view.fixture.detectChanges();
    expect(screen.getByRole('navigation', { name: 'Verwaltungsbereiche' })).toBeInTheDocument();
    expect(view.container.querySelector('.af')).toHaveClass('af--split');
  });

  it('passes the free height to a full-width page with adminPane, only on a wide viewport', async () => {
    const view = await setup(ALL, '/admin/flow');
    const frame = view.container.querySelector('.af');
    const host = view.fixture.nativeElement as HTMLElement;
    const pageFrame = view.fixture.debugElement.injector.get(PageFrameService);
    expect(frame).toHaveClass('af--pane');
    expect(host).toHaveClass('pane-page');
    expect(pageFrame.fill()).toBe(true);
    // A full-width page without the flag keeps the page scroll.
    await view.fixture.ngZone!.run(() =>
      view.fixture.debugElement.injector.get(Router).navigateByUrl('/admin/plain'),
    );
    view.fixture.detectChanges();
    expect(frame).not.toHaveClass('af--pane');
    expect(host).not.toHaveClass('pane-page');
    expect(pageFrame.fill()).toBe(false);
  });

  it('keeps the page scroll of an adminPane page below wide', async () => {
    const view = await setup(ALL, '/admin/flow', false);
    expect(view.container.querySelector('.af')).not.toHaveClass('af--pane');
    expect(view.fixture.nativeElement as HTMLElement).not.toHaveClass('pane-page');
  });

  it('beside an admin page the title is no heading and the entries have no description', async () => {
    const view = await setup(ALL, '/admin/users');
    expect(screen.queryByRole('heading', { name: 'Verwaltung' })).toBeNull();
    expect(screen.queryByText('Benutzer und Rollenzuweisungen')).toBeNull();
    expect(view.container.querySelector('.af')).toHaveClass('af--split');
  });

  it('keeps "Zustand" in the column beside an admin page, in the same order, and marks the open tile', async () => {
    const view = await setup(ALL, '/admin/audit');
    const nav = screen.getByRole('navigation', { name: 'Verwaltungsbereiche' });
    const health = nav.querySelector('app-admin-health');
    expect(health).not.toBeNull();
    // The tiles lead the column, before the first group of entries.
    expect(nav.querySelector('.af__navBody')?.firstElementChild).toBe(health);
    const tiles = [...health!.querySelectorAll<HTMLAnchorElement>('a.ah__tile')];
    expect(tiles.map((a) => a.getAttribute('href'))).toEqual([
      '/admin/audit',
      '/admin/backups',
      '/admin/privacy',
    ]);
    await view.fixture.whenStable();
    view.fixture.detectChanges();
    expect(tiles[0]).toHaveClass('ah__tile--on');
    expect(tiles[0]).toHaveAttribute('aria-current', 'page');
    expect(tiles[1]).not.toHaveClass('ah__tile--on');
  });

  it('beside an admin page is a pane page: it fills the window, and clears that when it goes', async () => {
    const view = await setup(ALL, '/admin/users');
    const frame = view.fixture.debugElement.injector.get(PageFrameService);
    expect(frame.fill()).toBe(true);
    // The sheet is the window: its body is the scroll container of the page.
    expect(view.container.querySelector('.af__page > .af__pageBody')).not.toBeNull();
    view.fixture.destroy();
    expect(frame.fill()).toBe(false);
  });

  it('does not fill the window in one column', async () => {
    const view = await setup(ALL, '/admin/users', false);
    expect(view.fixture.debugElement.injector.get(PageFrameService).fill()).toBe(false);
  });

  it('starts a new admin page at the top of the sheet', async () => {
    const view = await setup(ALL, '/admin/users');
    const body = view.container.querySelector<HTMLElement>('.af__pageBody')!;
    // jsdom does no layout: a plain property stands in for the scroll offset.
    Object.defineProperty(body, 'scrollTop', { value: 300, writable: true, configurable: true });
    await view.fixture.ngZone!.run(() =>
      view.fixture.debugElement.injector.get(Router).navigateByUrl('/admin/audit'),
    );
    view.fixture.detectChanges();
    await view.fixture.whenStable();
    expect(body.scrollTop).toBe(0);
  });

  it('hides the navigation below wide on an admin page', async () => {
    const page = await setup(ALL, '/admin/users', false);
    expect(screen.queryByRole('navigation')).toBeNull();
    expect(page.container.querySelector('.af')).not.toHaveClass('af--split');
  });

  it('on a phone: an admin page sits below the bar of a one-view page', async () => {
    const view = await setup(ALL, '/admin/users', false, true);
    expect(view.container.querySelector('app-list-detail-bar')).not.toBeNull();
    expect(view.container.querySelector('.af__pageBody')).toHaveClass('ld-under-bar');
    await userEvent.click(screen.getByRole('button', { name: 'Zur Liste' }));
    await view.fixture.whenStable();
    expect(view.fixture.debugElement.injector.get(Router).url).toBe('/admin');
  });

  it('on a phone: the back arrow leads to the parent page of the route', async () => {
    const view = await setup(ALL, '/admin/forms/f1', false, true);
    await userEvent.click(screen.getByRole('button', { name: 'Zur Liste' }));
    await view.fixture.whenStable();
    expect(view.fixture.debugElement.injector.get(Router).url).toBe('/admin/forms');
  });

  it('has no bar on the home page of a phone', async () => {
    const home = await setup(ALL, '/admin', false, true);
    expect(home.container.querySelector('app-list-detail-bar')).toBeNull();
  });

  it.each([
    ['/admin/users'],
    ['/admin/flow'],
  ] as const)('has no bar on %s between phone and wide: the header keeps its crumb', async (url) => {
    const view = await setup(ALL, url, false);
    expect(view.container.querySelector('app-list-detail-bar')).toBeNull();
    expect(view.container.querySelector('.af__pageBody')).not.toHaveClass('ld-under-bar');
  });

  it('has no bar on a wide full-width editor: the header keeps its crumb and title', async () => {
    const wide = await setup(ALL, '/admin/flow');
    expect(wide.container.querySelector('app-list-detail-bar')).toBeNull();
    expect(wide.container.querySelector('.af__pageBody')).not.toHaveClass('ld-under-bar');
  });

  it('has no bar beside the navigation', async () => {
    const wide = await setup(ALL, '/admin/users');
    expect(wide.container.querySelector('app-list-detail-bar')).toBeNull();
  });

  it('keeps the navigation above the page on the home page below wide', async () => {
    const home = await setup(ALL, '/admin', false);
    expect(screen.getByRole('navigation', { name: 'Verwaltungsbereiche' })).toBeInTheDocument();
    expect(home.container.querySelector('.af')).not.toHaveClass('af--split');
  });

  it('keeps the column and the sheet of every admin page on the wide home page', async () => {
    // Any admin right gives the same split: the empty sheet stands beside the column,
    // which shows the titles only, as beside an admin page.
    const view = await setup(['backup.manage'], '/admin');
    expect(view.container.querySelector('.af')).toHaveClass('af--split');
    expect(view.container.querySelector('.af__page')).not.toHaveClass('af__hidden');
    expect(view.container.querySelector('.af__itemDesc')).toBeNull();
  });

  it('tells the breadcrumbs to leave out "Verwaltung" while the column shows, and clears it', async () => {
    const view = await setup(ALL, '/admin/users');
    const frame = view.fixture.debugElement.injector.get(PageFrameService);
    expect(frame.crumbRoot()).toBe('admin');
    view.fixture.destroy();
    expect(frame.crumbRoot()).toBeNull();
  });

  it('does not set the crumb root below wide', async () => {
    const view = await setup(ALL, '/admin/users', false);
    expect(view.fixture.debugElement.injector.get(PageFrameService).crumbRoot()).toBeNull();
  });

  it('follows a navigation between home and an admin page', async () => {
    const view = await setup(ALL, '/admin');
    expect(view.container.querySelector('.af')).toHaveClass('af--home');
    await view.fixture.ngZone!.run(() =>
      view.fixture.debugElement.injector.get(Router).navigateByUrl('/admin/audit?x=1'),
    );
    view.fixture.detectChanges();
    expect(view.container.querySelector('.af')).not.toHaveClass('af--home');
  });
});

/** The frame in account mode, as the route `account` sets it (`data: { frame: 'account' }`). */
async function setupAccount(perms: string[], url = '/account', wide = true, phone = false) {
  matchWide(wide, phone);
  const api = {
    latestAuditVerification: jest.fn(() => of(null)),
    verifyAuditChain: jest.fn(),
    listBackups: jest.fn(() => of({ items: [] })),
    listErasures: jest.fn(() => of([])),
  };
  const view = await render(AdminFrameComponent, {
    componentInputs: { frame: 'account' },
    providers: [
      provideRouter([
        {
          path: 'account',
          children: [
            { path: '', component: StubPageComponent, pathMatch: 'full' },
            { path: '**', component: StubPageComponent },
          ],
        },
      ]),
      { provide: AuthService, useValue: fakeAuth(perms) },
      { provide: AdminApiService, useValue: api },
    ],
  });
  await view.fixture.ngZone!.run(() => view.fixture.debugElement.injector.get(Router).navigateByUrl(url));
  view.fixture.detectChanges();
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  return { ...view, api };
}

function accountLinks(): string[] {
  const nav = screen.getByRole('navigation', { name: 'Kontobereiche' });
  return [...nav.querySelectorAll<HTMLAnchorElement>('a.af__item')].map(
    (a) => a.getAttribute('href') ?? '',
  );
}

describe('AdminFrameComponent in account mode', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('lists the account pages under "Konto", without search, tiles and group heading', async () => {
    const view = await setupAccount(['mcp.use']);
    expect(screen.getByRole('heading', { name: 'Konto', level: 1 })).toBeInTheDocument();
    expect(accountLinks()).toEqual(['/account/notifications', '/account/grants']);
    expect(screen.queryByRole('searchbox')).toBeNull();
    expect(view.container.querySelector('app-admin-health')).toBeNull();
    expect(view.api.listBackups).not.toHaveBeenCalled();
    expect(screen.queryByRole('heading', { level: 2 })).toBeNull();
    // Beside the sheet the entries keep one line, the same as beside an account page.
    expect(screen.queryByText('E-Mails je Anlass ein- und ausschalten')).toBeNull();
    expect(view.container.querySelector('.af')).toHaveClass('af--account');
  });

  it('falls back to the admin frame for an unknown mode', async () => {
    matchWide(true);
    await render(AdminFrameComponent, {
      componentInputs: { frame: 'other' },
      providers: [
        provideRouter([{ path: '**', component: StubPageComponent }]),
        { provide: AuthService, useValue: fakeAuth(['admin.users']) },
        {
          provide: AdminApiService,
          useValue: { latestAuditVerification: jest.fn(() => of(null)), verifyAuditChain: jest.fn(), listBackups: jest.fn(), listErasures: jest.fn() },
        },
      ],
    });
    expect(screen.getByRole('navigation', { name: 'Verwaltungsbereiche' })).toBeInTheDocument();
  });

  it('leads an account page back to the account navigation on a swipe', async () => {
    const view = await setupAccount(['mcp.use'], '/account/notifications', false);
    const router = view.fixture.debugElement.injector.get(Router);
    jest.spyOn(window, 'scrollTo').mockImplementation(() => undefined);
    const nav = jest.spyOn(router, 'navigateByUrl').mockResolvedValue(true);
    mediaMatching([MEDIA.phone, MEDIA.coarse]);
    jest.useFakeTimers();
    const page = view.container.querySelector('.af__page') as HTMLElement;
    drag(page, { x: 4, y: 300 }, [{ x: 30, y: 300 }, { x: 300, y: 300 }]);
    jest.advanceTimersByTime(280);
    jest.useRealTimers();
    expect(nav).toHaveBeenCalledWith('/account');
    jest.restoreAllMocks();
  });

  it('shows "API-Zugang" only with mcp.use, like the account menu', async () => {
    await setupAccount([]);
    expect(accountLinks()).toEqual(['/account/notifications']);
  });

  it('wide: the home page is the navigation beside the empty sheet', async () => {
    const view = await setupAccount(['mcp.use']);
    expect(view.container.querySelector('.af')).toHaveClass('af--split');
    expect(view.container.querySelector('.af__page')).not.toHaveClass('af__hidden');
    expect(view.fixture.debugElement.injector.get(PageFrameService).fill()).toBe(true);
  });

  it('wide: an account page sits beside the navigation, with no "Zur Liste"', async () => {
    const view = await setupAccount(['mcp.use'], '/account/notifications');
    expect(view.container.querySelector('.af')).toHaveClass('af--split');
    expect(screen.getByRole('link', { name: 'Benachrichtigungen' })).toHaveAttribute(
      'aria-current',
      'page',
    );
    expect(screen.queryByRole('link', { name: 'Zur Liste' })).toBeNull();
    expect(view.fixture.debugElement.injector.get(PageFrameService).crumbRoot()).toBe('account');
  });

  it('below wide: the home page is the navigation alone, with a line per entry', async () => {
    const view = await setupAccount(['mcp.use'], '/account', false);
    expect(screen.getByRole('navigation', { name: 'Kontobereiche' })).toBeInTheDocument();
    expect(view.container.querySelector('.af__page')).toHaveClass('af__hidden');
    expect(screen.getByText('E-Mails je Anlass ein- und ausschalten')).toBeInTheDocument();
    expect(screen.getByText('MCP-Server und Zugriffe von Agenten')).toBeInTheDocument();
  });

  it('on a phone: an account page fills the width and the back arrow of the bar leads back', async () => {
    const view = await setupAccount(['mcp.use'], '/account/grants', false, true);
    expect(screen.queryByRole('navigation')).toBeNull();
    expect(view.container.querySelector('.af__page')).not.toHaveClass('af__hidden');
    const back = screen.getByRole('button', { name: 'Zur Liste' });
    await userEvent.click(back);
    await view.fixture.whenStable();
    view.fixture.detectChanges();
    expect(screen.getByRole('navigation', { name: 'Kontobereiche' })).toBeInTheDocument();
  });
});

describe('AdminFrameComponent mode from the route', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('keeps the admin mode on /admin?frame=account: the route data wins', async () => {
    matchWide(true);
    TestBed.configureTestingModule({
      providers: [
        provideRouter(
          [
            {
              path: 'admin',
              component: AdminFrameComponent,
              data: { frame: 'admin' },
              children: [{ path: '**', component: StubPageComponent }],
            },
          ],
          withComponentInputBinding(),
        ),
        { provide: AuthService, useValue: fakeAuth(['admin.users']) },
        {
          provide: AdminApiService,
          useValue: {
            latestAuditVerification: jest.fn(() => of(null)),
            verifyAuditChain: jest.fn(),
            listBackups: jest.fn(() => of({ items: [] })),
            listErasures: jest.fn(() => of([])),
          },
        },
      ],
    });
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/admin?frame=account');
    harness.detectChanges();
    expect(screen.getByRole('navigation', { name: 'Verwaltungsbereiche' })).toBeInTheDocument();
    expect(screen.queryByRole('navigation', { name: 'Kontobereiche' })).toBeNull();
  });
});
