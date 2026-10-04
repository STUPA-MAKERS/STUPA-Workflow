import { Component, signal } from '@angular/core';
import { Router, provideRouter, type Routes } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { render, screen, within } from '@testing-library/angular';
import { ShellComponent } from './shell.component';
import { AuthService } from '@core/auth/auth.service';
import { USE_MOCK_API } from '@core/api/api.config';
import { BrandingService } from '@core/branding/branding.service';
import type { Principal } from '@core/api/models';
import { RailStatusService } from './rail-status.service';
import { createLocationMock, provideLocationMock } from '../../testing/location-mock';

const MEMBER: Principal = {
  sub: '1',
  display_name: 'Mia Member',
  email: 'mia@stupa',
  roles: ['member'],
  permissions: ['application.read'],
  groups: [],
};

@Component({ standalone: true, template: '<h1>Seite</h1>' })
class StubPage {}

const ROUTES: Routes = [
  { path: 'dashboard', component: StubPage },
  { path: 'tasks', component: StubPage },
  { path: 'beamer', component: StubPage, data: { chrome: false } },
  {
    path: 'budget',
    component: StubPage,
    children: [{ path: 'wide', component: StubPage, data: { wide: true } }],
  },
];

/** The marks of the rail, set by the test instead of HTTP. */
function railStatusStub(tasks: number | null = 4, live = true) {
  return { taskCount: signal(tasks), live: signal(live), refresh: () => undefined };
}

function brandingStub(
  over: {
    copyright?: Record<string, string> | null;
    legalLinks?: { label: Record<string, string>; url: string }[];
    footerColumns?: { label: Record<string, string>; links: { label: Record<string, string>; url: string }[] }[];
  } = {},
) {
  return {
    appName: signal('STUPA'),
    homeHeading: signal('Willkommen'),
    copyright: signal(over.copyright ?? null),
    legalLinks: signal(over.legalLinks ?? []),
    footerColumns: signal(over.footerColumns ?? []),
    init: () => undefined,
  };
}

/** Let `matchMedia` report a phone viewport for the phone media query only. */
function phoneViewport(): () => void {
  const original = window.matchMedia;
  window.matchMedia = ((query: string) => ({
    matches: query === '(max-width: 768px)',
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
  return () => (window.matchMedia = original);
}

async function setup(
  principal: Principal | null | 'pending',
  opts: { branding?: ReturnType<typeof brandingStub>; status?: ReturnType<typeof railStatusStub> } = {},
) {
  localStorage.setItem('ap.locale', 'de');
  const view = await render(ShellComponent, {
    providers: [
      provideRouter(ROUTES),
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
      provideLocationMock(createLocationMock()),
      { provide: BrandingService, useValue: opts.branding ?? brandingStub() },
      { provide: RailStatusService, useValue: opts.status ?? railStatusStub() },
    ],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  const auth = view.fixture.debugElement.injector.get(AuthService);
  const router = view.fixture.debugElement.injector.get(Router);
  if (principal !== 'pending') {
    const req = http.expectOne('/api/auth/me');
    if (principal) req.flush(principal);
    else req.flush(null, { status: 401, statusText: 'Unauthorized' });
  }
  view.fixture.detectChanges();
  return { ...view, http, auth, router };
}

/** The main navigation (rail or phone bar). */
const mainNav = () => screen.queryByRole('navigation', { name: 'Hauptnavigation' });

describe('ShellComponent', () => {
  afterEach(() => localStorage.clear());

  describe('frame', () => {
    it('shows no frame while the session is not known yet', async () => {
      const { container } = await setup('pending');
      expect(mainNav()).not.toBeInTheDocument();
      expect(container.querySelector('app-public-header')).toBeNull();
      expect(container.querySelector('app-site-footer')).toBeNull();
      expect(container.querySelector('main#main')).not.toBeNull();
    });

    it('frames a signed-out visitor with the public bar and the footer, without navigation', async () => {
      const { container } = await setup(null);
      expect(screen.getByRole('button', { name: 'Anmelden' })).toBeInTheDocument();
      expect(mainNav()).not.toBeInTheDocument();
      expect(container.querySelector('app-site-footer')).not.toBeNull();
      // Nobody signed in: no search palette either.
      expect(container.querySelector('app-command-palette')).toBeNull();
    });

    it('frames a signed-in principal with the rail and the footer, without the public bar', async () => {
      const { container } = await setup(MEMBER);
      expect(mainNav()).toBeInTheDocument();
      expect(container.querySelector('app-nav-rail')).not.toBeNull();
      expect(container.querySelector('app-bottom-bar')).toBeNull();
      expect(container.querySelector('app-public-header')).toBeNull();
      expect(container.querySelector('app-site-footer')).not.toBeNull();
      expect(container.querySelector('app-command-palette')).not.toBeNull();
    });

    it('shows a route with `chrome: false` (the beamer) without rail, bars or footer', async () => {
      const { router, fixture, container } = await setup(MEMBER);
      await router.navigateByUrl('/beamer');
      fixture.detectChanges();
      expect(mainNav()).not.toBeInTheDocument();
      expect(container.querySelector('app-site-footer')).toBeNull();
      expect(container.querySelector('main')).not.toHaveClass('page-shell');
      expect(screen.getByRole('heading', { name: 'Seite' })).toBeInTheDocument();

      // Back on a normal page the frame returns.
      await router.navigateByUrl('/dashboard');
      fixture.detectChanges();
      expect(mainNav()).toBeInTheDocument();
    });

    it('swaps the rail for the bottom bar on a phone', async () => {
      const restore = phoneViewport();
      try {
        const { container } = await setup(MEMBER);
        expect(container.querySelector('app-nav-rail')).toBeNull();
        expect(container.querySelector('app-bottom-bar')).not.toBeNull();
        expect(container.querySelector('.frame--phone')).not.toBeNull();
      } finally {
        restore();
      }
    });

    it('resolves the wide layout from the deepest active route data', async () => {
      const { router, fixture, container } = await setup(MEMBER);
      const main = () => container.querySelector('main') as HTMLElement;

      await router.navigateByUrl('/dashboard');
      fixture.detectChanges();
      expect(main()).not.toHaveClass('main--wide');

      await router.navigateByUrl('/budget/wide');
      fixture.detectChanges();
      expect(main()).toHaveClass('main--wide');
    });

    it('keeps the skip link to the main content', async () => {
      await setup(MEMBER);
      expect(screen.getByRole('link', { name: 'Zum Inhalt springen' })).toHaveAttribute('href', '#main');
    });
  });

  describe('rail entries', () => {
    /** The visible labels of the rail links, in rail order (without the brand mark and the search). */
    const labels = () =>
      Array.from((mainNav() as HTMLElement).querySelectorAll('a.rail__item .rail__label')).map((l) =>
        l.textContent?.trim(),
      );

    it('shows a member without budget or admin rights no Budget, Buchungen, Rechnungen or Verwaltung', async () => {
      await setup(MEMBER);
      const nav = within(mainNav() as HTMLElement);
      expect(nav.getByRole('link', { name: /^Start/ })).toHaveAttribute('href', '/dashboard');
      expect(nav.getByRole('link', { name: /^Anträge/ })).toBeInTheDocument();
      expect(nav.getByRole('link', { name: /^Aufgaben/ })).toBeInTheDocument();
      for (const hidden of [/^Budget/, /^Buchungen/, /^Rechnungen/, /^Verwaltung/, /^Abstimmungen/, /^Sitzungen/]) {
        expect(nav.queryByRole('link', { name: hidden })).not.toBeInTheDocument();
      }
    });

    it('shows Sitzungen and Abstimmungen for session.manage in a gremium', async () => {
      await setup({ ...MEMBER, gremium_permissions: { g1: ['session.manage'] } });
      const nav = within(mainNav() as HTMLElement);
      expect(nav.getByRole('link', { name: /^Sitzungen/ })).toHaveAttribute('href', '/meetings');
      expect(nav.getByRole('link', { name: /^Abstimmungen/ })).toHaveAttribute('href', '/voting');
    });

    it('shows Abstimmungen for vote.cast in a gremium', async () => {
      await setup({ ...MEMBER, gremium_permissions: { g1: ['vote.cast'] } });
      expect(within(mainNav() as HTMLElement).getByRole('link', { name: /^Abstimmungen/ })).toBeInTheDocument();
    });

    it('shows Sitzungen for a gremium member and for meeting.view_all', async () => {
      await setup({ ...MEMBER, gremien: [{ id: 'g1', name: 'StuPa' }] } as Principal);
      expect(within(mainNav() as HTMLElement).getByRole('link', { name: /^Sitzungen/ })).toBeInTheDocument();
    });

    it('shows only Budget for a scoped budget view, not the bookings or invoices', async () => {
      await setup({ ...MEMBER, has_scoped_budget_view: true });
      const nav = within(mainNav() as HTMLElement);
      expect(nav.getByRole('link', { name: /^Budget/ })).toBeInTheDocument();
      expect(nav.queryByRole('link', { name: /^Buchungen/ })).not.toBeInTheDocument();
    });

    it('shows every entry to the admin, Verwaltung last', async () => {
      await setup({ ...MEMBER, roles: ['admin'] });
      expect(labels()).toEqual([
        'Start',
        'Anträge',
        'Aufgaben',
        'Sitzungen',
        'Abstimmungen',
        'Budget',
        'Buchungen',
        'Rechnungen',
        'Verwaltung',
      ]);
    });

    it('leads the rail with the mark, which links to the start page', async () => {
      await setup(MEMBER);
      expect(
        within(mainNav() as HTMLElement).getByRole('link', { name: 'STUPA, Start' }),
      ).toHaveAttribute('href', '/dashboard');
    });

    it('marks the entry of the current page', async () => {
      const { router, fixture } = await setup(MEMBER);
      await router.navigateByUrl('/tasks');
      fixture.detectChanges();
      const nav = within(mainNav() as HTMLElement);
      expect(nav.getByRole('link', { name: /^Aufgaben/ })).toHaveAttribute('aria-current', 'page');
      expect(nav.getByRole('link', { name: /^Start/ })).not.toHaveAttribute('aria-current');
    });

    it('carries the task count and the live mark from the rail status', async () => {
      await setup({ ...MEMBER, roles: ['admin'] }, { status: railStatusStub(4, true) });
      const nav = within(mainNav() as HTMLElement);
      expect(nav.getByRole('link', { name: 'Aufgaben 4 offen' })).toBeInTheDocument();
      expect(nav.getByRole('link', { name: 'Sitzungen Sitzung läuft' })).toBeInTheDocument();
    });

    it('shows no marks without open tasks and without a live meeting', async () => {
      const { container } = await setup({ ...MEMBER, roles: ['admin'] }, { status: railStatusStub(0, false) });
      expect(container.querySelector('.mark__count')).toBeNull();
      expect(container.querySelector('.mark__live')).toBeNull();
    });
  });

  describe('footer', () => {
    const branding = brandingStub({
      copyright: { de: '© Verfasste Studierendenschaft' },
      legalLinks: [{ label: { de: 'Impressum' }, url: 'https://example.org/impressum' }],
      footerColumns: [
        { label: { de: 'Kontakt' }, links: [{ label: { de: 'AStA-Büro' }, url: 'https://example.org/asta' }] },
      ],
    });

    it('shows the branded footer on a public page', async () => {
      await setup(null, { branding });
      const footer = screen.getByRole('contentinfo');
      expect(within(footer).getByText('© Verfasste Studierendenschaft')).toBeInTheDocument();
      expect(within(footer).getByRole('link', { name: 'Impressum' })).toHaveAttribute(
        'href',
        'https://example.org/impressum',
      );
      expect(within(footer).getByRole('link', { name: 'AStA-Büro' })).toBeInTheDocument();
    });

    it('shows the same footer at the end of a signed-in page', async () => {
      await setup(MEMBER, { branding });
      const footer = screen.getByRole('contentinfo');
      expect(within(footer).getByRole('link', { name: 'Impressum' })).toBeInTheDocument();
      expect(within(footer).getByRole('heading', { name: 'Kontakt' })).toBeInTheDocument();
    });
  });
});
