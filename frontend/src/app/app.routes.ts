import type { Routes } from '@angular/router';
import { authGuard } from '@core/auth/auth.guard';
import { ShellComponent } from './layout/shell.component';

/**
 * Routing-Gerüst (T-03). OIDC-Bereiche sind per `authGuard` geschützt; einzelne
 * Bereiche fordern zusätzlich eine RBAC-Permission (`data.permission`, T-36).
 * Feature-Inhalte folgen je Strang (T-30…T-35); offene Bereiche zeigen vorerst
 * den Platzhalter, sind aber bereits korrekt gated.
 */
export const routes: Routes = [
  {
    path: '',
    component: ShellComponent,
    children: [
      {
        path: '',
        loadComponent: () => import('./pages/home.component').then((m) => m.HomeComponent),
      },
      {
        path: 'apply',
        data: { title: 'apply.title' },
        loadComponent: () =>
          import('./features/apply/apply-wizard.component').then((m) => m.ApplyWizardComponent),
      },
      {
        path: 'apply/confirmation',
        data: { title: 'apply.confirm.heading' },
        loadComponent: () =>
          import('./features/apply/apply-confirmation.component').then(
            (m) => m.ApplyConfirmationComponent,
          ),
      },
      {
        path: 'status',
        data: { title: 'status.heading' },
        loadComponent: () =>
          import('./features/apply/status-timeline.component').then(
            (m) => m.StatusTimelineComponent,
          ),
      },
      {
        path: 'dashboard',
        data: { title: 'nav.dashboard' },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/dashboard/dashboard.component').then((m) => m.DashboardComponent),
      },
      {
        path: 'applications',
        // Kein Permission-Gate: ohne ``application.read`` sieht man die **eigenen**
        // Anträge (Server filtert auf ``created_by``), #24.
        data: { title: 'nav.applications', wide: true },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/applications/applications-list.component').then(
            (m) => m.ApplicationsListComponent,
          ),
      },
      {
        path: 'tasks',
        // Kein Permission-Gate: zeigt mind. die eigenen Anträge in bearbeitbarem State.
        data: { title: 'nav.tasks' },
        canActivate: [authGuard],
        loadComponent: () => import('./pages/tasks/tasks.component').then((m) => m.TasksComponent),
      },
      {
        path: 'applications/:id',
        // Kein Permission-Gate: Ersteller:innen erreichen den eigenen Antrag; der
        // Server autorisiert (``application.read``/Owner/Magic-Link), #24.
        data: { title: 'applications.detail.crumb', parent: ['applications'], wide: true },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/applications/applications-detail.component').then(
            (m) => m.ApplicationsDetailComponent,
          ),
      },
      {
        path: 'voting',
        data: { title: 'nav.voting', permission: ['vote.cast', 'vote.manage'] },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./features/voting/live-vote.component').then((m) => m.LiveVoteComponent),
      },
      {
        // Beamer-/Projektor-Ansicht (read-only). Vor `vote/:id` deklariert.
        path: 'voting/beamer',
        data: { title: 'voting.beamer.heading', permission: 'meeting.manage' },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./features/voting/beamer.component').then((m) => m.BeamerComponent),
      },
      {
        path: 'voting/beamer/:id',
        data: { title: 'voting.beamer.heading', permission: 'meeting.manage' },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./features/voting/beamer.component').then((m) => m.BeamerComponent),
      },
      {
        path: 'voting/meeting/:id',
        data: { title: 'voting.live.heading', permission: ['vote.cast', 'vote.manage'] },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./features/voting/live-vote.component').then((m) => m.LiveVoteComponent),
      },
      {
        path: 'voting/vote/:id',
        data: { title: 'voting.cast.heading', permission: ['vote.cast', 'vote.manage'] },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./features/voting/vote-cast.component').then((m) => m.VoteCastComponent),
      },
      {
        path: 'meetings',
        data: { title: 'nav.meetings', permission: ['meeting.manage', 'protocol.write'] },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./features/meetings/meetings.component').then((m) => m.MeetingsComponent),
      },
      {
        path: 'meetings/:id',
        data: {
          title: 'nav.meetings',
          permission: ['meeting.manage', 'protocol.write'],
          wide: true,
        },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./features/meetings/meetings.component').then((m) => m.MeetingsComponent),
      },
      {
        path: 'budget',
        data: { title: 'nav.budget', permission: ['budget.view', 'budget.manage'], wide: true },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/budget/budget-dashboard.component').then(
            (m) => m.BudgetDashboardComponent,
          ),
      },
      {
        path: 'expenses',
        data: { title: 'nav.expenses', permission: ['budget.view', 'budget.manage'], wide: true },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/expenses/expenses.component').then((m) => m.ExpensesComponent),
      },
      {
        // Kostenstellen-Baum in der Verwaltung (#9) — ersetzt die flache Töpfe-Liste.
        path: 'admin/budget-pots',
        data: { title: 'budget.tree.title', permission: 'budget.manage', parent: ['admin'], wide: true },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/budget/budget-tree.component').then((m) => m.BudgetTreeComponent),
      },
      {
        // Konten (Name + IBAN) in der Verwaltung — nicht an Kostenstellen gebunden.
        path: 'admin/accounts',
        data: { title: 'admin.accounts.title', permission: 'account.manage', parent: ['admin'] },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/admin/accounts/accounts.component').then((m) => m.AccountsComponent),
      },
      {
        path: 'admin',
        data: { title: 'nav.admin', permission: 'admin.config' },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/admin/admin-home.component').then((m) => m.AdminHomeComponent),
      },
      {
        path: 'admin/users',
        data: { title: 'admin.users.title', permission: 'admin.roles', parent: ['admin'] },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/admin/users/users.component').then((m) => m.UsersComponent),
      },
      {
        // Rollen-Rechte aus dem Benutzer-Screen herausgelöst (#12).
        path: 'admin/roles',
        data: { title: 'admin.roles.title', permission: 'admin.roles', parent: ['admin'] },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/admin/roles/roles.component').then((m) => m.AdminRolesComponent),
      },
      {
        path: 'admin/forms',
        data: { title: 'admin.forms.listTitle', permission: 'form.configure', parent: ['admin'] },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/admin/forms/forms-list.component').then((m) => m.FormsListComponent),
      },
      {
        path: 'admin/forms/:id',
        data: { title: 'admin.forms.edit', permission: 'form.configure', parent: ['admin', 'admin/forms'] },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/admin/forms/form-editor.component').then((m) => m.FormEditorComponent),
      },
      {
        path: 'admin/flow',
        data: { title: 'admin.flow.title', permission: 'flow.configure', parent: ['admin'] },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/admin/flow-editor/flow-editor.component').then(
            (m) => m.FlowEditorComponent,
          ),
      },
      {
        path: 'admin/gremien',
        data: { title: 'admin.gremien.title', permission: 'admin.config', parent: ['admin'] },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/admin/gremien/gremien.component').then((m) => m.AdminGremienComponent),
      },
      {
        // Mitglieder-Unterseite je Gremium (#18).
        path: 'admin/gremien/:id/members',
        data: { title: 'admin.gremien.membersOf', permission: 'admin.config', parent: ['admin', 'admin/gremien'] },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/admin/gremien/gremium-members.component').then(
            (m) => m.GremiumMembersComponent,
          ),
      },
      {
        path: 'admin/branding',
        data: { title: 'admin.brand.title', permission: 'admin.config', parent: ['admin'] },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/admin/branding/branding-editor.component').then(
            (m) => m.BrandingEditorComponent,
          ),
      },
      {
        path: 'admin/webhooks',
        data: { title: 'admin.webhook.title', permission: 'webhook.manage', parent: ['admin'] },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/admin/config/webhooks.component').then((m) => m.WebhooksComponent),
      },
      {
        path: 'admin/gremien/:id/roles',
        data: { title: 'admin.gremiumRoles.title', permission: 'admin.roles', parent: ['admin', 'admin/gremien'] },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/admin/gremium-roles/gremium-roles.component').then(
            (m) => m.GremiumRolesComponent,
          ),
      },
      {
        path: 'admin/audit',
        data: { title: 'admin.audit.title', permission: 'audit.read', parent: ['admin'] },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/admin/audit/audit-log.component').then((m) => m.AuditLogComponent),
      },
      {
        path: 'admin/delegations',
        data: { title: 'admin.deleg.title', permission: 'admin.roles', parent: ['admin'] },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/admin/delegations/delegations.component').then(
            (m) => m.DelegationsComponent,
          ),
      },
      {
        path: 'admin/deadlines',
        data: { title: 'admin.deadlines.title', permission: 'admin.config', parent: ['admin'] },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/admin/deadlines/deadlines.component').then(
            (m) => m.AdminDeadlinesComponent,
          ),
      },
      {
        // OAuth-Consent (#MCP): nach Login Scope + Token-Lebensdauer wählen.
        path: 'oauth/consent',
        data: { title: 'account.consent.title' },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/account/consent.component').then((m) => m.OAuthConsentComponent),
      },
      {
        // Konto → API-Zugang (#MCP): eigene OAuth-Grants verwalten + MCP-Paket laden.
        path: 'account/grants',
        data: { title: 'account.grants.title' },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/account/grants.component').then((m) => m.AccountGrantsComponent),
      },
      {
        path: 'forbidden',
        data: { title: 'forbidden.heading' },
        loadComponent: () =>
          import('./pages/forbidden.component').then((m) => m.ForbiddenComponent),
      },
      {
        path: '**',
        loadComponent: () =>
          import('./pages/not-found.component').then((m) => m.NotFoundComponent),
      },
    ],
  },
];
