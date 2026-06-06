import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { ApplicationsDetailComponent } from './applications-detail.component';
import { AuthService } from '@core/auth/auth.service';
import { USE_MOCK_API } from '@core/api/api.config';
import { ToastService } from '@shared/ui/toast/toast.service';
import type {
  ApplicationOutWire,
  CommentOutWire,
  StateOutWire,
  TransitionOutWire,
  VersionOutWire,
} from '@core/api/models';

const SUBMITTED: StateOutWire = {
  id: 's1',
  key: 'submitted',
  label: { de: 'Eingereicht', en: 'Submitted' },
  category: 'open',
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

const TRANSITIONS: TransitionOutWire[] = [
  { id: 'tr1', fromStateId: 's1', toStateId: 's2', label: { de: 'In Prüfung nehmen', en: 'Review' } },
];

function fakeAuth(permissions: string[]): Partial<AuthService> {
  return { can: (p: string) => permissions.includes(p) };
}

async function setup(permissions: string[] = ['application.read', 'application.manage']) {
  const view = await render(ApplicationsDetailComponent, {
    providers: [
      provideRouter([]),
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
      { provide: AuthService, useValue: fakeAuth(permissions) },
      {
        provide: ActivatedRoute,
        useValue: { snapshot: { paramMap: convertToParamMap({ id: 'app-1' }) } },
      },
    ],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  const toast = view.fixture.debugElement.injector.get(ToastService);
  return { ...view, http, toast };
}

const url = (suffix: string) => (r: { url: string }) => r.url === `/api/applications/app-1${suffix}`;

/** Flush the detail GET and the three (or two) aux loads it triggers. */
function flushAll(http: HttpTestingController, manage = true) {
  http.expectOne(url('')).flush(appWire());
  http.expectOne(url('/versions')).flush(VERSIONS);
  http.expectOne(url('/comments')).flush(COMMENTS);
  if (manage) http.expectOne(url('/transitions')).flush(TRANSITIONS);
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
    http.verify();
  });

  it('shows RBAC-gated transition actions only for managers', async () => {
    const { http, detectChanges } = await setup();
    flushAll(http);
    detectChanges();
    expect(screen.getByRole('heading', { name: 'Statuswechsel' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'In Prüfung nehmen' })).toBeInTheDocument();
    http.verify();
  });

  it('hides actions and never requests transitions without application.manage', async () => {
    const { http, detectChanges } = await setup(['application.read']);
    // no /transitions request expected
    http.expectOne(url('')).flush(appWire());
    http.expectOne(url('/versions')).flush(VERSIONS);
    http.expectOne(url('/comments')).flush(COMMENTS);
    detectChanges();

    expect(screen.queryByRole('heading', { name: 'Statuswechsel' })).not.toBeInTheDocument();
    // internal-visibility select is manager-only
    expect(screen.queryByText('Sichtbarkeit')).not.toBeInTheDocument();
    http.verify();
  });

  it('fires a confirmed transition and reloads on success', async () => {
    const { http, detectChanges, toast } = await setup();
    flushAll(http);
    detectChanges();
    const success = jest.spyOn(toast, 'success');

    await userEvent.click(screen.getByRole('button', { name: 'In Prüfung nehmen' }));
    expect(screen.getByText('Statuswechsel bestätigen')).toBeInTheDocument(); // confirm dialog
    await userEvent.click(screen.getByRole('button', { name: 'Ausführen' }));

    const post = http.expectOne(url('/transition'));
    expect(post.request.method).toBe('POST');
    expect(post.request.body).toEqual({ transitionId: 'tr1', note: null });
    post.flush({ newStateId: 's2', statusEventId: 'e1', dispatchedActions: [] });

    expect(success).toHaveBeenCalled();
    // refresh re-loads detail + aux
    flushAll(http);
    http.verify();
  });

  it('surfaces a 409 conflict as a dedicated toast', async () => {
    const { http, detectChanges, toast } = await setup();
    flushAll(http);
    detectChanges();
    const error = jest.spyOn(toast, 'error');

    await userEvent.click(screen.getByRole('button', { name: 'In Prüfung nehmen' }));
    await userEvent.click(screen.getByRole('button', { name: 'Ausführen' }));

    http
      .expectOne(url('/transition'))
      .flush({ title: 'Conflict' }, { status: 409, statusText: 'Conflict' });

    expect(error).toHaveBeenCalledWith(
      'Statuswechsel nicht möglich (Status hat sich geändert oder Bedingung nicht erfüllt).',
    );
    flushAll(http); // refresh after the failed attempt
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
    http.expectOne(url('/transitions')).flush(TRANSITIONS);
    detectChanges();
    expect(screen.getByText('Keine Feldänderungen.')).toBeInTheDocument();
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
    http.verify();
  });

  it('shows a not-found message for a 404 application', async () => {
    const { http, detectChanges } = await setup();
    http.expectOne(url('')).flush({ title: 'Not found' }, { status: 404, statusText: 'Not Found' });
    detectChanges();
    expect(screen.getByText('Antrag nicht gefunden.')).toBeInTheDocument();
    http.verify();
  });
});
