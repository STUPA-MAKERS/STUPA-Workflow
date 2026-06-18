/**
 * a11y-Scan der Kern-Views (T-43, requirements N3 — WCAG 2.1 AA).
 *
 * Ergänzt den Primitiv-Scan (`shared/ui/a11y.spec.ts`) um die zusammengesetzten
 * Views: Shell-Landmarks (anonym + angemeldet), Fehlerseiten (403/404), den
 * Apply-Wizard (N1a Multi-Step) und die Live-Vote-Ansicht (Live-Regionen).
 *
 * Für die Shell ist die `region`-Regel aktiv (Landmark-Struktur). Komponenten
 * ohne eigenes `<main>` werden in `<main>` gewrappt, damit Inhalte in einer
 * Landmark liegen.
 */
import { Component } from '@angular/core';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { of, Subject } from 'rxjs';
import { render } from '@testing-library/angular';
import { runAxe } from '../testing/a11y';
import { ShellComponent } from './layout/shell.component';
import { ForbiddenComponent } from './pages/forbidden.component';
import { NotFoundComponent } from './pages/not-found.component';
import { ApplyWizardComponent } from './features/apply/apply-wizard.component';
import { LiveVoteComponent } from './features/voting/live-vote.component';
import { BeamerComponent } from './features/voting/beamer.component';
import { AdminHomeComponent } from './pages/admin/admin-home.component';
import { UsersComponent } from './pages/admin/users/users.component';
import { FlowEditorComponent } from './pages/admin/flow-editor/flow-editor.component';
import { BrandingEditorComponent } from './pages/admin/branding/branding-editor.component';
import { AdminApiService } from './pages/admin/admin-api.service';
import { BudgetTreeApi } from './pages/budget/budget-tree.api';
import { AuthService } from '@core/auth/auth.service';
import { USE_MOCK_API } from '@core/api/api.config';
import { ApiClient } from '@core/api/api-client.service';
import { provideFormly } from '@shared/formly/formly.providers';
import { LIVE_VOTE_SOURCE, type LiveVoteSource } from '@core/ws/live-vote.source';
import type { MeetingChannel } from '@core/ws/ws.service';
import type { ClientMessage, ServerMessage } from '@core/ws/ws-messages';
import type { ApplicationType, EffectiveForm, Principal } from '@core/api/models';

const MEMBER: Principal = {
  sub: '1',
  display_name: 'Mia Member',
  email: 'mia@stupa',
  roles: ['member'],
  permissions: ['application.read', 'vote.cast'],
  groups: [],
};

describe('Kern-Views a11y (axe)', () => {
  describe('Shell (Landmarks)', () => {
    async function setupShell() {
      const view = await render(ShellComponent, {
        providers: [
          provideRouter([]),
          provideHttpClient(),
          provideHttpClientTesting(),
          { provide: USE_MOCK_API, useValue: false },
        ],
      });
      const auth = view.fixture.debugElement.injector.get(AuthService);
      const http = view.fixture.debugElement.injector.get(HttpTestingController);
      http
        .match((r) => r.url.endsWith('/admin/site-config'))
        .forEach((req) =>
          req.flush({
            version: 1,
            active: { logos: {}, footerColumns: [], copyright: {}, legalLinks: [], freetexts: {} },
            draft: { logos: {}, footerColumns: [], copyright: {}, legalLinks: [], freetexts: {} },
            hasDraftChanges: false,
          }),
        );
      return { view, auth, http };
    }

    it('anonymous shell has valid landmarks and no violations', async () => {
      const { view } = await setupShell();
      expect(await runAxe(view.container, { rules: { region: { enabled: true } } })).toHaveNoViolations();
    });

    it('authenticated shell (full nav) has no violations', async () => {
      const { view, auth, http } = await setupShell();
      auth.ensureLoaded().subscribe();
      http.expectOne('/api/auth/me').flush(MEMBER);
      view.fixture.detectChanges();
      expect(await runAxe(view.container, { rules: { region: { enabled: true } } })).toHaveNoViolations();
    });
  });

  describe('Fehlerseiten', () => {
    @Component({
      standalone: true,
      imports: [ForbiddenComponent],
      template: `<main><app-forbidden /></main>`,
    })
    class ForbiddenHost {}

    @Component({
      standalone: true,
      imports: [NotFoundComponent],
      template: `<main><app-not-found /></main>`,
    })
    class NotFoundHost {}

    it('403 /forbidden has no violations', async () => {
      const { container } = await render(ForbiddenHost, { providers: [provideRouter([])] });
      expect(await runAxe(container, { rules: { region: { enabled: true } } })).toHaveNoViolations();
    });

    it('404 not-found has no violations', async () => {
      const { container } = await render(NotFoundHost, { providers: [provideRouter([])] });
      expect(await runAxe(container, { rules: { region: { enabled: true } } })).toHaveNoViolations();
    });
  });

  describe('Apply-Wizard', () => {
    const TYPES: ApplicationType[] = [
      {
        id: 't1',
        name: 'Finanzantrag',
        active: true,
        hasBudget: true,
        activeFormVersionId: 'v1',
        key: null,
        gremiumId: null,
      },
    ];
    const EFF: EffectiveForm = {
      applicationTypeId: 't1',
      formVersionId: 'v1',
      budgetPotId: 'pot1',
      sections: [
        {
          key: 'main',
          label: { de: 'Antrag' },
          fields: [
            { key: 'title', type: 'text', label: { de: 'Titel' }, required: true },
            { key: 'amount', type: 'currency', label: { de: 'Betrag' }, required: true },
          ],
        },
      ],
    };
    const fakeApi: Partial<ApiClient> = {
      applicationTypes: () => of(TYPES),
      effectiveForm: () => of(EFF),
      // Anonyme Session — AuthService.ensureLoaded() im Wizard-Konstruktor (#24).
      me: (() => of(null)) as unknown as ApiClient['me'],
      // Branding-Info unter der Typ-Auswahl (#18) — leer im Test.
      publicSiteConfig: () => of({ version: 1, branding: null }),
    };

    @Component({
      standalone: true,
      imports: [ApplyWizardComponent],
      template: `<main><app-apply-wizard /></main>`,
    })
    class WizardHost {}

    it('wizard has no violations', async () => {
      const { container } = await render(WizardHost, {
        providers: [provideRouter([]), provideFormly(), { provide: ApiClient, useValue: fakeApi }],
      });
      expect(await runAxe(container, { rules: { region: { enabled: true } } })).toHaveNoViolations();
    });
  });

  describe('Live-Vote', () => {
    class FakeChannel implements MeetingChannel {
      readonly subject = new Subject<ServerMessage>();
      readonly messages$ = this.subject.asObservable();
      send(_msg: ClientMessage): void {}
      close(): void {
        this.subject.complete();
      }
    }
    class FakeSource implements LiveVoteSource {
      readonly channels: FakeChannel[] = [];
      connectMeeting(): MeetingChannel {
        const ch = new FakeChannel();
        this.channels.push(ch);
        return ch;
      }
    }
    const OPEN_VOTE: ServerMessage = {
      type: 'vote_opened',
      voteId: 'v1',
      applicationId: 'a1',
      options: ['yes', 'no', 'abstain'],
      closesAt: null,
    };

    @Component({
      standalone: true,
      imports: [LiveVoteComponent],
      template: `<main><app-live-vote /></main>`,
    })
    class LiveVoteHost {}

    it('open live-vote (options + live region) has no violations', async () => {
      const source = new FakeSource();
      const view = await render(LiveVoteHost, {
        providers: [
          provideRouter([]),
          { provide: LIVE_VOTE_SOURCE, useValue: source },
          { provide: AuthService, useValue: { can: () => true } },
          {
            provide: ActivatedRoute,
            useValue: { snapshot: { paramMap: convertToParamMap({ id: 'm1' }) } },
          },
        ],
      });
      source.channels[0].subject.next(OPEN_VOTE);
      view.fixture.detectChanges();
      expect(await runAxe(view.container, { rules: { region: { enabled: true } } })).toHaveNoViolations();
    });

    @Component({
      standalone: true,
      imports: [BeamerComponent],
      template: `<main><app-beamer /></main>`,
    })
    class BeamerHost {}

    it('beamer view (high-contrast/large, read-only) has no violations', async () => {
      const source = new FakeSource();
      const view = await render(BeamerHost, {
        providers: [
          provideRouter([]),
          { provide: LIVE_VOTE_SOURCE, useValue: source },
          {
            provide: ActivatedRoute,
            useValue: { snapshot: { paramMap: convertToParamMap({ id: 'm1' }) } },
          },
        ],
      });
      source.channels[0].subject.next(OPEN_VOTE);
      view.fixture.detectChanges();
      expect(await runAxe(view.container, { rules: { region: { enabled: true } } })).toHaveNoViolations();
    });
  });

  describe('Admin-Views (T-43 AC: Admin/Flow-Editor)', () => {
    // Reads liefern aus admin.mock (USE_MOCK_API) bzw. werden gefaket — die
    // Views sollen ihre volle Struktur (Headings/Tabellen/Forms) rendern.
    const adminHttp = [provideHttpClient(), provideHttpClientTesting()];

    @Component({
      standalone: true,
      imports: [AdminHomeComponent],
      template: `<main><app-admin-home /></main>`,
    })
    class AdminHomeHost {}

    @Component({
      standalone: true,
      imports: [UsersComponent],
      template: `<main><app-admin-users /></main>`,
    })
    class UsersHost {}

    @Component({
      standalone: true,
      imports: [FlowEditorComponent],
      template: `<main><app-flow-editor /></main>`,
    })
    class FlowEditorHost {}

    @Component({
      standalone: true,
      imports: [BrandingEditorComponent],
      template: `<main><app-branding-editor /></main>`,
    })
    class BrandingHost {}

    /** Fake-AdminApiService: Reads mit minimalen Daten, Mutationen als No-op. */
    function fakeAdminApi(): Partial<AdminApiService> {
      const role = {
        id: 'r-admin',
        key: 'admin',
        label: { de: 'administrator', en: 'administrator' },
        permissions: ['admin.roles'],
      };
      const principal = {
        id: 'p-1',
        sub: 'kc|alex',
        email: 'alex@x.de',
        displayName: 'Alex Admin',
        lastLogin: null,
        assignments: [],
      };
      return {
        listRoles: jest.fn(() => of([role])),
        listPermissions: jest.fn(() => of(['admin.roles', 'application.read'])),
        listPrincipals: jest.fn(() => of([principal])),
        listGremienOptions: jest.fn(() => of([{ id: 'g-1', name: 'StuPa' }])),
        assignRole: jest.fn(() => of({ id: 'a-new' })),
        revokeRole: jest.fn(() => of(void 0)),
        saveRolePermissions: jest.fn(() => of(role)),
        listApplicationTypes: jest.fn(() => of([{ id: 't1', name: 'Finanzantrag' }])),
        listGremiumRoles: jest.fn(() => of([])),
        getGlobalFlow: jest.fn(() => of(null)),
        createGlobalFlowVersion: jest.fn(() => of({ id: 'gfv1' })),
        listWebhooks: jest.fn(() => of([])),
        listDeadlinePolicies: jest.fn(() => of([])),
        listConfigRevisions: jest.fn(() => of([])),
      } as unknown as Partial<AdminApiService>;
    }

    it('/admin home has no violations', async () => {
      const { container } = await render(AdminHomeHost, {
        providers: [provideRouter([]), ...adminHttp, { provide: USE_MOCK_API, useValue: true }],
      });
      expect(await runAxe(container, { rules: { region: { enabled: true } } })).toHaveNoViolations();
    });

    it('/admin/users has no violations', async () => {
      const { container } = await render(UsersHost, {
        providers: [provideRouter([]), ...adminHttp, { provide: AdminApiService, useValue: fakeAdminApi() }],
      });
      expect(await runAxe(container, { rules: { region: { enabled: true } } })).toHaveNoViolations();
    });

    it('flow-editor has no violations', async () => {
      const { container } = await render(FlowEditorHost, {
        providers: [
          provideRouter([]),
          { provide: AdminApiService, useValue: fakeAdminApi() },
          // Kostenstellen-Namen für Guard-Labels (#7) — leerer Baum genügt.
          { provide: BudgetTreeApi, useValue: { tree: () => of([]) } },
        ],
      });
      expect(await runAxe(container, { rules: { region: { enabled: true } } })).toHaveNoViolations();
    });

    it('branding-editor has no violations', async () => {
      const { container } = await render(BrandingHost, {
        providers: [provideRouter([]), ...adminHttp, { provide: USE_MOCK_API, useValue: true }],
      });
      expect(await runAxe(container, { rules: { region: { enabled: true } } })).toHaveNoViolations();
    });
  });
});
