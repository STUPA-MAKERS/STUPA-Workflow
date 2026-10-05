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
 * shell (no rail, no bars, no footer), for the beamer.
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
        // `contextual`: this page only means something right after a submission. Opened
        // cold it tells the reader to check their mail for an application nobody sent.
        data: { title: 'apply.confirm.heading', contextual: true },
        loadComponent: () =>
          import('./features/apply/apply-confirmation.component').then(
            (m) => m.ApplyConfirmationComponent,
          ),
      },
      {
        path: 'status',
        // `contextual`: without an application id this renders "Antrag nicht gefunden".
        // The id arrives from the magic link, never from navigating here.
        data: { title: 'status.heading', contextual: true },
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
        // Wide: the two columns of the start page fill the width (board Main).
        // Fab: on a phone the shell keeps the foot of the page free for the "Antrag" button.
        data: { title: 'nav.dashboard', wide: true, fab: true },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/dashboard/dashboard.component').then((m) => m.DashboardComponent),
      },
      {
        path: 'applications',
        // No permission gate: without `application.read` you see only your own
        // applications. The server filters on `created_by`.
        //
        // The list and the detail share one page: the list pane stays while the detail of
        // `:id` loads in its outlet (board Anträge). A deep link to `/applications/:id`
        // opens the page with that application, also for its owner.
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
            // No permission gate: a creator can reach their own application. The server
            // authorizes through `application.read`, owner, or magic-link.
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
        // No permission gate: the tab shows at least your own applications in an editable
        // state.
        data: { title: 'nav.tasks', wide: true },
        canActivate: [authGuard],
        loadComponent: () => import('./pages/tasks/tasks.component').then((m) => m.TasksComponent),
      },
      {
        path: 'voting',
        // Voting rights are GREMIUM rights. No global permission grants them, so the
        // gate goes through `gremiumPermission` (any gremium, or the admin role).
        data: { title: 'nav.voting', gremiumPermission: VOTING_GREMIUM_PERMISSIONS },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./features/voting/live-vote.component').then((m) => m.LiveVoteComponent),
      },
      {
        // Read-only beamer view for the projector. Declared before `vote/:id`.
        path: 'voting/beamer',
        // The beamer WebSocket needs `session.manage` in the gremium of the meeting.
        // `chrome: false`: the projector shows the page without rail, bars or footer.
        data: { title: 'voting.beamer.heading', gremiumPermission: 'session.manage', chrome: false },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./features/voting/beamer.component').then((m) => m.BeamerComponent),
      },
      {
        path: 'voting/beamer/:id',
        data: { title: 'voting.beamer.heading', gremiumPermission: 'session.manage', chrome: false },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./features/voting/beamer.component').then((m) => m.BeamerComponent),
      },
      {
        path: 'voting/meeting/:id',
        data: { title: 'nav.voting', gremiumPermission: VOTING_GREMIUM_PERMISSIONS },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./features/voting/live-vote.component').then((m) => m.LiveVoteComponent),
      },
      {
        path: 'voting/vote/:id',
        // A delegation recipient can reach the ballot without vote.cast, and a reader
        // with `application.read` can view a standalone vote. The server decides the
        // rights and reports them as `canCast` and `canManage` on the vote.
        data: {
          title: 'voting.cast.heading',
          gremiumPermission: VOTING_GREMIUM_PERMISSIONS,
          allowAuthenticated: true,
        },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./features/voting/vote-cast.component').then((m) => m.VoteCastComponent),
      },
      {
        path: 'meetings',
        // A Gremium member can reach their own meetings without session.manage.
        // `session.manage` is a GREMIUM-role permission, so it goes through
        // `gremiumPermission` and never through the global `permission` list.
        // `meeting.view_all` is the global read right: the server shows its holder
        // the meetings of every Gremium, also without a membership.
        data: {
          title: 'nav.meetings',
          permission: ['meeting.view_all'],
          gremiumPermission: ['session.manage'],
          allowCommitteeMember: true,
        },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./features/meetings/meetings.component').then((m) => m.MeetingsComponent),
      },
      {
        path: 'meetings/:id',
        // `allowAuthenticated`: a delegation recipient can be neither a member nor
        // permitted. The server scopes the meeting view.
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
        path: 'budget',
        // A Gremium with an assigned cost center sees a scoped tab.
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
        // Full width, as on the board: up to eleven columns.
        data: { title: 'nav.invoices', permission: BUDGET_PERMISSIONS, wide: true },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/invoices/invoices.component').then((m) => m.InvoicesComponent),
      },
      {
        // The admin frame (board Verwaltung): the admin navigation beside every admin
        // page. The frame itself needs only a session; each page below keeps its own
        // permission gate. `wide`: the navigation and the page fill the width.
        path: 'admin',
        data: { wide: true },
        canActivate: [authGuard],
        loadComponent: () =>
          import('./pages/admin/admin-frame/admin-frame.component').then(
            (m) => m.AdminFrameComponent,
          ),
        children: [
          {
            path: 'cost-centres',
            data: { title: 'budget.tree.title', permission: 'budget.structure', parent: ['admin'], wide: true },
            canActivate: [authGuard],
            loadComponent: () =>
              import('./pages/budget/budget-tree.component').then((m) => m.BudgetTreeComponent),
          },
          // The page was called budget-pots while the pot feature existed. Bookmarks and
          // shared links from that time still work.
          { path: 'budget-pots', redirectTo: 'cost-centres', pathMatch: 'full' },
          {
            path: '',
            pathMatch: 'full',
            data: {
              title: 'nav.admin',
              // Every area-admin role can reach the admin overview.
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
            // Maps an OIDC group to a role.
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
            data: { title: 'admin.forms.edit', permission: 'form.configure', parent: ['admin', 'admin/forms'] },
            canActivate: [authGuard],
            loadComponent: () =>
              import('./pages/admin/forms/form-editor.component').then((m) => m.FormEditorComponent),
          },
          {
            path: 'flow',
            // The save (POST /admin/flow-versions/global) accepts either key. The route
            // gate must list both, or a holder of one of them opens an editor it cannot
            // save, or cannot open an editor it may save.
            data: {
              title: 'admin.flow.title',
              permission: ['flow.configure', 'admin.types'],
              parent: ['admin'],
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
            data: { title: 'admin.brand.title', permission: 'admin.site', parent: ['admin'] },
            canActivate: [authGuard],
            loadComponent: () =>
              import('./pages/admin/branding/branding-editor.component').then(
                (m) => m.BrandingEditorComponent,
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
            path: 'gremien/:id/roles',
            data: { title: 'admin.gremiumRoles.title', permission: 'admin.gremium_roles', parent: ['admin', 'admin/gremien'] },
            canActivate: [authGuard],
            loadComponent: () =>
              import('./pages/admin/gremium-roles/gremium-roles.component').then(
                (m) => m.GremiumRolesComponent,
              ),
          },
          {
            // Agent tokens (OAuth grants) of every principal, with a kill switch.
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
            // Platform-wide notification settings, such as the task reminders.
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
