import { Component, signal } from '@angular/core';
import { Router, provideRouter, type Routes } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { render, screen, within } from '@testing-library/angular';
import { DeferBlockState } from '@angular/core/testing';
import { HelpService } from '../features/help/help.service';
import { ShellComponent } from './shell.component';
import { AuthService } from '@core/auth/auth.service';
import { USE_MOCK_API } from '@core/api/api.config';
import { BrandingService } from '@core/branding/branding.service';
import type { Principal } from '@core/api/models';
import { provideAppUiKit } from '@core/i18n/ui-kit-intl';
import { PageFrame } from '@stupa-makers/ui-kit';
import { CommandPalette } from '@stupa-makers/ui-kit/shell';
import userEvent from '@testing-library/user-event';
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
  { path: 'account/notifications', component: StubPage },
  { path: 'expenses', component: StubPage },
  { path: 'protokolle', component: StubPage, data: { footer: true } },
  { path: 'tasks', component: StubPage },
  { path: 'beamer', component: StubPage, data: { chrome: false } },
  { path: 'start', component: StubPage, data: { fab: true } },
  {
    path: 'budget',
    component: StubPage,
    children: [{ path: 'wide', component: StubPage, data: { wide: true } }],
  },
];

/** The marks of the rail, set by the test instead of HTTP. */
function railStatusStub(tasks: number | null = 4, live = true, tickets: number | null = null) {
  return { taskCount: signal(tasks), ticketCount: signal<number | null>(tickets), live: signal(live), refresh: () => undefined };
}

/** The avatars read these. The config is not loaded, so they show the initials. */
function brandingStub(
  over: {
    copyright?: Record<string, string> | null;
    legalLinks?: { label: Record<string, string>; url: string }[];
  } = {},
) {
  return {
    appName: signal('STUPA'),
    homeHeading: signal('Willkommen'),
    wordmarkSrc: signal('assets/logos/stupa-wordmark-light.svg'),
    markSrc: signal('assets/logos/stupa-mark.svg'),
    copyright: signal(over.copyright ?? null),
    legalLinks: signal(over.legalLinks ?? []),
    loaded: signal(false),
    gravatarEnabled: signal(true),
    wikiUrl: signal('https://wiki.example.org/handbook'),
    ticketsPublic: signal(false),
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
      provideAppUiKit(),
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

    /** With nobody signed in there is no search palette either. */
    it('frames a signed-out visitor with the public bar and the footer, without navigation', async () => {
      const { container } = await setup(null);
      expect(screen.getByRole('button', { name: 'Anmelden' })).toBeInTheDocument();
      expect(mainNav()).not.toBeInTheDocument();
      expect(container.querySelector('app-site-footer')).not.toBeNull();
      expect(container.querySelector('app-command-palette')).toBeNull();
    });

    it('loads the report dialog only on its first opening', async () => {
      const { container, fixture } = await setup(MEMBER);
      expect(container.querySelector('app-report-dialog')).toBeNull();
      fixture.debugElement.injector.get(HelpService).openReport();
      fixture.detectChanges();
      const [block] = await fixture.getDeferBlocks();
      await block.render(DeferBlockState.Complete);
      expect(container.querySelector('app-report-dialog')).not.toBeNull();
    });

    /** No route with `footer: true` is open, so a signed-in page has no footer. */
    it('frames a signed-in principal with the rail, without the public bar', async () => {
      const { container } = await setup(MEMBER);
      expect(mainNav()).toBeInTheDocument();
      expect(container.querySelector('app-nav-rail')).not.toBeNull();
      expect(container.querySelector('app-bottom-bar')).toBeNull();
      expect(container.querySelector('app-public-header')).toBeNull();
      expect(container.querySelector('app-site-footer')).toBeNull();
      expect(container.querySelector('app-command-palette')).not.toBeNull();
    });

    /** Back on a normal page the frame returns. */
    it('shows a route with `chrome: false` (the beamer) without rail, bars or footer', async () => {
      const { router, fixture, container } = await setup(MEMBER);
      await router.navigateByUrl('/beamer');
      fixture.detectChanges();
      expect(mainNav()).not.toBeInTheDocument();
      expect(container.querySelector('app-site-footer')).toBeNull();
      expect(container.querySelector('main')).not.toHaveClass('page-shell');
      expect(screen.getByRole('heading', { name: 'Seite' })).toBeInTheDocument();

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

    it('keeps the foot of the page free for a floating button only on a phone route with `fab`', async () => {
      const restore = phoneViewport();
      try {
        const { router, fixture, container } = await setup(MEMBER);
        const frame = () => container.querySelector('.frame') as HTMLElement;

        await router.navigateByUrl('/dashboard');
        fixture.detectChanges();
        expect(frame()).not.toHaveClass('frame--fab');

        await router.navigateByUrl('/start');
        fixture.detectChanges();
        expect(frame()).toHaveClass('frame--phone');
        expect(frame()).toHaveClass('frame--fab');
      } finally {
        restore();
      }
    });

    it('gives a `fab` route no clearance outside a phone', async () => {
      const { router, fixture, container } = await setup(MEMBER);
      await router.navigateByUrl('/start');
      fixture.detectChanges();
      expect(container.querySelector('.frame--fab')).toBeNull();
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
        'Boards',
        'Sitzungen',
        'Gremien',
        'Abstimmungen',
        'Budget',
        'Buchungen',
        'Rechnungen',
        'Tickets',
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
    });

    it('shows the branded footer on a public page', async () => {
      await setup(null, { branding });
      const footer = screen.getByRole('contentinfo');
      expect(within(footer).getByText('© Verfasste Studierendenschaft')).toBeInTheDocument();
      expect(within(footer).getByRole('link', { name: 'Impressum' })).toHaveAttribute(
        'href',
        'https://example.org/impressum',
      );
    });

    it('shows the footer on every public page, also without route data `footer`', async () => {
      const { router, fixture } = await setup(null, { branding });
      await router.navigateByUrl('/tasks');
      fixture.detectChanges();
      expect(screen.getByRole('contentinfo')).toBeInTheDocument();
    });

    it('shows the same footer at the end of a signed-in page with route data `footer` (a public page)', async () => {
      const { router, fixture } = await setup(MEMBER, { branding });
      await router.navigateByUrl('/protokolle');
      fixture.detectChanges();
      const footer = screen.getByRole('contentinfo');
      expect(within(footer).getByRole('link', { name: 'Impressum' })).toBeInTheDocument();
      expect(within(footer).getByText('© Verfasste Studierendenschaft')).toBeInTheDocument();
    });

    /** The start page is a work page too, because whoever sees it is signed in. */
    it('leaves the footer out on a signed-in work page, and brings it back on a public page', async () => {
      const { router, fixture } = await setup(MEMBER, { branding });
      await router.navigateByUrl('/tasks');
      fixture.detectChanges();
      expect(screen.queryByRole('contentinfo')).not.toBeInTheDocument();
      await router.navigateByUrl('/dashboard');
      fixture.detectChanges();
      expect(screen.queryByRole('contentinfo')).not.toBeInTheDocument();
      await router.navigateByUrl('/budget/wide');
      fixture.detectChanges();
      expect(screen.queryByRole('contentinfo')).not.toBeInTheDocument();
      await router.navigateByUrl('/protokolle');
      fixture.detectChanges();
      expect(screen.getByRole('contentinfo')).toBeInTheDocument();
    });

    it('leaves the footer out while the page fills the viewport', async () => {
      const view = await setup(MEMBER, { branding });
      await view.router.navigateByUrl('/protokolle');
      view.fixture.detectChanges();
      const frame = view.fixture.debugElement.injector.get(PageFrame);
      frame.fill.set(true);
      view.fixture.detectChanges();
      expect(screen.queryByRole('contentinfo')).not.toBeInTheDocument();
      expect(view.container.querySelector('main')).toHaveClass('main--fill');
      frame.fill.set(false);
      view.fixture.detectChanges();
      expect(screen.getByRole('contentinfo')).toBeInTheDocument();
    });
  });

  describe('phone bar', () => {
    let restore: () => void;
    beforeEach(() => (restore = phoneViewport()));
    afterEach(() => restore());

    const bar = () => screen.getByRole('navigation', { name: 'Hauptnavigation' });
    const more = () => within(bar()).getByRole('button', { name: 'Mehr' });
    const ADMIN: Principal = { ...MEMBER, display_name: 'Ada Admin', roles: ['admin'] };

    it('shows Start, Anträge, Sitzungen and Aufgaben, then Mehr', async () => {
      await setup(ADMIN, { status: railStatusStub(8, true) });
      const labels = Array.from(bar().querySelectorAll('.bb__label')).map((l) => l.textContent?.trim());
      expect(labels).toEqual(['Start', 'Anträge', 'Sitzungen', 'Aufgaben', 'Mehr']);
      expect(within(bar()).getByRole('link', { name: 'Aufgaben 8 offen' })).toHaveAttribute('href', '/tasks');
      expect(within(bar()).getByRole('link', { name: 'Sitzungen Sitzung läuft' })).toBeInTheDocument();
    });

    /** The bar entries are not repeated in the sheet. The help entries and the account follow. */
    it('lists the other areas, the search, the help and the account in the Mehr sheet', async () => {
      const { fixture } = await setup(ADMIN);
      await userEvent.click(more());
      fixture.detectChanges();
      const sheet = screen.getByRole('dialog', { name: 'Mehr' });
      for (const name of ['Abstimmungen', 'Budget', 'Buchungen', 'Rechnungen', 'Verwaltung']) {
        expect(within(sheet).getByRole('link', { name })).toBeInTheDocument();
      }
      expect(within(sheet).queryByRole('link', { name: 'Start' })).not.toBeInTheDocument();
      expect(within(sheet).getByRole('button', { name: 'Suche' })).toBeInTheDocument();
      expect(within(sheet).getByRole('group', { name: 'Hilfe' })).toBeInTheDocument();
      expect(within(sheet).getByRole('group', { name: 'Konto' })).toBeInTheDocument();
      expect(within(sheet).getByText('Ada Admin')).toBeInTheDocument();
      expect(within(sheet).getByRole('link', { name: 'Benachrichtigungen' })).toBeInTheDocument();
    });

    it('opens the search palette from the sheet and closes the sheet', async () => {
      const { fixture } = await setup(ADMIN);
      await userEvent.click(more());
      fixture.detectChanges();
      await userEvent.click(screen.getByRole('button', { name: 'Suche' }));
      fixture.detectChanges();
      expect(fixture.debugElement.injector.get(CommandPalette).isOpen()).toBe(true);
      expect(screen.queryByRole('dialog', { name: 'Mehr' })).not.toBeInTheDocument();
    });

    it('marks Mehr as active on a page that lives in the sheet and on the account pages', async () => {
      const { fixture, router } = await setup(ADMIN);
      await router.navigateByUrl('/expenses');
      fixture.detectChanges();
      expect(more()).toHaveClass('is-active');
      await router.navigateByUrl('/account/notifications');
      fixture.detectChanges();
      expect(more()).toHaveClass('is-active');
      await router.navigateByUrl('/dashboard');
      fixture.detectChanges();
      expect(more()).not.toHaveClass('is-active');
    });
  });

  describe('nav marks', () => {
    it('caps the task badge at 99+ but says the full count', async () => {
      const { container } = await setup(MEMBER, { status: railStatusStub(120, false) });
      expect(container.querySelector('.mark__count')).toHaveTextContent('99+');
      expect(screen.getByRole('link', { name: 'Aufgaben 120 offen' })).toBeInTheDocument();
    });

    it('shows no badge before the first answer', async () => {
      const { container } = await setup(MEMBER, { status: railStatusStub(null, false) });
      expect(container.querySelector('.mark__count')).toBeNull();
      expect(screen.getByRole('link', { name: 'Aufgaben' })).toBeInTheDocument();
    });

    it('counts the new tickets on the Tickets entry', async () => {
      await setup({ ...MEMBER, roles: ['admin'] }, { status: railStatusStub(0, false, 3) });
      expect(screen.getByRole('link', { name: 'Tickets 3 neu' })).toHaveAttribute('href', '/tickets');
    });
  });

  describe('rail foot', () => {
    it('puts the help menu and the account menu at the foot of the rail', async () => {
      const { container } = await setup(MEMBER);
      expect(container.querySelector('.rail__tools app-help-menu')).not.toBeNull();
      expect(
        screen.getByRole('button', { name: 'Konto: Mia Member' }).closest('.rail__account'),
      ).not.toBeNull();
    });

    it('opens the search palette from the rail', async () => {
      const { fixture } = await setup(MEMBER);
      const button = within(mainNav() as HTMLElement).getByRole('button', { name: 'Suche' });
      expect(button).toHaveAttribute('aria-keyshortcuts', expect.stringMatching(/^(Control|Meta)\+K$/));
      await userEvent.click(button);
      expect(fixture.debugElement.injector.get(CommandPalette).isOpen()).toBe(true);
    });
  });
});
