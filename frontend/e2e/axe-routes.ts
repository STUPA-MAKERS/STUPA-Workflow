/**
 * Every route of the app for the axe sweep (§ NF/accessibility/conformance/000491).
 *
 * `path` is the route path as `app.routes.ts` writes it, so the jest contract
 * `src/app/axe-routes.contract.spec.ts` can prove that each route is here. A `:param` takes
 * the id of an item that the sweep creates in its setup (`Ids`), or the fixed id `MISSING`
 * when the stack cannot make the item: the page then shows its not-found state, which is a
 * state of the page too. `public` routes run without the admin session.
 */
export interface Ids {
  application: string;
  meeting: string;
  gremium: string;
  ticket: string;
  board: string;
  card: string;
  form: string;
}

/** An id that no item has. */
export const MISSING = '00000000-0000-4000-8000-000000000000';

export interface AxeRoute {
  path: string;
  url: (ids: Ids) => string;
  public?: boolean;
}

const fixed = (path: string, extra: Partial<AxeRoute> = {}): AxeRoute => ({ path, url: () => `/${path}`, ...extra });

export const AXE_ROUTES: readonly AxeRoute[] = [
  fixed('', { public: true }),
  fixed('apply', { public: true }),
  fixed('apply/confirmation', { public: true }),
  fixed('login', { public: true }),
  fixed('my-applications', { public: true }),
  fixed('stop-observing', { public: true }),
  { path: 'my-applications/:id', url: () => `/my-applications/${MISSING}`, public: true },
  fixed('protocols', { public: true }),
  fixed('public-calendar', { public: true }),
  { path: 'protocols/:id', url: () => `/protocols/${MISSING}`, public: true },
  { path: 'j/:code', url: () => '/j/ZZZZZZ', public: true },
  fixed('accessibility', { public: true }),
  fixed('dashboard'),
  fixed('applications'),
  { path: 'applications/:id', url: (ids) => `/applications/${ids.application}` },
  fixed('tasks'),
  { path: 'tasks/todo/:cardId', url: (ids) => `/tasks/todo/${ids.card}` },
  { path: 'tasks/:id', url: (ids) => `/tasks/${ids.application}` },
  fixed('voting/projector'),
  { path: 'voting/projector/:id', url: () => `/voting/projector/${MISSING}` },
  fixed('voting'),
  { path: 'voting/:id', url: () => `/voting/${MISSING}` },
  fixed('meetings'),
  fixed('calendar'),
  { path: 'meetings/:id', url: (ids) => `/meetings/${ids.meeting}` },
  fixed('committees'),
  { path: 'committees/:id', url: (ids) => `/committees/${ids.gremium}` },
  fixed('budget'),
  fixed('expenses'),
  fixed('invoices'),
  fixed('tickets'),
  { path: 'tickets/:id', url: (ids) => `/tickets/${ids.ticket}` },
  fixed('todos'),
  { path: 'todos/:boardId', url: (ids) => `/todos/${ids.board}` },
  fixed('admin'),
  fixed('admin/cost-centres'),
  fixed('admin/users'),
  fixed('admin/roles'),
  fixed('admin/group-mappings'),
  fixed('admin/mail-templates'),
  fixed('admin/forms'),
  { path: 'admin/forms/:id', url: (ids) => `/admin/forms/${ids.form}` },
  fixed('admin/flow'),
  fixed('admin/backups'),
  fixed('admin/login-settings'),
  fixed('admin/privacy'),
  fixed('admin/committees'),
  { path: 'admin/committees/:id/members', url: (ids) => `/admin/committees/${ids.gremium}/members` },
  { path: 'admin/committees/:id/roles', url: (ids) => `/admin/committees/${ids.gremium}/roles` },
  fixed('admin/branding'),
  fixed('admin/texts'),
  fixed('admin/translations'),
  fixed('admin/cd-variants'),
  fixed('admin/calendars'),
  fixed('admin/webhooks'),
  fixed('admin/help-tickets'),
  fixed('admin/features'),
  fixed('admin/oauth-grants'),
  fixed('admin/audit'),
  fixed('admin/delegations'),
  fixed('admin/deadlines'),
  fixed('admin/notifications'),
  { path: 'oauth/consent', url: () => '/oauth/consent?client_id=missing' },
  fixed('account'),
  fixed('account/notifications'),
  fixed('account/grants'),
  fixed('forbidden'),
  { path: '**', url: () => '/gibt-es-nicht', public: true },
];
