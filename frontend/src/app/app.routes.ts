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
 * branded footer below a page of the signed-in frame: only the start page and the public
 * pages have it (the public frame shows it always).
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
        // `contextual`: this page only means something right after a submission. Opened
        // cold it tells the reader to check their mail for an application nobody sent.
        data: { title: 'apply.confirm.heading', contextual: true, footer: true },
        loadComponent: () =>
          import('./features/apply/apply-confirmation.component').then(
            (m) => m.ApplyConfirmationComponent,
          ),
      },
      {
        path: 'status',
        // `contextual`: without an application id this renders "Antrag nicht gefunden".
        // The id arrives from the magic link, never from navigating here.
        data: { title: 'status.heading', contextual: true, footer: true },
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
        data: { title: 'status.heading', footer: true },
        loadComponent: () =>
          import('./features/apply/status-timeline.component').then(
            (m) => m.StatusTimelineComponent,
          ),
      },
      {
        path: 'dashboard',
        // Wide: the two columns of the start page fill the width (board Main).
        // Fab: on a phone the shell keeps the foot of the page free for the "Antrag" button.
        // Footer: the start page is the only signed-in page with the branded footer.
        data: { title: 'nav.dashboard', wide: true, fab: true, footer: true },
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
        //
        // The same two panes as `applications`: the task list stays while the detail of
        // `:id` loads in its outlet. A deep link to `/tasks/:id` opens that task.
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
            path: ':id',
            // The detail of the applications page. The server authorizes the read.
            data: { title: 'applications.detail.crumb', parent: ['tasks'] },
            loadComponent: () =>
              import('./pages/applications/applications-detail.component').then(
                (m) => m.ApplicationsDetailComponent,
              ),
          },
        ],
      },
      {
        // Read-only beamer view for the projector. Declared before `voting`, whose child
        // `:id` would match `beamer` too.
        path: 'voting/beamer',
        // The beamer WebSocket needs `session.manage` in the gremium of the meeting.
        // `chrome: false`: the projector shows the page without rail, bars or footer.
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
      // The former paths of one vote and of the live page of a meeting. The list page
      // follows the running meetings itself and opens a vote that opens.
      { path: 'voting/vote/:id', redirectTo: 'voting/:id' },
      { path: 'voting/meeting/:id', redirectTo: 'voting' },
      {
        path: 'voting',
        // The list of the votes beside the open vote, like the applications and the
        // tasks: the list stays while the vote of `:id` loads in its outlet.
        //
        // Voting rights are GREMIUM rights. No global permission grants them, so the
        // gate goes through `gremiumPermission` (any gremium, or the admin role). The
        // guard runs per child (`canActivateChild`), because `:id` admits more people
        // than the list: see there.
        data: { title: 'nav.voting', gremiumPermission: VOTING_GREMIUM_PERMISSIONS, wide: true },
        canActivateChild: [authGuard],
        loadComponent: () =>
          import('./features/voting/voting-page/voting.component').then((m) => m.VotingComponent),
        children: [
          {
            path: '',
            // Every way back from a vote goes to this path: the phone back, "Zur Liste",
            // "Zur Übersicht" and the redirect after a delete. A person who can open a
            // vote (`:id`) must also come back to the list, else the guard sends them to
            // /forbidden. The server filters `GET /votes` by the read scope, and the
            // navigation entry stays gated.
            data: { allowAuthenticated: true },
            loadComponent: () =>
              import('./features/voting/voting-page/voting-none.component').then(
                (m) => m.VotingNoneComponent,
              ),
          },
          {
            path: ':id',
            // A delegation recipient can reach the ballot without vote.cast, and a reader
            // with `application.read` can view a standalone vote. The server decides the
            // rights and reports them as `canCast` and `canManage` on the vote; the list
            // beside it shows what the server lets the person read.
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
          // The overview is a list/detail or a calendar page over the full width.
          wide: true,
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
        // A list/detail page: the invoice list beside the detail of the open invoice.
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
            // `adminNav: 'xl'`: the cost-centre table with its eight columns fits beside
            // the admin navigation from 1440 px on (a sheet of 904 px, the table needs
            // 870 px). Below that the page takes the full width.
            data: {
              title: 'budget.tree.title',
              permission: 'budget.structure',
              parent: ['admin'],
              wide: true,
              adminNav: 'xl',
            },
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
            // `adminNav: false`: the editor fills the width, without the admin navigation
            // (board Admin-Formular-Editor).
            data: {
              title: 'admin.forms.edit',
              permission: 'form.configure',
              parent: ['admin', 'admin/forms'],
              adminNav: false,
            },
            canActivate: [authGuard],
            loadComponent: () =>
              import('./pages/admin/forms/form-editor.component').then((m) => m.FormEditorComponent),
          },
          {
            path: 'flow',
            // The save (POST /admin/flow-versions/global) accepts either key. The route
            // gate must list both, or a holder of one of them opens an editor it cannot
            // save, or cannot open an editor it may save.
            // `adminNav: false`: the canvas fills the width, without the admin navigation
            // (board Admin-Flow-Editor).
            data: {
              title: 'admin.flow.title',
              permission: ['flow.configure', 'admin.types'],
              parent: ['admin'],
              adminNav: false,
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
        // The calendar subscription is a popover of the meetings page now. Old links and
        // bookmarks of the former account page land there.
        path: 'account/calendar',
        redirectTo: '/meetings',
        pathMatch: 'full',
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
