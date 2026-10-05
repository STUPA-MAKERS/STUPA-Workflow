import { Component } from '@angular/core';
import { of } from 'rxjs';
import { Router, provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
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

/** Let `matchMedia` report a wide viewport (or not). jsdom has none of its own. */
function matchWide(wide: boolean, xl = false): void {
  window.matchMedia = ((query: string) => ({
    matches:
      (wide && query.includes('min-width: 1200px')) || (xl && query.includes('min-width: 1440px')),
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

async function setup(perms: string[], url = '/admin/users', wide = true, xl = false) {
  matchWide(wide, xl);
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
            { path: 'cost-centres', component: StubPageComponent, data: { adminNav: 'xl' } },
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

  it('leaves out the navigation beside an adminNav: xl page below 1440 px', async () => {
    const view = await setup(ALL, '/admin/cost-centres', true, false);
    expect(screen.queryByRole('navigation')).toBeNull();
    expect(view.container.querySelector('.af')).not.toHaveClass('af--split');
  });

  it('shows the navigation beside an adminNav: xl page from 1440 px', async () => {
    const view = await setup(ALL, '/admin/cost-centres', true, true);
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
async function setupAccount(perms: string[], url = '/account', wide = true) {
  matchWide(wide);
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

  it('below wide: an account page fills the width and "Zur Liste" leads back', async () => {
    const view = await setupAccount(['mcp.use'], '/account/grants', false);
    expect(screen.queryByRole('navigation')).toBeNull();
    expect(view.container.querySelector('.af__page')).not.toHaveClass('af__hidden');
    const back = screen.getByRole('link', { name: 'Zur Liste' });
    expect(back).toHaveAttribute('href', '/account');
    await userEvent.click(back);
    await view.fixture.whenStable();
    view.fixture.detectChanges();
    expect(screen.getByRole('navigation', { name: 'Kontobereiche' })).toBeInTheDocument();
  });
});
