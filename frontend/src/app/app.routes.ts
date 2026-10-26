import type { Routes } from '@angular/router';
import { authGuard } from '@core/auth/auth.guard';
import { homeRedirectGuard } from '@core/auth/home-redirect.guard';
import { ShellComponent } from './layout/shell.component';
import {
  ADMIN_AREA_PERMISSIONS,
  BUDGET_PERMISSIONS,
  VOTING_GREMIUM_PERMISSIONS,
} from './layout/nav.service';

/**
 * Routing skeleton. `authGuard` protects the OIDC areas. Some areas also need an RBAC
 * permission: a global one (`data.permission`) or a gremium one in any gremium
 * (`data.gremiumPermission`). `data.chrome: false` shows the page without the frame of the
 * shell (no rail, no bars, no footer), for the beamer. `data.footer: true` shows the
 * branded footer below a page of the signed-in frame: only the public pages have it (the
 * public frame shows it always).
 *
 * The beamer route comes before `voting`, because the child `:id` of `voting` would match
 * `beamer` too. Gremium rights (`session.manage`, `vote.cast`) go through
 * `gremiumPermission`, never through the global `permission` list. The votes guard runs per
 * child, because `:id` admits more people than the list, and the list stays open to them,
 * or the way back from a vote ends on /forbidden. A route without a gate (applications,
 * tasks, the meetings of a delegation recipient) relies on the server, which filters by
 * owner and scope. The flow
 * editor lists both permission keys, because the save accepts either. The `frame` mode is
 * route data, because route data wins over a `?frame=` query parameter in the input
 * binding. The redirects keep old bookmarks and shared links working.
 */
export const routes: Routes = [
  {
    path: '',
    component: ShellComponent,
    children: [
      {
        path: '',
        canActivate: [homeRedirectGuard],
        data: { footer: true },
        loadComponent: () => import('./pages/home.component').then((m) => m.HomeComponent),
      },
      {
        path: 'apply',
        data: { title: 'apply.title', footer: true },
        loadComponent: () =>
          import('./features/apply/apply-wizard.component').then((m) => m.ApplyWizardComponent),
      },
      {
        path: 'apply/confirmation',
        data: { title: 'apply.confirm.heading', contextual: true, footer: true },
        loadComponent: () =>
          import('./features/apply/apply-confirmation.component').then(
            (m) => m.ApplyConfirmationComponent,
          ),
      },
      {
        path: 'status',
        data: { title: 'status.heading', contextual: true, footer: true },
        loadComponent: () =>
          import('./features/apply/status-timeline.component').then(
            (m) => m.StatusTimelineComponent,
          ),
      },
      {
        path: 'antrag/:id',
        data: { title: 'status.heading', footer: true },
        loadComponent: () =>
          import('./features/apply/status-timeline.component').then(
            (m) => m.StatusTimelineComponent,
          ),
      },
      {
        path: 'protokolle',
        data: { title: 'publicProtocols.title', footer: true },
        loadComponent: () =>
          import('./features/public-protocols/public-protocols.component').then(
            (m) => m.PublicProtocolsComponent,
          ),
      },
      {
        path: 'protokolle/:id',
        data: { title: 'publicProtocols.title', footer: true },
        loadComponent: () =>
          import('./features/public-protocols/public-protocol-detail.component').then(
            (m) => m.PublicProtocolDetailComponent,
          ),
      },
      {
        path: 'j/:code',
        data: { title: 'guests.page.routeTitle', chrome: false },
        loadComponent: () =>
          import('./features/public-meeting/public-meeting.component').then(
            (m) => m.PublicMeetingComponent,
          ),
      },
      {
        path: 'dashboard',
        data: { title: 'nav.dashboard', wide: true, fab: true },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/dashboard/dashboard.component').then((m) => m.DashboardComponent),
      },
      {
        path: 'applications',
        data: { title: 'nav.applications', wide: true },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/applications/applications-list.component').then(
            (m) => m.ApplicationsListComponent,
          ),
        children: [
          {
            path: '',
            data: { fab: true },
            loadComponent: () =>
              import('./pages/applications/applications-none.component').then(
                (m) => m.ApplicationsNoneComponent,
              ),
          },
          {
            path: ':id',
            data: { title: 'applications.detail.crumb', parent: ['applications'] },
            loadComponent: () =>
              import('./pages/applications/applications-detail.component').then(
                (m) => m.ApplicationsDetailComponent,
              ),
          },
        ],
      },
      {
        path: 'tasks',
        data: { title: 'nav.tasks', wide: true },
        canActivate: [authGuard],
        loadComponent: () => import('./pages/tasks/tasks.component').then((m) => m.TasksComponent),
        children: [
          {
            path: '',
            loadComponent: () =>
              import('./pages/tasks/tasks-none.component').then((m) => m.TasksNoneComponent),
          },
          {
            path: 'todo/:cardId',
            data: { title: 'todos.card.kicker', parent: ['tasks'] },
            loadComponent: () =>
              import('./pages/tasks/task-todo.component').then((m) => m.TaskTodoComponent),
          },
          {
            path: ':id',
            data: { title: 'applications.detail.crumb', parent: ['tasks'] },
            loadComponent: () =>
              import('./pages/applications/applications-detail.component').then(
                (m) => m.ApplicationsDetailComponent,
              ),
          },
        ],
      },
      {
        path: 'voting/beamer',
        data: { title: 'beamer.title', gremiumPermission: 'session.manage', chrome: false },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./features/voting/beamer.component').then((m) => m.BeamerComponent),
      },
      {
        path: 'voting/beamer/:id',
        data: { title: 'beamer.title', gremiumPermission: 'session.manage', chrome: false },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./features/voting/beamer.component').then((m) => m.BeamerComponent),
      },
      { path: 'voting/vote/:id', redirectTo: 'voting/:id' },
      { path: 'voting/meeting/:id', redirectTo: 'voting' },
      {
        path: 'voting',
        data: { title: 'nav.voting', gremiumPermission: VOTING_GREMIUM_PERMISSIONS, wide: true },
        canActivateChild: [authGuard],
        loadComponent: () =>
          import('./features/voting/voting-page/voting.component').then((m) => m.VotingComponent),
        children: [
          {
            path: '',
            data: { allowAuthenticated: true },
            loadComponent: () =>
              import('./features/voting/voting-page/voting-none.component').then(
                (m) => m.VotingNoneComponent,
              ),
          },
          {
            path: ':id',
            data: {
              title: 'voting.cast.heading',
              parent: ['voting'],
              gremiumPermission: VOTING_GREMIUM_PERMISSIONS,
              allowAuthenticated: true,
            },
            loadComponent: () =>
              import('./features/voting/vote-cast.component').then((m) => m.VoteCastComponent),
          },
        ],
      },
      {
        path: 'meetings',
        data: {
          title: 'nav.meetings',
          permission: ['meeting.view_all'],
          gremiumPermission: ['session.manage'],
          allowCommitteeMember: true,
          wide: true,
        },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./features/meetings/meetings.component').then((m) => m.MeetingsComponent),
      },
      {
        path: 'meetings/:id',
        data: {
          title: 'meetings.detailCrumb',
          parent: ['meetings'],
          permission: ['meeting.view_all'],
          gremiumPermission: ['session.manage'],
          allowCommitteeMember: true,
          allowAuthenticated: true,
          wide: true,
        },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./features/meetings/meetings.component').then((m) => m.MeetingsComponent),
      },
      {
        path: 'gremien',
        data: {
          title: 'nav.gremien',
          permission: ['gremium.view_all'],
          allowCommitteeMember: true,
          wide: true,
        },
        canActivateChild: [authGuard],
        loadComponent: () =>
          import('./features/gremien/gremien-page/gremien.component').then((m) => m.GremienComponent),
        children: [
          {
            path: '',
            data: { permission: ['gremium.view_all'], allowCommitteeMember: true },
            loadComponent: () =>
              import('./features/gremien/gremien-none/gremien-none.component').then(
                (m) => m.GremienNoneComponent,
              ),
          },
          {
            path: ':id',
            data: {
              title: 'gremien.title',
              parent: ['gremien'],
              permission: ['gremium.view_all'],
              allowCommitteeMember: true,
            },
            loadComponent: () =>
              import('./features/gremien/gremium-detail/gremium-detail.component').then(
                (m) => m.GremiumDetailComponent,
              ),
          },
        ],
      },
      {
        path: 'budget',
        data: { title: 'nav.budget', permission: BUDGET_PERMISSIONS, allowScopedBudgetView: true, wide: true },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/budget/budget-dashboard.component').then(
            (m) => m.BudgetDashboardComponent,
          ),
      },
      {
        path: 'expenses',
        data: { title: 'nav.expenses', permission: BUDGET_PERMISSIONS, wide: true },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/expenses/expenses.component').then((m) => m.ExpensesComponent),
      },
      {
        path: 'invoices',
        data: { title: 'nav.invoices', permission: BUDGET_PERMISSIONS, wide: true },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/invoices/invoices.component').then((m) => m.InvoicesComponent),
      },
      {
        path: 'tickets',
        data: { title: 'nav.tickets', permission: 'ticket.manage', allowReporter: true, wide: true },
        canActivate: [authGuard],
        loadComponent: () => import('./pages/tickets/tickets.component').then((m) => m.TicketsComponent),
        children: [
          {
            path: '',
            loadComponent: () =>
              import('./pages/tickets/tickets-none.component').then((m) => m.TicketsNoneComponent),
          },
          {
            path: ':id',
            data: { title: 'tickets.detail.crumb', parent: ['tickets'] },
            loadComponent: () =>
              import('./pages/tickets/ticket-detail.component').then((m) => m.TicketDetailComponent),
          },
        ],
      },
      {
        path: 'todos',
        data: { title: 'nav.todos', wide: true },
        canActivate: [authGuard],
        loadComponent: () => import('./pages/todos/todos.component').then((m) => m.TodosComponent),
      },
      {
        path: 'todos/:boardId',
        data: { title: 'nav.todos', wide: true },
        canActivate: [authGuard],
        loadComponent: () => import('./pages/todos/todos.component').then((m) => m.TodosComponent),
      },
      {
        path: 'admin',
        data: { wide: true, frame: 'admin' },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/admin/admin-frame/admin-frame.component').then(
            (m) => m.AdminFrameComponent,
          ),
        children: [
          {
            path: 'cost-centres',
            data: {
              title: 'budget.tree.title',
              permission: 'budget.structure',
              parent: ['admin'],
              wide: true,
            },
            canActivate: [authGuard],
            loadComponent: () =>
              import('./pages/budget/budget-tree.component').then((m) => m.BudgetTreeComponent),
          },
          { path: 'budget-pots', redirectTo: 'cost-centres', pathMatch: 'full' },
          {
            path: '',
            pathMatch: 'full',
            data: {
              title: 'nav.admin',
              permission: ADMIN_AREA_PERMISSIONS,
            },
            canActivate: [authGuard],
            loadComponent: () =>
              import('./pages/admin/admin-home.component').then((m) => m.AdminHomeComponent),
          },
          {
            path: 'users',
            data: { title: 'admin.users.title', permission: 'admin.users', parent: ['admin'] },
            canActivate: [authGuard],
            loadComponent: () =>
              import('./pages/admin/users/users.component').then((m) => m.UsersComponent),
          },
          {
            path: 'roles',
            data: { title: 'admin.roles.title', permission: 'admin.roles', parent: ['admin'] },
            canActivate: [authGuard],
            loadComponent: () =>
              import('./pages/admin/roles/roles.component').then((m) => m.AdminRolesComponent),
          },
          {
            path: 'group-mappings',
            data: { title: 'admin.groupMappings.title', permission: 'admin.group_mappings', parent: ['admin'] },
            canActivate: [authGuard],
            loadComponent: () =>
              import('./pages/admin/group-mappings/group-mappings.component').then(
                (m) => m.GroupMappingsComponent,
              ),
          },
          {
            path: 'mail-templates',
            data: { title: 'admin.mailTemplates.title', permission: 'admin.notifications', parent: ['admin'] },
            canActivate: [authGuard],
            loadComponent: () =>
              import('./pages/admin/mail-templates/mail-templates.component').then(
                (m) => m.MailTemplatesComponent,
              ),
          },
          {
            path: 'forms',
            data: { title: 'admin.forms.listTitle', permission: 'form.configure', parent: ['admin'] },
            canActivate: [authGuard],
            loadComponent: () =>
              import('./pages/admin/forms/forms-list.component').then((m) => m.FormsListComponent),
          },
          {
            path: 'forms/:id',
            data: {
              title: 'admin.forms.edit',
              permission: 'form.configure',
              parent: ['admin', 'admin/forms'],
              adminNav: false,
              adminPane: true,
            },
            canActivate: [authGuard],
            loadComponent: () =>
              import('./pages/admin/forms/form-editor.component').then((m) => m.FormEditorComponent),
          },
          {
            path: 'flow',
            data: {
              title: 'admin.flow.title',
              permission: ['flow.configure', 'admin.types'],
              parent: ['admin'],
              adminNav: false,
              adminPane: true,
            },
            canActivate: [authGuard],
            loadComponent: () =>
              import('./pages/admin/flow-editor/flow-editor.component').then(
                (m) => m.FlowEditorComponent,
              ),
          },
          {
            path: 'backups',
            data: { title: 'admin.backups.title', permission: 'backup.manage', parent: ['admin'] },
            canActivate: [authGuard],
            loadComponent: () =>
              import('./pages/admin/backups/backups.component').then(
                (m) => m.BackupsComponent,
              ),
          },
          {
            path: 'login-settings',
            data: { title: 'admin.loginSettings.title', permission: 'admin.users', parent: ['admin'] },
            canActivate: [authGuard],
            loadComponent: () =>
              import('./pages/admin/login-settings/login-settings.component').then(
                (m) => m.LoginSettingsComponent,
              ),
          },
          {
            path: 'privacy',
            data: { title: 'admin.privacy.title', permission: 'privacy.manage', parent: ['admin'] },
            canActivate: [authGuard],
            loadComponent: () =>
              import('./pages/admin/privacy/privacy.component').then(
                (m) => m.PrivacyComponent,
              ),
          },
          {
            path: 'gremien',
            data: { title: 'admin.gremien.title', permission: 'admin.gremien', parent: ['admin'] },
            canActivate: [authGuard],
            loadComponent: () =>
              import('./pages/admin/gremien/gremien.component').then((m) => m.AdminGremienComponent),
          },
          {
            path: 'gremien/:id/members',
            data: { title: 'admin.gremien.membersOf', permission: 'admin.gremien', parent: ['admin', 'admin/gremien'] },
            canActivate: [authGuard],
            loadComponent: () =>
              import('./pages/admin/gremien/gremium-members.component').then(
                (m) => m.GremiumMembersComponent,
              ),
          },
          {
            path: 'branding',
            data: { title: 'admin.brand.title', permission: 'admin.site', parent: ['admin'], section: 'branding' },
            canActivate: [authGuard],
            loadComponent: () =>
              import('./pages/admin/branding/branding-editor.component').then(
                (m) => m.BrandingEditorComponent,
              ),
          },
          {
            path: 'texts',
            data: { title: 'admin.texts.title', permission: 'admin.site', parent: ['admin'], section: 'texts' },
            canActivate: [authGuard],
            loadComponent: () =>
              import('./pages/admin/branding/branding-editor.component').then(
                (m) => m.BrandingEditorComponent,
              ),
          },
          {
            path: 'translations',
            data: { title: 'admin.translations.title', permission: 'admin.translations', parent: ['admin'] },
            canActivate: [authGuard],
            loadComponent: () =>
              import('./pages/admin/translations/translations.component').then(
                (m) => m.AdminTranslationsComponent,
              ),
          },
          {
            path: 'cd-variants',
            data: { title: 'admin.cdVariants.title', permission: 'admin.cd_variants', parent: ['admin'] },
            canActivate: [authGuard],
            loadComponent: () =>
              import('./pages/admin/cd-variants/cd-variants.component').then(
                (m) => m.AdminCdVariantsComponent,
              ),
          },
          {
            path: 'webhooks',
            data: { title: 'admin.webhook.title', permission: 'webhook.manage', parent: ['admin'] },
            canActivate: [authGuard],
            loadComponent: () =>
              import('./pages/admin/config/webhooks.component').then((m) => m.WebhooksComponent),
          },
          {
            path: 'help-tickets',
            data: { title: 'admin.helpTickets.title', permission: ['admin.site', 'ticket.manage'], parent: ['admin'] },
            canActivate: [authGuard],
            loadComponent: () =>
              import('./pages/admin/help-tickets/help-tickets.component').then(
                (m) => m.HelpTicketsComponent,
              ),
          },
          {
            path: 'gremien/:id/roles',
            data: { title: 'admin.gremiumRoles.title', permission: 'admin.gremium_roles', parent: ['admin', 'admin/gremien'] },
            canActivate: [authGuard],
            loadComponent: () =>
              import('./pages/admin/gremium-roles/gremium-roles.component').then(
                (m) => m.GremiumRolesComponent,
              ),
          },
          {
            path: 'oauth-grants',
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
            path: 'audit',
            data: { title: 'admin.audit.title', permission: 'audit.read', parent: ['admin'] },
            canActivate: [authGuard],
            loadComponent: () =>
              import('./pages/admin/audit/audit-log.component').then((m) => m.AuditLogComponent),
          },
          {
            path: 'delegations',
            data: { title: 'admin.deleg.title', permission: 'admin.delegations', parent: ['admin'] },
            canActivate: [authGuard],
            loadComponent: () =>
              import('./pages/admin/delegations/delegations.component').then(
                (m) => m.DelegationsComponent,
              ),
          },
          {
            path: 'deadlines',
            data: { title: 'admin.deadlines.title', permission: 'admin.deadlines', parent: ['admin'] },
            canActivate: [authGuard],
            loadComponent: () =>
              import('./pages/admin/deadlines/deadlines.component').then(
                (m) => m.AdminDeadlinesComponent,
              ),
          },
          {
            path: 'notifications',
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
        ],
      },
      {
        path: 'oauth/consent',
        data: { title: 'account.consent.title' },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/account/consent.component').then((m) => m.OAuthConsentComponent),
      },
      {
        path: 'account',
        data: { wide: true, frame: 'account' },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/admin/admin-frame/admin-frame.component').then(
            (m) => m.AdminFrameComponent,
          ),
        children: [
          {
            path: '',
            pathMatch: 'full',
            data: { title: 'account.frame.title' },
            loadComponent: () =>
              import('./pages/account/account-none.component').then(
                (m) => m.AccountNoneComponent,
              ),
          },
          {
            path: 'notifications',
            data: { title: 'account.notifications.title' },
            loadComponent: () =>
              import('./pages/account/notifications.component').then(
                (m) => m.AccountNotificationsComponent,
              ),
          },
          {
            path: 'grants',
            data: { title: 'account.grants.title' },
            loadComponent: () =>
              import('./pages/account/grants.component').then((m) => m.AccountGrantsComponent),
          },
          {
            path: 'calendar',
            redirectTo: '/meetings',
            pathMatch: 'full',
          },
        ],
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
