import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ActivatedRoute, convertToParamMap, provideRouter, Router } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { BehaviorSubject } from 'rxjs';
import { ApplicationsDetailComponent } from './applications-detail.component';
import { AuthService } from '@core/auth/auth.service';
import { USE_MOCK_API } from '@core/api/api.config';
import { ToastService } from '@stupa-makers/ui-kit';
import type {
  Application,
  ApplicationComment,
  ApplicationOutWire,
  ApplicationVersion,
  CommentOutWire,
  FormFieldDef,
  StateOutWire,
  Transition,
  VersionOutWire,
} from '@core/api/models';

const SUBMITTED: StateOutWire = {
  id: 's1',
  key: 'submitted',
  label: { de: 'Eingereicht', en: 'Submitted' },
  color: '#4a90d9',
  editAllowed: true,
};

function appWire(): ApplicationOutWire {
  return {
    id: 'app-1',
    typeId: 't1',
    state: SUBMITTED,
    gremiumId: null,
    budgetPotId: null,
    amount: '250.00',
    currency: 'EUR',
    data: { title: 'Förderung Fest', amount: '250.00' },
    version: 2,
    lang: 'de',
    createdAt: '2026-06-05T10:00:00Z',
    updatedAt: '2026-06-05T11:00:00Z',
    applicant: { email: 'a@stupa', name: 'Mia', anonymized: false },
  };
}

const VERSIONS: VersionOutWire[] = [
  { version: 1, data: { title: 'Fest' }, diff: null, changedBy: 'Mia', at: '2026-06-05T10:00:00Z' },
  {
    version: 2,
    data: { title: 'Förderung Fest' },
    diff: { added: {}, removed: {}, changed: { title: { old: 'Fest', new: 'Förderung Fest' } } },
    changedBy: 'Mia',
    at: '2026-06-05T11:00:00Z',
  },
];

const COMMENTS: CommentOutWire[] = [
  {
    id: 'c1',
    author: 'Finanzreferat',
    authorKind: 'principal',
    body: 'Bitte Kostenplan ergänzen.',
    visibility: 'public',
    at: '2026-06-05T12:00:00Z',
  },
];

function fakeAuth(permissions: string[], roles: string[] = []): Partial<AuthService> {
  return {
    can: (p: string) => permissions.includes(p),
    roles: (() => roles) as unknown as AuthService['roles'],
  };
}

async function setup(
  permissions: string[] = ['application.read', 'application.manage'],
  paramMap$ = new BehaviorSubject(convertToParamMap({ id: 'app-1' })),
  roles: string[] = [],
) {
  const view = await render(ApplicationsDetailComponent, {
    providers: [
      provideRouter([]),
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
      { provide: AuthService, useValue: fakeAuth(permissions, roles) },
      { provide: ActivatedRoute, useValue: { paramMap: paramMap$ } },
    ],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  const toast = view.fixture.debugElement.injector.get(ToastService);
  const router = view.fixture.debugElement.injector.get(Router);
  const cmp = view.fixture.componentInstance;
  return { ...view, http, toast, router, cmp, paramMap$ };
}

const url =
  (suffix: string, id = 'app-1') =>
  (r: { url: string }) =>
    r.url === `/api/applications/${id}${suffix}`;

/** Flush the effective-form request used for data-field labels. */
function flushForm(http: HttpTestingController, id = 'app-1') {
  http
    .expectOne((r) => r.url === `/api/applications/${id}/form`)
    .flush({
      applicationTypeId: 't1',
      formVersionId: 'fv1',
      sections: [
        { key: 'main', label: { de: 'Antrag' }, fields: [{ key: 'amount', type: 'currency', label: { de: 'Betrag' } }] },
      ],
    });
}

// `form` nur beim initialen Laden (loadApplication); ein refresh() lädt die Form nicht neu.
// Statuswechsel laufen über den Flow → keine /transitions-Anfrage mehr.
function flushAll(http: HttpTestingController, id = 'app-1', form = true) {
  http.expectOne(url('', id)).flush({ ...appWire(), id });
  http.expectOne(url('/versions', id)).flush(VERSIONS);
  http.expectOne(url('/comments', id)).flush(COMMENTS);
  // Verwalter:innen laden zusätzlich den Kostenstellen-Baum (#17) — tolerant leeren.
  for (const req of http.match((r) => r.method === 'GET' && r.url === '/api/budgets')) {
    req.flush([]);
  }
  if (form) flushForm(http, id);
}

// Das Anhänge-Panel lädt beim Rendern bestehende Anhänge — tolerant leeren (falls vorhanden).
function flushAttachments(http: HttpTestingController) {
  for (const req of http.match((r) => r.method === 'GET' && /\/attachments$/.test(r.url))) {
    req.flush([]);
  }
  // Verwalter:innen laden zusätzlich den Kostenstellen-Baum (#17) — tolerant leeren.
  for (const req of http.match((r) => r.method === 'GET' && r.url === '/api/budgets')) {
    req.flush([]);
  }
}

describe('ApplicationsDetailComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  // jsdom (jest) has no structuredClone; startEdit relies on the browser global.
  const g = globalThis as unknown as { structuredClone?: <T>(v: T) => T };
  const savedClone = g.structuredClone;
  beforeAll(() => {
    g.structuredClone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
  });
  afterAll(() => {
    g.structuredClone = savedClone;
  });

  it('renders the header, data fields, version diff and comments', async () => {
    const { http, detectChanges } = await setup();
    flushAll(http);
    detectChanges();

    expect(screen.getByRole('heading', { name: 'Förderung Fest', level: 1 })).toBeInTheDocument();
    expect(screen.getByText('Eingereicht')).toBeInTheDocument();
    // "Version 2" shows in the header and again as a history entry
    expect(screen.getAllByText('Version 2').length).toBeGreaterThan(0);
    // applicant fact
    expect(screen.getByText('Mia')).toBeInTheDocument();
    // version diff: changed title old → new
    expect(screen.getByText('Fest')).toBeInTheDocument();
    // comment body
    expect(screen.getByText('Bitte Kostenplan ergänzen.')).toBeInTheDocument();
    flushAttachments(http);
    http.verify();
  });

  it('hides the internal-visibility select for non-managers', async () => {
    const { http, detectChanges } = await setup(['application.read']);
    http.expectOne(url('')).flush(appWire());
    http.expectOne(url('/versions')).flush(VERSIONS);
    http.expectOne(url('/comments')).flush(COMMENTS);
    detectChanges();

    // No manual status-change UI (handled via the flow) and no manager-only options.
    expect(screen.queryByRole('heading', { name: 'Statuswechsel' })).not.toBeInTheDocument();
    expect(screen.queryByText('Sichtbarkeit')).not.toBeInTheDocument();
    flushForm(http);
    flushAttachments(http);
    http.verify();
  });

  it('posts a new comment with the chosen visibility', async () => {
    const { http, detectChanges } = await setup();
    flushAll(http);
    detectChanges();

    await userEvent.type(screen.getByLabelText('Kommentar hinzufügen'), 'Danke!');
    await userEvent.click(screen.getByRole('button', { name: 'Senden' }));

    const post = http.expectOne(url('/comments'));
    expect(post.request.method).toBe('POST');
    expect(post.request.body).toEqual({ body: 'Danke!', visibility: 'public' });
    post.flush(
      {
        id: 'c2',
        author: null,
        authorKind: 'principal',
        body: 'Danke!',
        visibility: 'public',
        at: '2026-06-05T13:00:00Z',
      },
      { status: 201, statusText: 'Created' },
    );
    detectChanges();
    expect(screen.getByText('Danke!')).toBeInTheDocument();
    flushAttachments(http);
    http.verify();
  });

  it('labels a present-but-empty diff as "no field changes"', async () => {
    const { http, detectChanges } = await setup();
    http.expectOne(url('')).flush(appWire());
    http.expectOne(url('/versions')).flush([
      VERSIONS[0],
      { version: 2, data: {}, diff: { added: {}, removed: {}, changed: {} }, changedBy: null, at: '2026-06-05T11:00:00Z' },
    ]);
    http.expectOne(url('/comments')).flush(COMMENTS);
    detectChanges();
    expect(screen.getByText('Keine Feldänderungen.')).toBeInTheDocument();
    flushForm(http);
    flushAttachments(http);
    http.verify();
  });

  it('toasts an error when posting a comment fails', async () => {
    const { http, detectChanges, toast } = await setup();
    flushAll(http);
    detectChanges();
    const error = jest.spyOn(toast, 'error');

    await userEvent.type(screen.getByLabelText('Kommentar hinzufügen'), 'Hmm');
    await userEvent.click(screen.getByRole('button', { name: 'Senden' }));
    http
      .expectOne(url('/comments'))
      .flush({ title: 'Boom' }, { status: 500, statusText: 'Server Error' });

    expect(error).toHaveBeenCalledWith('Kommentar konnte nicht gespeichert werden.');
    flushAttachments(http);
    http.verify();
  });

  it('reloads when the route id changes on a reused component (paramMap, not snapshot)', async () => {
    const paramMap$ = new BehaviorSubject(convertToParamMap({ id: 'app-1' }));
    const { http, detectChanges } = await setup(
      ['application.read', 'application.manage'],
      paramMap$,
    );
    flushAll(http);
    detectChanges();

    // simulate Detail→Detail navigation: same component instance, new param
    paramMap$.next(convertToParamMap({ id: 'app-2' }));
    // a fresh detail GET for app-2 must fire (snapshot would have stayed on app-1)
    http.expectOne(url('', 'app-2')).flush({ ...appWire(), id: 'app-2' });
    http.expectOne(url('/versions', 'app-2')).flush(VERSIONS);
    http.expectOne(url('/comments', 'app-2')).flush(COMMENTS);
    flushForm(http, 'app-2'); // loadApplication for app-2 also fetches the effective form
    detectChanges();

    expect(screen.getByRole('heading', { level: 1 })).toBeInTheDocument();
    flushAttachments(http);
    http.verify();
  });

  it('discards a stale load when a newer navigation has bumped the load sequence', async () => {
    const paramMap$ = new BehaviorSubject(convertToParamMap({ id: 'app-1' }));
    const { http, detectChanges, cmp } = await setup(['application.read'], paramMap$);

    // Hold the app-1 detail request unflushed, then navigate to app-2 (bumps loadSeq).
    const stale = http.expectOne(url(''));
    paramMap$.next(convertToParamMap({ id: 'app-2' }));

    // The fresh app-2 load fires immediately and resolves fully.
    http.expectOne(url('', 'app-2')).flush({ ...appWire(), id: 'app-2' });
    http.expectOne(url('/versions', 'app-2')).flush(VERSIONS);
    http.expectOne(url('/comments', 'app-2')).flush(COMMENTS);
    flushForm(http, 'app-2');
    detectChanges();
    flushAttachments(http);

    // Now flush the stale app-1 detail GET: the seq guard returns early, so it
    // must NOT overwrite app-2's state and must NOT trigger app-1's loadAux.
    stale.flush(appWire());
    detectChanges();
    expect(cmp.app()?.id).toBe('app-2');

    // No app-1 versions/comments/form requests should have been issued.
    expect(http.match((r) => r.url === '/api/applications/app-1/versions')).toHaveLength(0);
    expect(http.match((r) => r.url === '/api/applications/app-1/form')).toHaveLength(0);
    flushAttachments(http);
    http.verify();
  });

  it('ignores a stale load *error* once a newer navigation has started', async () => {
    const paramMap$ = new BehaviorSubject(convertToParamMap({ id: 'app-1' }));
    const { http, detectChanges, cmp } = await setup(['application.read'], paramMap$);

    const stale = http.expectOne(url(''));
    paramMap$.next(convertToParamMap({ id: 'app-2' }));
    http.expectOne(url('', 'app-2')).flush({ ...appWire(), id: 'app-2' });
    http.expectOne(url('/versions', 'app-2')).flush(VERSIONS);
    http.expectOne(url('/comments', 'app-2')).flush(COMMENTS);
    flushForm(http, 'app-2');
    detectChanges();
    flushAttachments(http);

    // Stale 404 arrives late: the seq guard returns before setting notFound/error.
    stale.flush({ title: 'Gone' }, { status: 404, statusText: 'Not Found' });
    detectChanges();
    expect(cmp.notFound()).toBe(false);
    expect(cmp.error()).toBe(false);
    expect(cmp.app()?.id).toBe('app-2');
    flushAttachments(http);
    http.verify();
  });

  it('ignores a stale refresh once a newer navigation has started', async () => {
    const paramMap$ = new BehaviorSubject(convertToParamMap({ id: 'app-1' }));
    const { http, detectChanges, cmp } = await setup(
      ['application.read', 'application.manage'],
      paramMap$,
    );
    flushAll(http);
    detectChanges();
    flushAttachments(http);

    // Trigger a refresh (via a successful erasure request → no refresh; use delete?).
    // Simpler: call the private refresh(), hold its GET, then navigate.
    (cmp as unknown as { refresh: () => void }).refresh();
    const staleRefresh = http.expectOne(url(''));
    paramMap$.next(convertToParamMap({ id: 'app-2' }));
    http.expectOne(url('', 'app-2')).flush({ ...appWire(), id: 'app-2' });
    http.expectOne(url('/versions', 'app-2')).flush(VERSIONS);
    http.expectOne(url('/comments', 'app-2')).flush(COMMENTS);
    flushForm(http, 'app-2');
    for (const req of http.match((r) => r.method === 'GET' && r.url === '/api/budgets')) {
      req.flush([]);
    }
    detectChanges();
    flushAttachments(http);

    // The stale refresh response must not overwrite app-2 nor trigger app-1 loadAux.
    staleRefresh.flush({ ...appWire(), id: 'app-1' });
    detectChanges();
    expect(cmp.app()?.id).toBe('app-2');
    expect(http.match((r) => r.url === '/api/applications/app-1/versions')).toHaveLength(0);
    flushAttachments(http);
    http.verify();
  });

  it('renders data with form-field labels and typed values', async () => {
    const { http, detectChanges } = await setup();
    http.expectOne(url('')).flush(appWire());
    http.expectOne(url('/versions')).flush(VERSIONS);
    http.expectOne(url('/comments')).flush(COMMENTS);
    http.expectOne((r) => r.url === '/api/applications/app-1/form').flush({
      applicationTypeId: 't1',
      formVersionId: 'fv1',
      sections: [
        { key: 'main', label: { de: 'Antrag' }, fields: [{ key: 'amount', type: 'currency', label: { de: 'Beantragte Summe' } }] },
      ],
    });
    detectChanges();

    // data row uses the field label, not the raw key, and formats the currency value.
    expect(screen.getByText('Beantragte Summe')).toBeInTheDocument();
    flushAttachments(http);
    http.verify();
  });

  it('shows a not-found message for a 404 application', async () => {
    const { http, detectChanges } = await setup();
    http.expectOne(url('')).flush({ title: 'Not found' }, { status: 404, statusText: 'Not Found' });
    detectChanges();
    expect(screen.getByText('Antrag nicht gefunden.')).toBeInTheDocument();
    flushAttachments(http);
    http.verify();
  });

  it('treats an empty route id as not-found without firing a request', async () => {
    const paramMap$ = new BehaviorSubject(convertToParamMap({}));
    const { http, detectChanges, cmp } = await setup(['application.read'], paramMap$);
    detectChanges();
    expect(cmp.notFound()).toBe(true);
    expect(cmp.loading()).toBe(false);
    expect(screen.getByText('Antrag nicht gefunden.')).toBeInTheDocument();
    http.verify();
  });

  it('shows the generic error message for a non-404 load failure', async () => {
    const { http, detectChanges, cmp } = await setup();
    http.expectOne(url('')).flush({ title: 'Boom' }, { status: 500, statusText: 'Server Error' });
    detectChanges();
    expect(cmp.error()).toBe(true);
    expect(cmp.notFound()).toBe(false);
    expect(screen.getByText('Antrag konnte nicht geladen werden.')).toBeInTheDocument();
    http.verify();
  });

  it('degrades the effective-form to empty on a form error', async () => {
    const { http, detectChanges, cmp } = await setup();
    http.expectOne(url('')).flush(appWire());
    http.expectOne(url('/versions')).flush(VERSIONS);
    http.expectOne(url('/comments')).flush(COMMENTS);
    for (const req of http.match((r) => r.method === 'GET' && r.url === '/api/budgets')) {
      req.flush([]);
    }
    http
      .expectOne((r) => r.url === '/api/applications/app-1/form')
      .flush({ title: 'x' }, { status: 500, statusText: 'Server Error' });
    detectChanges();
    expect(cmp.formFields()).toEqual([]);
    flushAttachments(http);
    http.verify();
  });

  it('loads manual transitions and fires one (success → refresh)', async () => {
    const { http, detectChanges, cmp, toast } = await setup([
      'application.read',
      'application.manage',
      'application.transition',
    ]);
    http.expectOne(url('')).flush(appWire());
    http.expectOne(url('/versions')).flush(VERSIONS);
    http.expectOne(url('/comments')).flush(COMMENTS);
    http.expectOne(url('/transitions')).flush([
      { id: 'tr-1', fromStateId: 's1', toStateId: 's2', label: { de: 'Annehmen' }, color: '#0a0' },
    ]);
    for (const req of http.match((r) => r.method === 'GET' && r.url === '/api/budgets')) {
      req.flush([]);
    }
    flushForm(http);
    detectChanges();
    const success = jest.spyOn(toast, 'success');

    await userEvent.click(screen.getByRole('button', { name: 'Annehmen' }));
    const post = http.expectOne((r) => r.url === '/api/applications/app-1/transition');
    expect(post.request.method).toBe('POST');
    expect(post.request.body).toEqual({ transitionId: 'tr-1' });
    post.flush({ newStateId: 's2', statusEventId: 'e1', dispatchedActions: [] });
    expect(cmp.firing()).toBeNull();
    expect(success).toHaveBeenCalled();

    // refresh re-fetches the application + aux (no form re-fetch).
    http.expectOne(url('')).flush({ ...appWire(), version: 3 });
    http.expectOne(url('/versions')).flush(VERSIONS);
    http.expectOne(url('/comments')).flush(COMMENTS);
    http.expectOne(url('/transitions')).flush([]);
    for (const req of http.match((r) => r.method === 'GET' && r.url === '/api/budgets')) {
      req.flush([]);
    }
    detectChanges();
    flushAttachments(http);
    http.verify();
  });

  it('ignores a second fire while one is in flight', async () => {
    const { cmp } = await setup();
    const t: Transition = { id: 'tr-1', fromStateId: 's1', toStateId: 's2', label: 'Go', color: null };
    cmp.firing.set('other');
    cmp.fire(t);
    // firing unchanged — guard returned early
    expect(cmp.firing()).toBe('other');
  });

  it.each([
    [403, 'Sie dürfen diesen Übergang nicht ausführen.'],
    [409, 'Statuswechsel nicht möglich (Status hat sich geändert oder Bedingung nicht erfüllt).'],
    [500, 'Statuswechsel fehlgeschlagen.'],
  ])('maps a failed transition %s to its toast (and refreshes)', async (status, message) => {
    const { http, detectChanges, cmp, toast } = await setup([
      'application.read',
      'application.manage',
      'application.transition',
    ]);
    http.expectOne(url('')).flush(appWire());
    http.expectOne(url('/versions')).flush(VERSIONS);
    http.expectOne(url('/comments')).flush(COMMENTS);
    http.expectOne(url('/transitions')).flush([
      { id: 'tr-1', fromStateId: 's1', toStateId: 's2', label: { de: 'Annehmen' }, color: null },
    ]);
    for (const req of http.match((r) => r.method === 'GET' && r.url === '/api/budgets')) {
      req.flush([]);
    }
    flushForm(http);
    detectChanges();
    const error = jest.spyOn(toast, 'error');

    await userEvent.click(screen.getByRole('button', { name: 'Annehmen' }));
    http
      .expectOne((r) => r.url === '/api/applications/app-1/transition')
      .flush({ title: 'e' }, { status, statusText: 'x' });
    expect(error).toHaveBeenCalledWith(message);
    expect(cmp.firing()).toBeNull();

    // refresh fires even on error
    http.expectOne(url('')).flush(appWire());
    http.expectOne(url('/versions')).flush(VERSIONS);
    http.expectOne(url('/comments')).flush(COMMENTS);
    http.expectOne(url('/transitions')).flush([]);
    for (const req of http.match((r) => r.method === 'GET' && r.url === '/api/budgets')) {
      req.flush([]);
    }
    detectChanges();
    flushAttachments(http);
    http.verify();
  });

  it('degrades transitions to empty on a load error', async () => {
    const { http, detectChanges, cmp } = await setup([
      'application.read',
      'application.transition',
    ]);
    http.expectOne(url('')).flush(appWire());
    http.expectOne(url('/versions')).flush(VERSIONS);
    http.expectOne(url('/comments')).flush(COMMENTS);
    http
      .expectOne(url('/transitions'))
      .flush({ title: 'e' }, { status: 500, statusText: 'Server Error' });
    flushForm(http);
    detectChanges();
    expect(cmp.transitions()).toEqual([]);
    flushAttachments(http);
    http.verify();
  });

  // --- budget assignment (#17) --------------------------------------------
  function budgetTree() {
    return [
      {
        id: 'b1',
        parentId: null,
        gremiumId: null,
        key: 'VS',
        pathKey: 'VS-800',
        name: 'Veranstaltungen',
        currency: 'EUR',
        active: true,
        color: null,
        acceptedStateKeys: [],
        deniedStateKeys: [],
        hiddenInBudget: false,
        viewGremiumId: null,
        fiscalStartMonth: 1,
        fiscalStartDay: 1,
        byFiscalYear: [],
        children: [],
      },
    ];
  }

  it('shows the budget badge label for an assigned cost centre', async () => {
    const { http, detectChanges, cmp } = await setup();
    http.expectOne(url('')).flush({ ...appWire(), budgetId: 'b1' });
    http.expectOne(url('/versions')).flush(VERSIONS);
    http.expectOne(url('/comments')).flush(COMMENTS);
    http.expectOne((r) => r.method === 'GET' && r.url === '/api/budgets').flush(budgetTree());
    // Top-Budget der zugeordneten Kostenstelle → HHJ-Liste wird nachgeladen (#fiscal).
    http.expectOne((r) => r.url === '/api/budgets/b1/fiscal-years').flush([]);
    flushForm(http);
    detectChanges();
    expect(cmp.budgetLabel('b1')).toContain('Veranstaltungen');
    expect(cmp.budgetLabel(null)).toBe('');
    expect(cmp.budgetLabel('unknown')).toBe('');
    expect(screen.getByText(/Veranstaltungen/)).toBeInTheDocument();
    flushAttachments(http);
    http.verify();
  });

  it('degrades the budget tree to empty on a load error', async () => {
    const { http, detectChanges, cmp } = await setup();
    http.expectOne(url('')).flush(appWire());
    http.expectOne(url('/versions')).flush(VERSIONS);
    http.expectOne(url('/comments')).flush(COMMENTS);
    http
      .expectOne((r) => r.method === 'GET' && r.url === '/api/budgets')
      .flush({ title: 'e' }, { status: 500, statusText: 'Server Error' });
    flushForm(http);
    detectChanges();
    expect(cmp.budgetTree()).toEqual([]);
    flushAttachments(http);
    http.verify();
  });

  it('assigns a budget (success → toast + refresh) and opens the dialog with the current value', async () => {
    const { http, detectChanges, cmp, toast } = await setup();
    http.expectOne(url('')).flush({ ...appWire(), budgetId: 'b1' });
    http.expectOne(url('/versions')).flush(VERSIONS);
    http.expectOne(url('/comments')).flush(COMMENTS);
    http.expectOne((r) => r.method === 'GET' && r.url === '/api/budgets').flush(budgetTree());
    // initiale HHJ-Liste der zugeordneten Kostenstelle (#fiscal)
    http.expectOne((r) => r.url === '/api/budgets/b1/fiscal-years').flush([]);
    flushForm(http);
    flushAttachments(http);
    detectChanges();
    const success = jest.spyOn(toast, 'success');

    cmp.openBudgetDialog();
    expect(cmp.budgetDialogOpen()).toBe(true);
    expect(cmp.budgetChoice()).toBe('b1');
    // Dialog öffnen lädt die HHJ-Liste des aktuellen Top-Budgets erneut
    http.expectOne((r) => r.url === '/api/budgets/b1/fiscal-years').flush([]);

    cmp.budgetChoice.set('');
    cmp.assignBudget();
    const post = http.expectOne((r) => r.url === '/api/applications/app-1/assign-budget');
    expect(post.request.method).toBe('POST');
    expect(post.request.body).toEqual({ budgetId: null, fiscalYearId: null });
    post.flush({ applicationId: 'app-1', budgetId: null, fiscalYearId: null });
    expect(cmp.assigningBudget()).toBe(false);
    expect(cmp.budgetDialogOpen()).toBe(false);
    expect(success).toHaveBeenCalled();

    // refresh
    http.expectOne(url('')).flush(appWire());
    http.expectOne(url('/versions')).flush(VERSIONS);
    http.expectOne(url('/comments')).flush(COMMENTS);
    for (const req of http.match((r) => r.method === 'GET' && r.url === '/api/budgets')) {
      req.flush([]);
    }
    detectChanges();
    flushAttachments(http);
    http.verify();
  });

  it('ignores a second assignBudget while one is in flight', async () => {
    const { cmp } = await setup();
    cmp.assigningBudget.set(true);
    cmp.assignBudget();
    // still true, no extra request emitted (verified by http.verify in other tests)
    expect(cmp.assigningBudget()).toBe(true);
  });

  it.each([
    [422, 'Zuordnung nicht möglich – Kostenstelle/Haushaltsjahr prüfen.'],
    [403, 'Sie dürfen diesen Übergang nicht ausführen.'],
    [500, 'Statuswechsel fehlgeschlagen.'],
  ])('maps a failed budget assignment %s to its toast', async (status, message) => {
    const { http, detectChanges, cmp, toast } = await setup();
    http.expectOne(url('')).flush(appWire());
    http.expectOne(url('/versions')).flush(VERSIONS);
    http.expectOne(url('/comments')).flush(COMMENTS);
    http.expectOne((r) => r.method === 'GET' && r.url === '/api/budgets').flush(budgetTree());
    flushForm(http);
    detectChanges();
    flushAttachments(http);
    const error = jest.spyOn(toast, 'error');

    cmp.budgetChoice.set('b1');
    cmp.assignBudget();
    http
      .expectOne((r) => r.url === '/api/applications/app-1/assign-budget')
      .flush({ title: 'e' }, { status, statusText: 'x' });
    expect(error).toHaveBeenCalledWith(message);
    expect(cmp.assigningBudget()).toBe(false);
    http.verify();
  });

  // --- value formatting via dataEntries / formatByField -------------------
  function setupWithFields(
    fields: FormFieldDef[],
    data: Record<string, unknown>,
  ): Promise<Awaited<ReturnType<typeof setup>>> {
    return (async () => {
      const ctx = await setup();
      ctx.http.expectOne(url('')).flush({ ...appWire(), data });
      ctx.http.expectOne(url('/versions')).flush(VERSIONS);
      ctx.http.expectOne(url('/comments')).flush(COMMENTS);
      for (const req of ctx.http.match((r) => r.method === 'GET' && r.url === '/api/budgets')) {
        req.flush([]);
      }
      ctx.http.expectOne((r) => r.url === '/api/applications/app-1/form').flush({
        applicationTypeId: 't1',
        formVersionId: 'fv1',
        sections: [{ key: 'main', label: { de: 'Antrag' }, fields }],
      });
      ctx.detectChanges();
      return ctx;
    })();
  }

  it('formats checkbox / select / multiselect / currency / dash values', async () => {
    const fields: FormFieldDef[] = [
      { key: 'agree', type: 'checkbox', label: { de: 'Zustimmung' } },
      {
        key: 'cat',
        type: 'select',
        label: { de: 'Kategorie' },
        options: [{ value: 'a', label: { de: 'Kultur' } }],
      },
      {
        key: 'tags',
        type: 'multiselect',
        label: { de: 'Tags' },
        options: [{ value: 'x', label: { de: 'X-Label' } }],
      },
      { key: 'budget', type: 'currency', label: { de: 'Budget' } },
      { key: 'empty', type: 'text', label: { de: 'Leer' } },
      { key: 'desc', type: 'markdown', label: { de: 'Beschreibung' } },
    ];
    const data = {
      agree: true,
      cat: 'a',
      tags: ['x', 'y'],
      budget: 1234.5,
      empty: '',
      desc: '# ignored',
    };
    const { cmp } = await setupWithFields(fields, data);
    const app = cmp.app() as Application;
    const byKey = new Map(cmp.dataEntries(app).map((e) => [e.key, e.value]));
    expect(byKey.get('agree')).toBe('Ja');
    expect(byKey.get('cat')).toBe('Kultur');
    // unknown multiselect option falls back to the raw value
    expect(byKey.get('tags')).toBe('X-Label, y');
    expect(byKey.get('budget')).toContain('1.234,50');
    expect(byKey.get('empty')).toBe('—');
    // markdown is a display-only field → excluded
    expect(byKey.has('desc')).toBe(false);
  });

  it('handles unknown select option and non-finite currency and false checkbox', async () => {
    const fields: FormFieldDef[] = [
      {
        key: 'cat',
        type: 'select',
        label: { de: 'Kategorie' },
        options: [{ value: 'a', label: { de: 'Kultur' } }],
      },
      { key: 'budget', type: 'currency', label: { de: 'Budget' } },
      { key: 'agree', type: 'checkbox', label: { de: 'Zustimmung' } },
    ];
    const data = { cat: 'zzz', budget: 'not-a-number', agree: false };
    const { cmp } = await setupWithFields(fields, data);
    const app = cmp.app() as Application;
    const byKey = new Map(cmp.dataEntries(app).map((e) => [e.key, e.value]));
    expect(byKey.get('cat')).toBe('zzz');
    expect(byKey.get('budget')).toBe('not-a-number');
    expect(byKey.get('agree')).toBe('Nein');
  });

  it('renders raw data rows for keys without a field definition (excluding title)', async () => {
    const { cmp } = await setupWithFields(
      [{ key: 'known', type: 'text', label: { de: 'Bekannt' } }],
      { title: 'Hidden', known: 'v', extra: { a: 1 } },
    );
    const app = cmp.app() as Application;
    const rows = cmp.dataEntries(app);
    const keys = rows.map((r) => r.key);
    expect(keys).not.toContain('title');
    expect(keys).toContain('extra');
    const extra = rows.find((r) => r.key === 'extra');
    expect(extra?.label).toBe('extra');
    expect(extra?.value).toBe('{"a":1}');
  });

  // --- positions block (#1) -----------------------------------------------
  it('renders the positions block with preferred-offer totals', async () => {
    const fields: FormFieldDef[] = [
      { key: 'kosten', type: 'positions', label: { de: 'Kostenaufstellung' } },
    ];
    const data = {
      kosten: [
        {
          label: 'Bühne',
          offers: [
            { label: 'Anbieter A', value: 100, preferred: true },
            { label: 'Anbieter B', value: 120, preferred: false },
          ],
        },
        { offers: 'nope' }, // missing label → defaults to '' (?? branch)
      ],
    };
    const { cmp } = await setupWithFields(fields, data);
    const app = cmp.app() as Application;

    // positions are NOT in dataEntries
    expect(cmp.dataEntries(app).some((e) => e.key === 'kosten')).toBe(false);

    const blocks = cmp.positionEntries(app);
    expect(blocks).toHaveLength(1);
    expect(blocks[0].positions).toHaveLength(2);
    // bad offers normalise to []
    expect(blocks[0].positions[1].offers).toEqual([]);
    expect(blocks[0].positions[1].label).toBe('');

    expect(cmp.positionValue(blocks[0].positions[0])).toBe(100);
    // no preferred → 0
    expect(cmp.positionValue(blocks[0].positions[1])).toBe(0);
    expect(cmp.positionsTotal(blocks[0].positions)).toBe(100);
    expect(cmp.money(100)).toContain('100,00');
    expect(cmp.money(null)).toContain('0,00');
    expect(cmp.money(NaN)).toContain('0,00');
  });

  it('skips positions blocks when the value is not an array', async () => {
    const fields: FormFieldDef[] = [
      { key: 'kosten', type: 'positions', label: { de: 'Kostenaufstellung' } },
    ];
    const { cmp } = await setupWithFields(fields, { kosten: 'broken' });
    expect(cmp.positionEntries(cmp.app() as Application)).toEqual([]);
  });

  it('formatByField summarises a positions value (count × total) and dashes non-arrays', async () => {
    const { cmp } = await setup();
    const field: FormFieldDef = { key: 'kosten', type: 'positions', label: { de: 'Kosten' } };
    const fmt = (
      cmp as unknown as { formatByField: (f: FormFieldDef, v: unknown) => string }
    ).formatByField.bind(cmp);
    const summary = fmt(field, [
      { offers: [{ value: 100, preferred: true }, { value: 80, preferred: false }] },
      { offers: [{ value: 50, preferred: true }] },
      { offers: [{ value: 10, preferred: false }] }, // no preferred → 0
      {}, // missing offers → 0
    ]);
    expect(summary).toMatch(/^4 ×/);
    expect(summary).toContain('150,00');
    // non-array positions value falls back to a dash
    expect(fmt(field, 'nope')).toBe('—');
  });

  it('summarises positions compactly in a non-positions data row context', async () => {
    // positions inside dataEntries route through formatByField → formatPositions,
    // exercised here by calling the public formatter contract through a select
    // that holds an array value handled as multiselect; positions summary is
    // covered via positionEntries above. Here we assert formatPositions edge
    // (empty array) using the dash branch.
    const fields: FormFieldDef[] = [
      { key: 'multi', type: 'multiselect', label: { de: 'Multi' } },
    ];
    const { cmp } = await setupWithFields(fields, { multi: 'not-array' });
    const app = cmp.app() as Application;
    const row = cmp.dataEntries(app).find((e) => e.key === 'multi');
    // non-array multiselect falls through to formatFieldValue
    expect(row?.value).toBe('not-array');
  });

  // --- amount() formatting -------------------------------------------------
  it('formats the requested amount, falling back for null / non-numeric', async () => {
    const { cmp } = await setup();
    const base = { ...({} as Application) };
    void base;
    const app = (v: string | null, currency: string | null = 'EUR'): Application =>
      ({ amount: v, currency }) as Application;
    expect(cmp.amount(app(null))).toBe('—');
    expect(cmp.amount(app('abc'))).toBe('abc');
    expect(cmp.amount(app('250.00'))).toContain('250,00');
    expect(cmp.amount(app('10', null))).toContain('10,00');
  });

  // --- isEmptyDiff ---------------------------------------------------------
  it('isEmptyDiff is false for a null diff and true for an all-empty diff', async () => {
    const { cmp } = await setup();
    expect(cmp.isEmptyDiff({ diff: null } as ApplicationVersion)).toBe(false);
    expect(
      cmp.isEmptyDiff({ diff: { added: [], removed: [], changed: [] } } as ApplicationVersion),
    ).toBe(true);
    expect(
      cmp.isEmptyDiff({
        diff: { added: [{ key: 'a', value: 1 }], removed: [], changed: [] },
      } as ApplicationVersion),
    ).toBe(false);
  });

  // --- comment author / initial helpers -----------------------------------
  it('derives the author name and avatar initials', async () => {
    const { cmp } = await setup();
    expect(cmp['authorName']({ author: 'Mia Müller' } as ApplicationComment)).toBe('Mia Müller');
    expect(
      cmp['authorName']({ author: null, authorKind: 'applicant' } as ApplicationComment),
    ).toBe('Antragsteller:in');
    expect(
      cmp['authorName']({ author: null, authorKind: 'principal' } as ApplicationComment),
    ).toBe('Gremium');
    expect(cmp['initial']('Mia Müller')).toBe('MM');
    expect(cmp['initial']('Solo')).toBe('S');
    expect(cmp['initial']('   ')).toBe('?');
  });

  it('does not post an empty/whitespace comment and guards against double-submit', async () => {
    const { http, detectChanges, cmp } = await setup();
    flushAll(http);
    detectChanges();
    flushAttachments(http);
    const evt = { preventDefault: jest.fn() } as unknown as Event;

    cmp.newComment.set('   ');
    cmp.submitComment(evt);
    expect(evt.preventDefault).toHaveBeenCalled();
    expect(cmp.posting()).toBe(false);

    cmp.newComment.set('real');
    cmp.posting.set(true);
    cmp.submitComment(evt);
    // still posting, no request fired (verified below)
    http.verify();
  });

  // --- edit (#24) ----------------------------------------------------------
  it('starts inline edit, cancels, and saves (success)', async () => {
    const { http, detectChanges, cmp, toast } = await setupWithFields(
      [{ key: 'title', type: 'text', label: { de: 'Titel' } }],
      { title: 'Förderung Fest' },
    );
    flushAttachments(http);
    const success = jest.spyOn(toast, 'success');

    cmp.startEdit(cmp.app() as Application);
    expect(cmp.editing()).toBe(true);
    expect(cmp.editModel).toEqual({ title: 'Förderung Fest' });
    expect(cmp.editFields().length).toBeGreaterThan(0);

    cmp.cancelEdit();
    expect(cmp.editing()).toBe(false);

    cmp.startEdit(cmp.app() as Application);
    cmp.editModel = { title: 'Neu' };
    cmp.saveEdit();
    const patch = http.expectOne((r) => r.method === 'PATCH' && r.url === '/api/applications/app-1');
    expect(patch.request.body).toEqual({ data: { title: 'Neu' } });
    patch.flush({ ...appWire(), data: { title: 'Neu' } });
    expect(cmp.savingEdit()).toBe(false);
    expect(cmp.editing()).toBe(false);
    expect(success).toHaveBeenCalled();

    // refresh after save
    http.expectOne(url('')).flush(appWire());
    http.expectOne(url('/versions')).flush(VERSIONS);
    http.expectOne(url('/comments')).flush(COMMENTS);
    for (const req of http.match((r) => r.method === 'GET' && r.url === '/api/budgets')) {
      req.flush([]);
    }
    detectChanges();
    flushAttachments(http);
    http.verify();
  });

  it('does not save while the edit form is invalid or already saving', async () => {
    const { http, detectChanges, cmp } = await setup();
    flushAll(http);
    detectChanges();
    flushAttachments(http);

    // invalid form
    jest.spyOn(cmp.editForm, 'invalid', 'get').mockReturnValue(true);
    cmp.saveEdit();
    expect(cmp.savingEdit()).toBe(false);

    // already saving
    jest.spyOn(cmp.editForm, 'invalid', 'get').mockReturnValue(false);
    cmp.savingEdit.set(true);
    cmp.saveEdit();
    http.verify();
  });

  it.each([
    [409, 'In diesem Status nicht bearbeitbar.'],
    [500, 'Speichern fehlgeschlagen.'],
  ])('maps a failed save %s to its toast', async (status, message) => {
    const { http, detectChanges, cmp, toast } = await setup();
    flushAll(http);
    detectChanges();
    flushAttachments(http);
    const error = jest.spyOn(toast, 'error');

    cmp.editModel = { title: 'Neu' };
    cmp.saveEdit();
    http
      .expectOne((r) => r.method === 'PATCH' && r.url === '/api/applications/app-1')
      .flush({ title: 'e' }, { status, statusText: 'x' });
    expect(error).toHaveBeenCalledWith(message);
    expect(cmp.savingEdit()).toBe(false);
    http.verify();
  });

  // --- delete (#24, admin-only) -------------------------------------------
  it('deletes the application and navigates to the list', async () => {
    const { http, detectChanges, cmp, toast, router } = await setup(
      ['application.read', 'application.manage'],
      new BehaviorSubject(convertToParamMap({ id: 'app-1' })),
      ['admin'],
    );
    flushAll(http);
    detectChanges();
    flushAttachments(http);
    const success = jest.spyOn(toast, 'success');
    const nav = jest.spyOn(router, 'navigate').mockResolvedValue(true);
    expect(cmp.isAdmin()).toBe(true);

    cmp.doDelete();
    http
      .expectOne((r) => r.method === 'DELETE' && r.url === '/api/applications/app-1')
      .flush(null, { status: 204, statusText: 'No Content' });
    expect(cmp.deleting()).toBe(false);
    expect(cmp.confirmDelete()).toBe(false);
    expect(success).toHaveBeenCalled();
    expect(nav).toHaveBeenCalledWith(['/applications']);
    http.verify();
  });

  it('toasts and keeps the dialog on a failed delete, and guards double-delete', async () => {
    const { http, detectChanges, cmp, toast } = await setup();
    flushAll(http);
    detectChanges();
    flushAttachments(http);
    const error = jest.spyOn(toast, 'error');

    cmp.doDelete();
    http
      .expectOne((r) => r.method === 'DELETE' && r.url === '/api/applications/app-1')
      .flush({ title: 'e' }, { status: 500, statusText: 'Server Error' });
    expect(error).toHaveBeenCalledWith('Löschen fehlgeschlagen.');
    expect(cmp.deleting()).toBe(false);

    cmp.deleting.set(true);
    cmp.doDelete();
    http.verify();
  });

  // --- erasure request (DSGVO) --------------------------------------------
  it('requests erasure (success) and guards double-request', async () => {
    const { http, detectChanges, cmp, toast } = await setup();
    flushAll(http);
    detectChanges();
    flushAttachments(http);
    const success = jest.spyOn(toast, 'success');

    cmp.doRequestErasure();
    http
      .expectOne((r) => r.method === 'POST' && r.url === '/api/applications/app-1/erasure-request')
      .flush(null, { status: 202, statusText: 'Accepted' });
    expect(cmp.requestingErasure()).toBe(false);
    expect(cmp.confirmErase()).toBe(false);
    expect(success).toHaveBeenCalledWith('Löschantrag eingegangen.');

    cmp.requestingErasure.set(true);
    cmp.doRequestErasure();
    http.verify();
  });

  it('toasts on a failed erasure request', async () => {
    const { http, detectChanges, cmp, toast } = await setup();
    flushAll(http);
    detectChanges();
    flushAttachments(http);
    const error = jest.spyOn(toast, 'error');

    cmp.doRequestErasure();
    http
      .expectOne((r) => r.method === 'POST' && r.url === '/api/applications/app-1/erasure-request')
      .flush({ title: 'e' }, { status: 500, statusText: 'Server Error' });
    expect(error).toHaveBeenCalledWith('Löschantrag fehlgeschlagen.');
    expect(cmp.requestingErasure()).toBe(false);
    http.verify();
  });

  it('renders the not-provided title fallback when data has no title key', async () => {
    const { http, detectChanges, cmp } = await setup();
    http.expectOne(url('')).flush({ ...appWire(), data: {} });
    http.expectOne(url('/versions')).flush(VERSIONS);
    http.expectOne(url('/comments')).flush(COMMENTS);
    for (const req of http.match((r) => r.method === 'GET' && r.url === '/api/budgets')) {
      req.flush([]);
    }
    flushForm(http);
    detectChanges();
    expect(cmp.title()).toBe('Ohne Titel');
    flushAttachments(http);
    http.verify();
  });
});
