import type { Routes } from '@angular/router';
import { authGuard } from '@core/auth/auth.guard';
import { homeRedirectGuard } from '@core/auth/home-redirect.guard';
import { ShellComponent } from './layout/shell.component';

/**
 * Routing skeleton. `authGuard` protects the OIDC areas. Some areas also need an RBAC
 * permission (`data.permission`).
 */
export const routes: Routes = [
  {
    path: '',
    component: ShellComponent,
    children: [
      {
        path: '',
        // An authenticated user goes to /dashboard. Only an applicant sees the public
        // landing page.
        canActivate: [homeRedirectGuard],
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
        // Magic-link target: {public_base_url}/antrag/{id}#t={token}. The route is public
        // and uses an applicant token instead of a login. The component resolves the
        // fragment and :id.
        path: 'antrag/:id',
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
        // No permission gate: without `application.read` you see only your own
        // applications. The server filters on `created_by`.
        data: { title: 'nav.applications', wide: true },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/applications/applications-list.component').then(
            (m) => m.ApplicationsListComponent,
          ),
      },
      {
        path: 'tasks',
        // No permission gate: the tab shows at least your own applications in an editable
        // state.
        data: { title: 'nav.tasks' },
        canActivate: [authGuard],
        loadComponent: () => import('./pages/tasks/tasks.component').then((m) => m.TasksComponent),
      },
      {
        path: 'applications/:id',
        // No permission gate: a creator can reach their own application. The server
        // authorizes through `application.read`, owner, or magic-link.
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
        // Read-only beamer view for the projector. Declared before `vote/:id`.
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
        // A delegation recipient can reach the ballot without vote.cast. The server
        // decides the voting rights with the delegation check.
        data: {
          title: 'voting.cast.heading',
          permission: ['vote.cast', 'vote.manage'],
          allowAuthenticated: true,
        },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./features/voting/vote-cast.component').then((m) => m.VoteCastComponent),
      },
      {
        path: 'meetings',
        // A Gremium member reaches their own meetings without meeting.manage.
        // `protocol.write` is gremium-scoped and can never match here (#g10).
        data: {
          title: 'nav.meetings',
          permission: ['meeting.manage'],
          allowCommitteeMember: true,
        },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./features/meetings/meetings.component').then((m) => m.MeetingsComponent),
      },
      {
        path: 'meetings/:id',
        // `allowAuthenticated`: a delegation recipient is neither a member nor
        // permitted; the server scopes the meeting view (#g10).
        data: {
          title: 'meetings.detailCrumb',
          parent: ['meetings'],
          permission: ['meeting.manage'],
          allowCommitteeMember: true,
          allowAuthenticated: true,
          wide: true,
        },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./features/meetings/meetings.component').then((m) => m.MeetingsComponent),
      },
      {
        path: 'budget',
        // A Gremium with an assigned cost center sees a scoped tab.
        data: { title: 'nav.budget', permission: ['budget.view', 'budget.structure', 'budget.book'], allowScopedBudgetView: true, wide: true },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/budget/budget-dashboard.component').then(
            (m) => m.BudgetDashboardComponent,
          ),
      },
      {
        path: 'expenses',
        data: { title: 'nav.expenses', permission: ['budget.view', 'budget.structure', 'budget.book'], wide: true },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/expenses/expenses.component').then((m) => m.ExpensesComponent),
      },
      {
        path: 'invoices',
        // Narrow body like the tasks tab: no `wide` keeps the default container width.
        data: { title: 'nav.invoices', permission: ['budget.view', 'budget.structure', 'budget.book'] },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/invoices/invoices.component').then((m) => m.InvoicesComponent),
      },
      {
        path: 'admin/budget-pots',
        data: { title: 'budget.tree.title', permission: 'budget.structure', parent: ['admin'], wide: true },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/budget/budget-tree.component').then((m) => m.BudgetTreeComponent),
      },
      {
        path: 'admin',
        data: {
          title: 'nav.admin',
          // Every area-admin role can reach the admin overview.
          permission: ['admin.site', 'admin.gremien', 'admin.types', 'admin.roles', 'admin.users', 'admin.group_mappings', 'admin.gremium_roles', 'admin.cd_variants', 'admin.delegations', 'admin.deadlines', 'admin.notifications', 'privacy.manage', 'webhook.manage', 'audit.read'],
        },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/admin/admin-home.component').then((m) => m.AdminHomeComponent),
      },
      {
        path: 'admin/users',
        data: { title: 'admin.users.title', permission: 'admin.users', parent: ['admin'] },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/admin/users/users.component').then((m) => m.UsersComponent),
      },
      {
        path: 'admin/roles',
        data: { title: 'admin.roles.title', permission: 'admin.roles', parent: ['admin'] },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/admin/roles/roles.component').then((m) => m.AdminRolesComponent),
      },
      {
        // Maps an OIDC group to a role.
        path: 'admin/group-mappings',
        data: { title: 'admin.groupMappings.title', permission: 'admin.group_mappings', parent: ['admin'] },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/admin/group-mappings/group-mappings.component').then(
            (m) => m.GroupMappingsComponent,
          ),
      },
      {
        path: 'admin/mail-templates',
        data: { title: 'admin.mailTemplates.title', permission: 'admin.notifications', parent: ['admin'] },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/admin/mail-templates/mail-templates.component').then(
            (m) => m.MailTemplatesComponent,
          ),
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
        data: { title: 'admin.flow.title', permission: 'admin.types', parent: ['admin'] },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/admin/flow-editor/flow-editor.component').then(
            (m) => m.FlowEditorComponent,
          ),
      },
      {
        path: 'admin/privacy',
        data: { title: 'admin.privacy.title', permission: 'privacy.manage', parent: ['admin'] },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/admin/privacy/privacy.component').then(
            (m) => m.PrivacyComponent,
          ),
      },
      {
        path: 'admin/gremien',
        data: { title: 'admin.gremien.title', permission: 'admin.gremien', parent: ['admin'] },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/admin/gremien/gremien.component').then((m) => m.AdminGremienComponent),
      },
      {
        path: 'admin/gremien/:id/members',
        data: { title: 'admin.gremien.membersOf', permission: 'admin.gremien', parent: ['admin', 'admin/gremien'] },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/admin/gremien/gremium-members.component').then(
            (m) => m.GremiumMembersComponent,
          ),
      },
      {
        path: 'admin/branding',
        data: { title: 'admin.brand.title', permission: 'admin.site', parent: ['admin'] },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/admin/branding/branding-editor.component').then(
            (m) => m.BrandingEditorComponent,
          ),
      },
      {
        path: 'admin/cd-variants',
        data: { title: 'admin.cdVariants.title', permission: 'admin.cd_variants', parent: ['admin'] },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/admin/cd-variants/cd-variants.component').then(
            (m) => m.AdminCdVariantsComponent,
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
        data: { title: 'admin.gremiumRoles.title', permission: 'admin.gremium_roles', parent: ['admin', 'admin/gremien'] },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/admin/gremium-roles/gremium-roles.component').then(
            (m) => m.GremiumRolesComponent,
          ),
      },
      {
        path: 'admin/oauth-grants',
        data: {
          title: 'admin.oauthGrants.title',
          permission: 'admin.users',
          parent: ['admin'],
        },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/admin/oauth-grants/oauth-grants.component').then(
            (m) => m.AdminOAuthGrantsComponent,
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
        data: { title: 'admin.deleg.title', permission: 'admin.delegations', parent: ['admin'] },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/admin/delegations/delegations.component').then(
            (m) => m.DelegationsComponent,
          ),
      },
      {
        path: 'admin/deadlines',
        data: { title: 'admin.deadlines.title', permission: 'admin.deadlines', parent: ['admin'] },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/admin/deadlines/deadlines.component').then(
            (m) => m.AdminDeadlinesComponent,
          ),
      },
      {
        // Platform-wide notification settings, such as the task reminders.
        path: 'admin/notifications',
        data: {
          title: 'admin.notifications.title',
          permission: 'admin.notifications',
          parent: ['admin'],
        },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/admin/notifications/notification-settings.component').then(
            (m) => m.NotificationSettingsComponent,
          ),
      },
      {
        // OAuth consent: after the login the user picks the scope and the token lifetime.
        path: 'oauth/consent',
        data: { title: 'account.consent.title' },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/account/consent.component').then((m) => m.OAuthConsentComponent),
      },
      {
        // API access: manage your own OAuth grants and download the MCP package.
        path: 'account/grants',
        data: { title: 'account.grants.title' },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/account/grants.component').then((m) => m.AccountGrantsComponent),
      },
      {
        // Your own mail switches. Each switch is an opt-out.
        path: 'account/notifications',
        data: { title: 'account.notifications.title' },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/account/notifications.component').then(
            (m) => m.AccountNotificationsComponent,
          ),
      },
      {
        // Calendar subscription: the personal iCal feed URL for your meetings.
        path: 'account/calendar',
        data: { title: 'account.calendar.title' },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/account/calendar.component').then((m) => m.AccountCalendarComponent),
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
