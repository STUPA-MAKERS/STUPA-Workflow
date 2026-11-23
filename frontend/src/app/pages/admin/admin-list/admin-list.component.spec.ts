import { ChangeDetectionStrategy, Component } from '@angular/core';
import { of } from 'rxjs';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter, withComponentInputBinding } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { PageFrame } from '@stupa-makers/ui-kit';
import { AuthService } from '@core/auth/auth.service';
import { AdminApiService } from '../admin-api.service';
import { PageFrameService } from '../../../layout/page-frame.service';
import { ADMIN_PAGES } from './admin-pages';
import { AdminListComponent } from './admin-list.component';

@Component({
  changeDetection: ChangeDetectionStrategy.Eager,
  selector: 'app-stub-page',
  standalone: true,
  template: '<h1>Seite</h1>',
})
class StubPageComponent {}

function fakeAuth(perms: string[]): Partial<AuthService> {
  const set = new Set(perms);
  return { can: (p: string) => set.has(p), canAny: (...p: string[]) => p.some((x) => set.has(x)) };
}

/** Every permission of an admin page. */
const ALL = [...new Set(ADMIN_PAGES.flatMap((p) => p.permissions))];

/**
 * Let `matchMedia` report a wide viewport, a phone or the width between. jsdom has none
 * of its own, and it measures every element as 0 wide, which `app-list-detail` reads as
 * "not laid out yet".
 */
function matchWide(wide: boolean, phone = false): void {
  window.matchMedia = ((query: string) => ({
    matches:
      (wide && query.includes('min-width: 1200px')) ||
      (phone && query.includes('max-width: 767.98px')),
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

function fakeApi() {
  return {
    latestAuditVerification: jest.fn(() => of(null)),
    verifyAuditChain: jest.fn(() => of({ valid: true, checked: 1, brokenAt: null, reason: null })),
    listBackups: jest.fn(() => of({ items: [], enabled: true, restoreEnabled: true, retentionCount: 14 })),
    listErasures: jest.fn(() => of([])),
  };
}

async function setup(
  perms: string[],
  url = '/admin/users',
  wide = true,
  frame: 'admin' | 'account' = 'admin',
) {
  matchWide(wide);
  const api = fakeApi();
  const view = await render(AdminListComponent, {
    componentInputs: { frame },
    providers: [
      provideRouter([
        {
          path: 'admin',
          children: [
            { path: '', component: StubPageComponent, pathMatch: 'full' },
            {
              path: 'committees/g1/members',
              component: StubPageComponent,
              data: { parent: ['admin', 'admin/committees'] },
            },
            { path: '**', component: StubPageComponent },
          ],
        },
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

/** The links of the list, in order. */
function links(container: Element): string[] {
  return [...container.querySelectorAll<HTMLAnchorElement>('app-list-item a.li__title')].map(
    (a) => a.getAttribute('href') ?? '',
  );
}

describe('AdminListComponent (spec 001480, 001481)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('is an ordinary list/detail page: the list in the list slot, the page in the detail', async () => {
    const view = await setup(ALL);
    const layout = view.container.querySelector('app-list-detail')!;
    expect(layout.querySelector('.ld__list nav[aria-label="Verwaltungsbereiche"]')).not.toBeNull();
    expect(layout.querySelector('.ld__detail router-outlet')).not.toBeNull();
  });

  it('lists every admin page in its group for a principal with all rights', async () => {
    const view = await setup(ALL);
    expect(links(view.container)).toEqual(ADMIN_PAGES.map((p) => `/admin/${p.link}`));
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
  });

  it('gives each row the icon and the description as its second line', async () => {
    const view = await setup(ALL);
    const rows = view.container.querySelectorAll('app-list-item');
    expect(rows).toHaveLength(ADMIN_PAGES.length);
    expect(rows[0].querySelector('[lead]')).not.toBeNull();
    expect(screen.getByText('Benutzer und Rollenzuweisungen')).toBeInTheDocument();
  });

  /** Spec 000758: an admin page of a feature that is off has no entry. */
  it('leaves out the admin pages of a feature that is off', async () => {
    localStorage.setItem('ap.features.off', JSON.stringify(['budget', 'calendar', 'meetings']));
    const view = await setup(ALL);
    localStorage.removeItem('ap.features.off');
    const hrefs = links(view.container);
    expect(hrefs).not.toContain('/admin/budgets');
    expect(hrefs).not.toContain('/admin/calendars');
    expect(hrefs).not.toContain('/admin/delegations');
    expect(hrefs).toContain('/admin/features');
  });

  it('shows only the pages of the held permissions, and leaves out empty groups', async () => {
    const view = await setup(['form.configure', 'admin.types']);
    expect(links(view.container)).toEqual(['/admin/forms', '/admin/flow']);
    expect(screen.queryByRole('heading', { name: 'Finanzen' })).toBeNull();
  });

  it('selects the open page, also on a page below it', async () => {
    const view = await setup(ALL, '/admin/committees/g1/members');
    const on = [...view.container.querySelectorAll('a.li__title[aria-current="true"]')];
    expect(on.map((a) => a.getAttribute('href'))).toEqual(['/admin/committees']);
  });

  it('has no "Zustand" tiles', async () => {
    const view = await setup(ALL);
    expect(screen.queryByText('Zustand')).toBeNull();
    expect(view.api.listBackups).not.toHaveBeenCalled();
    expect(view.api.latestAuditVerification).not.toHaveBeenCalled();
  });

  it('filters the entries by title and description, and says when nothing matches', async () => {
    const view = await setup(ALL);
    const search = screen.getByRole('searchbox', { name: 'Einstellungen durchsuchen' });
    await userEvent.type(search, 'löschanträge');
    expect(links(view.container)).toEqual(['/admin/privacy']);
    await userEvent.clear(search);
    await userEvent.type(search, 'xyz');
    expect(links(view.container)).toHaveLength(0);
    expect(screen.getByText('Keine Einstellung gefunden.')).toBeInTheDocument();
  });

  it('shows the list on /admin', async () => {
    const view = await setup(ALL, '/admin', false);
    expect(screen.getByRole('heading', { name: 'Verwaltung', level: 1 })).toBeInTheDocument();
    expect(view.container.querySelector('.ld__detail')).toHaveAttribute('hidden');
    expect(view.container.querySelector('.ld__list')).not.toHaveAttribute('hidden');
  });

  it('opens the detail on every page below /admin', async () => {
    const page = await setup(ALL, '/admin/roles', false);
    expect(page.container.querySelector('.ld__list')).toHaveAttribute('hidden');
    expect(page.container.querySelector('.ld__detail')).not.toHaveAttribute('hidden');
  });

  it('leads "Zur Liste" back to the parent page of the route', async () => {
    const view = await setup(ALL, '/admin/committees/g1/members', false);
    const router = view.fixture.debugElement.injector.get(Router);
    const nav = jest.spyOn(router, 'navigateByUrl').mockResolvedValue(true);
    await userEvent.click(screen.getByRole('button', { name: 'Zur Liste' }));
    expect(nav).toHaveBeenCalledWith('/admin/committees');
  });

  it('leads "Zur Liste" of a page without a parent to /admin', async () => {
    const view = await setup(ALL, '/admin/backups', false);
    const router = view.fixture.debugElement.injector.get(Router);
    const nav = jest.spyOn(router, 'navigateByUrl').mockResolvedValue(true);
    await userEvent.click(screen.getByRole('button', { name: 'Zur Liste' }));
    expect(nav).toHaveBeenCalledWith('/admin');
  });

  it('side by side: fills the window and drops "Verwaltung" from the breadcrumbs', async () => {
    const view = await setup(ALL, '/admin/users');
    const injector = view.fixture.debugElement.injector;
    expect(view.container.querySelector('.adl')).toHaveClass('adl--split');
    expect(injector.get(PageFrame).fill()).toBe(true);
    expect(injector.get(PageFrameService).crumbRoot()).toBe('admin');
    expect(screen.queryByRole('button', { name: 'Zur Liste' })).toBeNull();
    expect(screen.queryByRole('heading', { name: 'Verwaltung', level: 1 })).toBeNull();
  });

  it('one pane at a time: no fill and no crumb root', async () => {
    const view = await setup(ALL, '/admin/users', false);
    const injector = view.fixture.debugElement.injector;
    expect(injector.get(PageFrame).fill()).toBe(false);
    expect(injector.get(PageFrameService).crumbRoot()).toBeNull();
  });
});

describe('AdminListComponent in account mode', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('lists the account pages under "Konto", without search and group heading', async () => {
    const view = await setup(['mcp.use'], '/account', true, 'account');
    expect(screen.getByRole('heading', { name: 'Konto', level: 1 })).toBeInTheDocument();
    expect(links(view.container)).toEqual(['/account/profile', '/account/notifications', '/account/grants']);
    expect(screen.queryByRole('searchbox')).toBeNull();
    expect(screen.queryByRole('heading', { level: 2 })).toBeNull();
  });

  it('shows "API-Zugang" only with mcp.use, like the account menu', async () => {
    const view = await setup([], '/account', true, 'account');
    expect(links(view.container)).toEqual(['/account/profile', '/account/notifications']);
  });

  it('names push under "Benachrichtigungen" only while the feature push is on', async () => {
    await setup([], '/account', true, 'account');
    expect(screen.getByText('Mail und Push je Anlass ein- und ausschalten')).toBeInTheDocument();
  });

  it('names only the mails while the feature push is off', async () => {
    localStorage.setItem('ap.features.off', JSON.stringify(['push']));
    await setup([], '/account', true, 'account');
    localStorage.removeItem('ap.features.off');
    expect(screen.getByText('E-Mails je Anlass ein- und ausschalten')).toBeInTheDocument();
  });

  it('leads an account page back to /account', async () => {
    const view = await setup(['mcp.use'], '/account/grants', false, 'account');
    const router = view.fixture.debugElement.injector.get(Router);
    const nav = jest.spyOn(router, 'navigateByUrl').mockResolvedValue(true);
    await userEvent.click(screen.getByRole('button', { name: 'Zur Liste' }));
    expect(nav).toHaveBeenCalledWith('/account');
  });
});

describe('AdminListComponent mode from the route', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('keeps the admin mode on /admin?frame=account: the route data wins', async () => {
    matchWide(true);
    TestBed.configureTestingModule({
      providers: [
        provideRouter(
          [
            {
              path: 'admin',
              component: AdminListComponent,
              data: { frame: 'admin' },
              children: [{ path: '**', component: StubPageComponent }],
            },
          ],
          withComponentInputBinding(),
        ),
        { provide: AuthService, useValue: fakeAuth(['admin.users']) },
        { provide: AdminApiService, useValue: fakeApi() },
      ],
    });
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/admin?frame=account');
    harness.detectChanges();
    expect(screen.getByRole('navigation', { name: 'Verwaltungsbereiche' })).toBeInTheDocument();
    expect(screen.queryByRole('navigation', { name: 'Kontobereiche' })).toBeNull();
  });
});
