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
        data: { title: 'nav.applications', permission: 'application.read' },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/applications/applications-list.component').then(
            (m) => m.ApplicationsListComponent,
          ),
      },
      {
        path: 'applications/:id',
        data: { title: 'nav.applications', permission: 'application.read' },
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
        data: { title: 'nav.meetings', permission: ['meeting.manage', 'protocol.write'] },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./features/meetings/meetings.component').then((m) => m.MeetingsComponent),
      },
      {
        path: 'budget',
        data: { title: 'nav.budget', permission: ['budget.view', 'budget.manage'] },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/budget/budget-dashboard.component').then(
            (m) => m.BudgetDashboardComponent,
          ),
      },
      {
        path: 'budget/pots',
        data: { title: 'budget.pots.title', permission: 'budget.manage' },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/budget/budget-pots.component').then((m) => m.BudgetPotsComponent),
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
        data: { title: 'admin.users.title', permission: 'admin.roles' },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/admin/users/users.component').then((m) => m.UsersComponent),
      },
      {
        path: 'admin/forms',
        data: { title: 'admin.form.title', permission: 'form.configure' },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/admin/form-builder/form-builder.component').then(
            (m) => m.FormBuilderComponent,
          ),
      },
      {
        path: 'admin/flow',
        data: { title: 'admin.flow.title', permission: 'flow.configure' },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/admin/flow-editor/flow-editor.component').then(
            (m) => m.FlowEditorComponent,
          ),
      },
      {
        path: 'admin/branding',
        data: { title: 'admin.brand.title', permission: 'admin.config' },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/admin/branding/branding-editor.component').then(
            (m) => m.BrandingEditorComponent,
          ),
      },
      {
        path: 'admin/webhooks',
        data: { title: 'admin.webhook.title', permission: 'webhook.manage' },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/admin/config/webhooks.component').then((m) => m.WebhooksComponent),
      },
      {
        path: 'admin/notifications',
        data: { title: 'admin.notif.title', permission: 'notification.manage' },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/admin/config/notification-rules.component').then(
            (m) => m.NotificationRulesComponent,
          ),
      },
      {
        path: 'admin/delegations',
        data: { title: 'admin.deleg.title', permission: 'admin.roles' },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/admin/delegations/delegations.component').then(
            (m) => m.DelegationsComponent,
          ),
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
