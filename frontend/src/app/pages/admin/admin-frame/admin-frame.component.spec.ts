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
function matchWide(wide: boolean): void {
  window.matchMedia = ((query: string) => ({
    matches: wide && query.includes('min-width: 1200px'),
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

async function setup(perms: string[], url = '/admin/users', wide = true) {
  matchWide(wide);
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
    const view = await setup(ALL, '/admin');
    expect(screen.getByRole('heading', { name: 'Verwaltung', level: 1 })).toBeInTheDocument();
    expect(view.container.querySelector('app-admin-health')).not.toBeNull();
    expect(screen.getByText('Benutzer und Rollenzuweisungen')).toBeInTheDocument();
    expect(view.container.querySelector('.af')).toHaveClass('af--home');
    // The search hides the tiles: they are no entries.
    await userEvent.type(screen.getByRole('searchbox'), 'audit');
    expect(view.container.querySelector('app-admin-health')).toBeNull();
  });

  it('beside an admin page the title is no heading and the entries have no description', async () => {
    const view = await setup(ALL, '/admin/users');
    expect(screen.queryByRole('heading', { name: 'Verwaltung' })).toBeNull();
    expect(screen.queryByText('Benutzer und Rollenzuweisungen')).toBeNull();
    expect(view.container.querySelector('app-admin-health')).toBeNull();
    expect(view.container.querySelector('.af')).toHaveClass('af--split');
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

  it('keeps the home page in one column without a gremium page beside the navigation', async () => {
    const view = await setup(['backup.manage'], '/admin');
    expect(view.container.querySelector('.af')).not.toHaveClass('af--split');
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
