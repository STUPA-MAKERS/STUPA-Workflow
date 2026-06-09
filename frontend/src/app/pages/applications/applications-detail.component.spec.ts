import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { BehaviorSubject } from 'rxjs';
import { ApplicationsDetailComponent } from './applications-detail.component';
import { AuthService } from '@core/auth/auth.service';
import { USE_MOCK_API } from '@core/api/api.config';
import { ToastService } from '@shared/ui/toast/toast.service';
import type {
  ApplicationOutWire,
  CommentOutWire,
  StateOutWire,
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

function fakeAuth(permissions: string[]): Partial<AuthService> {
  return { can: (p: string) => permissions.includes(p) };
}

async function setup(
  permissions: string[] = ['application.read', 'application.manage'],
  paramMap$ = new BehaviorSubject(convertToParamMap({ id: 'app-1' })),
) {
  const view = await render(ApplicationsDetailComponent, {
    providers: [
      provideRouter([]),
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
      { provide: AuthService, useValue: fakeAuth(permissions) },
      { provide: ActivatedRoute, useValue: { paramMap: paramMap$ } },
    ],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  const toast = view.fixture.debugElement.injector.get(ToastService);
  return { ...view, http, toast, paramMap$ };
}

const url =
  (suffix: string, id = 'app-1') =>
  (r: { url: string }) =>
    r.url === `/api/applications/${id}${suffix}`;

/** Flush the effective-form request used for data-field labels. */
function flushForm(http: HttpTestingController) {
  http
    .expectOne((r) => r.url === '/api/application-types/t1/form')
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
  if (form) flushForm(http);
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
    flushForm(http); // loadApplication for app-2 also fetches the effective form
    detectChanges();

    expect(screen.getByRole('heading', { level: 1 })).toBeInTheDocument();
    flushAttachments(http);
    http.verify();
  });

  it('renders data with form-field labels and typed values', async () => {
    const { http, detectChanges } = await setup();
    http.expectOne(url('')).flush(appWire());
    http.expectOne(url('/versions')).flush(VERSIONS);
    http.expectOne(url('/comments')).flush(COMMENTS);
    http.expectOne((r) => r.url === '/api/application-types/t1/form').flush({
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
});
