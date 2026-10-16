/**
 * The comments of the application detail page in `app-chat`: post, retry, edit, delete.
 *
 * Its own spec file: the base spec of the same component is already large, and one
 * file with both blocks pushes the first TestBed compile over the default jest timeout
 * under `--coverage`.
 */
import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { fireEvent, render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { BehaviorSubject } from 'rxjs';
import { ApplicationsDetailComponent } from './applications-detail.component';
import { ApplicationsPageService } from './applications-page.service';
import { RailStatusService } from '../../layout/rail-status.service';
import { AuthService } from '@core/auth/auth.service';
import { USE_MOCK_API } from '@core/api/api.config';
import { ToastService } from '@stupa-makers/ui-kit';
import type { ApplicationOutWire, CommentOutWire, StateOutWire, VersionOutWire } from '@core/api/models';
import { NO_LINKED_TODOS } from '../../../testing/todo-fixtures';

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
  return {
    can: (p: string) => permissions.includes(p),
    roles: (() => []) as unknown as AuthService['roles'],
    isAuthenticated: (() => true) as unknown as AuthService['isAuthenticated'],
  };
}

/** The page link of the side-by-side layout. */
function splitPage(): ApplicationsPageService {
  const page = new ApplicationsPageService();
  page.split.set(true);
  return page;
}

async function setup(
  permissions: string[] = ['application.read', 'application.manage'],
  paramMap$ = new BehaviorSubject(convertToParamMap({ id: 'app-1' })),
) {
  const view = await render(ApplicationsDetailComponent, {
    providers: [
      NO_LINKED_TODOS,
      provideRouter([]),
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
      { provide: AuthService, useValue: fakeAuth(permissions) },
      // The real service polls; the page only asks it to refresh.
      { provide: RailStatusService, useValue: { refresh: jest.fn() } },
      { provide: ActivatedRoute, useValue: { paramMap: paramMap$ } },
      // Side by side with the list: every section shows at once, no tabs.
      { provide: ApplicationsPageService, useFactory: splitPage },
    ],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  const toast = view.fixture.debugElement.injector.get(ToastService);
  const cmp = view.fixture.componentInstance;
  return { ...view, http, toast, cmp };
}

const url =
  (suffix: string, id = 'app-1') =>
  (r: { url: string }) =>
    r.url === `/api/applications/${id}${suffix}`;

/** Flush the effective-form request used for data-field labels. */
function flushForm(http: HttpTestingController, id = 'app-1') {
  http.expectOne((r) => r.url === `/api/applications/${id}/form`).flush({
    applicationTypeId: 't1',
    formVersionId: 'fv1',
    sections: [],
  });
}

/** The attachments panel loads on render. An empty answer is fine. */
function flushAttachments(http: HttpTestingController) {
  flushTypes(http);
  for (const req of http.match((r) => r.method === 'GET' && /\/(attachments|timeline)$/.test(r.url))) {
    req.flush([]);
  }
  for (const req of http.match((r) => r.method === 'GET' && r.url === '/api/budgets')) {
    req.flush([]);
  }
}

// --- helpers -----------------------------------------------------------------

/** The application types load once, for "<Typ> · Version n" above the title. */
function flushTypes(http: HttpTestingController) {
  for (const req of http.match((r) => r.method === 'GET' && r.url === '/api/application-types')) {
    req.flush({
      items: [{ id: 't1', name: 'Finanzantrag', hasBudget: true, active: true, activeFormVersionId: 'v1' }],
      total: 1,
      limit: 20,
      offset: 0,
    });
  }
}

/** Load the page with the given comments and answer every request of the load. */
async function loaded(permissions?: string[], comments: CommentOutWire[] = COMMENTS) {
  const ctx = await setup(permissions);
  flushTypes(ctx.http);
  ctx.http.expectOne(url('')).flush(appWire());
  ctx.http.expectOne(url('/versions')).flush(VERSIONS);
  ctx.http.expectOne(url('/comments')).flush(comments);
  for (const req of ctx.http.match((r) => r.method === 'GET' && r.url === '/api/budgets')) req.flush([]);
  flushForm(ctx.http);
  ctx.detectChanges();
  flushAttachments(ctx.http);
  const input = () => screen.getByRole('textbox', { name: 'Kommentar schreiben …' });
  const type = (text: string) => {
    fireEvent.input(input(), { target: { value: text } });
    fireEvent.keyDown(input(), { key: 'Enter' });
    ctx.detectChanges();
  };
  return { ...ctx, input, type };
}

const OWN: CommentOutWire = {
  id: 'c2',
  author: 'Mara Keller',
  authorKind: 'principal',
  authorInfo: { kind: 'principal', displayName: 'Mara Keller', principalId: 'p-9' },
  body: 'Mein Text',
  visibility: 'internal',
  at: '2026-06-05T12:30:00Z',
  isOwn: true,
};

describe('ApplicationsDetailComponent — comments in app-chat', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => localStorage.clear());

  it('posts a public comment without application.manage, at once and without a toast', async () => {
    const { http, toast, type, detectChanges } = await loaded(['application.read']);
    const success = jest.spyOn(toast, 'success');
    expect(screen.queryByRole('radiogroup', { name: 'Sichtbarkeit' })).not.toBeInTheDocument();
    expect(screen.getByText('Bitte Kostenplan ergänzen.')).toBeInTheDocument();
    // A foreign comment offers no edit.
    expect(screen.queryByRole('button', { name: 'Nachricht bearbeiten' })).not.toBeInTheDocument();

    type('Frage');
    expect(screen.getByText('wird gesendet …')).toBeInTheDocument();
    const post = http.expectOne(url('/comments'));
    expect(post.request.body).toEqual({ body: 'Frage', visibility: 'public' });
    post.flush({ ...OWN, id: 'c3', body: 'Frage', visibility: 'public' });
    detectChanges();
    expect(screen.getByText('Frage')).toBeInTheDocument();
    expect(screen.queryByText('wird gesendet …')).not.toBeInTheDocument();
    expect(success).not.toHaveBeenCalled();
    http.verify();
  });

  it('posts an internal comment when the toggle says so and keeps the choice', async () => {
    const { http, type, detectChanges } = await loaded();
    const group = screen.getByRole('radiogroup', { name: 'Sichtbarkeit' });
    expect(within(group).getByRole('radio', { name: 'Öffentlich' })).toHaveAttribute('aria-checked', 'true');
    await userEvent.click(within(group).getByRole('radio', { name: 'Intern' }));
    type('Nur für uns');
    const post = http.expectOne(url('/comments'));
    expect(post.request.body).toEqual({ body: 'Nur für uns', visibility: 'internal' });
    post.flush({ ...OWN, body: 'Nur für uns' });
    detectChanges();
    expect(within(group).getByRole('radio', { name: 'Intern' })).toHaveAttribute('aria-checked', 'true');
    // Both kinds exist: the internal comment carries its mark.
    expect(document.querySelector('.chat__mark--internal')).toHaveTextContent('Intern');
    http.verify();
  });

  it('sends a comment with a file only, and shows the files of the comments', async () => {
    const withFile: CommentOutWire = {
      ...COMMENTS[0],
      attachments: [{ id: 'f1', filename: 'kosten.pdf', mime: 'application/pdf', size: 2048, scanState: 'clean' }],
    };
    const { http, input, detectChanges, fixture } = await loaded(undefined, [withFile]);
    expect(screen.getByRole('link', { name: /kosten\.pdf/ })).toHaveAttribute('href', '/api/attachments/f1/download');

    const box = fixture.nativeElement.querySelector('.chat__fileInput') as HTMLInputElement;
    const file = new File(['%PDF'], 'angebot.pdf', { type: 'application/pdf' });
    Object.defineProperty(box, 'files', { value: [file], configurable: true });
    fireEvent.change(box);
    const upload = http.expectOne('/api/apply/attachments');
    expect(upload.request.headers.has('X-Draft-Token')).toBe(false);
    upload.flush({
      id: 'd1',
      filename: 'angebot.pdf',
      mime: 'application/pdf',
      size: 4,
      scanned: false,
      is_comparison_offer: false,
      draftToken: 'tok',
      draftExpiresAt: '2999-01-01T00:00:00Z',
    });
    await new Promise((r) => setTimeout(r));
    detectChanges();
    expect(screen.getByRole('button', { name: 'angebot.pdf entfernen' })).toBeInTheDocument();

    fireEvent.keyDown(input(), { key: 'Enter' });
    detectChanges();
    const post = http.expectOne(url('/comments'));
    expect(post.request.body).toEqual({ body: '', visibility: 'public', attachmentIds: ['d1'], draftToken: 'tok' });
    // The pending message shows the file, still in the scan, as no link.
    expect(screen.getByText('In Prüfung')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'angebot.pdf entfernen' })).not.toBeInTheDocument();
    post.flush({
      ...OWN,
      id: 'c3',
      body: '',
      visibility: 'public',
      attachments: [{ id: 'd1', filename: 'angebot.pdf', mime: 'application/pdf', size: 4, scanState: 'scanning' }],
    });
    detectChanges();
    expect(screen.queryByRole('link', { name: /angebot\.pdf/ })).not.toBeInTheDocument();
    http.verify();
  });

  it('keeps a failed comment and sends it again', async () => {
    const { http, type, detectChanges } = await loaded();
    type('Hmm');
    http.expectOne(url('/comments')).flush({ title: 'Boom' }, { status: 500, statusText: 'Server Error' });
    detectChanges();
    expect(screen.getByText('Nicht gesendet')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Erneut senden' }));
    http.expectOne(url('/comments')).flush({ ...OWN, body: 'Hmm', visibility: 'public' });
    detectChanges();
    expect(screen.queryByText('Nicht gesendet')).not.toBeInTheDocument();
    expect(screen.getByText('Hmm')).toBeInTheDocument();
    http.verify();
  });

  it('patches only the body of an own comment', async () => {
    const { http, detectChanges, cmp } = await loaded(undefined, [COMMENTS[0], OWN]);
    // A manager may change both comments; the second one is the own.
    fireEvent.click(screen.getAllByRole('button', { name: 'Nachricht bearbeiten' })[1]);
    const box = screen.getByRole('textbox', { name: 'Nachricht bearbeiten' });
    fireEvent.input(box, { target: { value: '  Neuer Text  ' } });
    fireEvent.keyDown(box, { key: 'Enter' });
    const patch = http.expectOne(url('/comments/c2'));
    expect(patch.request.method).toBe('PATCH');
    expect(patch.request.body).toEqual({ body: 'Neuer Text' });
    patch.flush({ ...OWN, body: 'Neuer Text' });
    detectChanges();
    expect(cmp.comments()[1].body).toBe('Neuer Text');
    http.verify();
  });

  it.each([
    [403, 'Nur die verfassende Person oder eine Antragsverwaltung darf diesen Kommentar ändern.'],
    [404, 'Dieser Kommentar existiert nicht mehr.'],
    [500, 'Kommentar konnte nicht gespeichert werden.'],
  ])('explains a %s on the comment patch', async (status, message) => {
    const { http, toast, cmp } = await loaded(undefined, [OWN]);
    const error = jest.spyOn(toast, 'error');
    const restore = jest.fn();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (cmp as any).editComment({ id: 'c2', body: 'x', restore });
    expect(restore).not.toHaveBeenCalled();
    http.expectOne(url('/comments/c2')).flush({ title: 'e' }, { status, statusText: 'x' });
    expect(error).toHaveBeenCalledWith(message);
    // The chat opens the edit again with the text, so nothing typed is lost.
    expect(restore).toHaveBeenCalledTimes(1);
    expect(cmp.comments()[0].body).toBe('Mein Text');
    http.verify();
  });

  it('keeps the new text in the edit when the server refuses it', async () => {
    const { http, detectChanges, fixture } = await loaded(undefined, [COMMENTS[0]]);
    fireEvent.click(screen.getByRole('button', { name: 'Nachricht bearbeiten' }));
    const box = screen.getByRole('textbox', { name: 'Nachricht bearbeiten' });
    fireEvent.input(box, { target: { value: 'Lange neue Fassung' } });
    fireEvent.keyDown(box, { key: 'Enter' });
    http.expectOne(url('/comments/c1')).flush({ title: 'e' }, { status: 500, statusText: 'x' });
    detectChanges();
    await fixture.whenStable();
    expect(screen.getByRole('textbox', { name: 'Nachricht bearbeiten' })).toHaveValue('Lange neue Fassung');
    http.verify();
  });

  it('lets a holder of application.manage edit and delete a comment of another person', async () => {
    const { http, detectChanges, cmp } = await loaded(undefined, [COMMENTS[0]]);
    fireEvent.click(screen.getByRole('button', { name: 'Nachricht bearbeiten' }));
    const box = screen.getByRole('textbox', { name: 'Nachricht bearbeiten' });
    fireEvent.input(box, { target: { value: 'Korrigiert' } });
    fireEvent.keyDown(box, { key: 'Enter' });
    const patch = http.expectOne(url('/comments/c1'));
    expect(patch.request.method).toBe('PATCH');
    patch.flush({ ...COMMENTS[0], body: 'Korrigiert' });
    detectChanges();
    expect(cmp.comments()[0].body).toBe('Korrigiert');

    fireEvent.click(screen.getByRole('button', { name: 'Nachricht löschen' }));
    const dialog = screen.getByRole('dialog', { name: 'Nachricht löschen' });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Löschen' }));
    const del = http.expectOne(url('/comments/c1'));
    expect(del.request.method).toBe('DELETE');
    del.flush(null, { status: 204, statusText: 'No Content' });
    detectChanges();
    expect(cmp.comments()).toEqual([]);
    http.verify();
  });

  it('lists the to-dos linked to the application in the details', async () => {
    await loaded();
    expect(document.querySelector('app-todo-linked-list[kind="application"]')).not.toBeNull();
  });

  it('offers no edit or delete on a comment of another person without application.manage', async () => {
    await loaded(['application.read'], [COMMENTS[0], OWN]);
    expect(screen.getAllByRole('button', { name: 'Nachricht bearbeiten' })).toHaveLength(1);
    expect(screen.getAllByRole('button', { name: 'Nachricht löschen' })).toHaveLength(1);
  });

  it('deletes an own comment after the confirmation', async () => {
    const { http, detectChanges, cmp } = await loaded(undefined, [OWN]);
    fireEvent.click(screen.getByRole('button', { name: 'Nachricht löschen' }));
    const dialog = screen.getByRole('dialog', { name: 'Nachricht löschen' });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Löschen' }));
    const del = http.expectOne(url('/comments/c2'));
    expect(del.request.method).toBe('DELETE');
    del.flush(null, { status: 204, statusText: 'No Content' });
    detectChanges();
    expect(cmp.comments()).toEqual([]);
    http.verify();
  });

  it('reports a failed delete and keeps the comment', async () => {
    const { http, toast, cmp } = await loaded(undefined, [OWN]);
    const error = jest.spyOn(toast, 'error');
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (cmp as any).deleteComment({ id: 'c2' });
    http.expectOne(url('/comments/c2')).flush({ title: 'e' }, { status: 403, statusText: 'x' });
    expect(error).toHaveBeenCalledWith(
      'Nur die verfassende Person oder eine Antragsverwaltung darf diesen Kommentar ändern.',
    );
    expect(cmp.comments()).toHaveLength(1);
    http.verify();
  });
});
