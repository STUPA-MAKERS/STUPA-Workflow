/**
 * Comment edit/delete and the PDF render job of the application detail page.
 *
 * These live in their own spec file. The base spec of the same component is
 * already large, and one file with both blocks pushes the first TestBed compile
 * of this component over the default jest timeout under `--coverage`.
 */
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
import { ToastService } from '@stupa-makers/ui-kit';
import type { ApplicationOutWire, CommentOutWire, StateOutWire, VersionOutWire } from '@core/api/models';

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
  };
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

/** Answer every request of one page load. */
function flushAll(http: HttpTestingController, id = 'app-1') {
  http.expectOne(url('', id)).flush({ ...appWire(), id });
  http.expectOne(url('/versions', id)).flush(VERSIONS);
  http.expectOne(url('/comments', id)).flush(COMMENTS);
  for (const req of http.match((r) => r.method === 'GET' && r.url === '/api/budgets')) {
    req.flush([]);
  }
  flushForm(http, id);
}

/** The attachments panel loads on render. An empty answer is fine. */
function flushAttachments(http: HttpTestingController) {
  for (const req of http.match((r) => r.method === 'GET' && /\/attachments$/.test(r.url))) {
    req.flush([]);
  }
  for (const req of http.match((r) => r.method === 'GET' && r.url === '/api/budgets')) {
    req.flush([]);
  }
}

// --- comment edit / delete -------------------------------------------------

/** A pending render job as the POST returns it. */
const PENDING_JOB = {
  id: 'job-1',
  kind: 'application_pdf',
  status: 'pending',
  applicationId: 'app-1',
  resultUrl: null,
  error: null,
};

describe('ApplicationsDetailComponent — comment edit and delete', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('offers edit and delete for an own comment', async () => {
    const { http, detectChanges } = await setup(['application.read']);
    http.expectOne(url('')).flush(appWire());
    http.expectOne(url('/versions')).flush(VERSIONS);
    http.expectOne(url('/comments')).flush([{ ...COMMENTS[0], isOwn: true }]);
    flushForm(http);
    detectChanges();

    expect(screen.getByRole('button', { name: 'Kommentar bearbeiten' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Kommentar löschen' })).toBeInTheDocument();
    flushAttachments(http);
    http.verify();
  });

  it('hides both controls for a foreign comment without application.manage', async () => {
    const { http, detectChanges } = await setup(['application.read']);
    http.expectOne(url('')).flush(appWire());
    http.expectOne(url('/versions')).flush(VERSIONS);
    http.expectOne(url('/comments')).flush(COMMENTS);
    flushForm(http);
    detectChanges();

    expect(screen.queryByRole('button', { name: 'Kommentar bearbeiten' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Kommentar löschen' })).not.toBeInTheDocument();
    flushAttachments(http);
    http.verify();
  });

  it('offers both controls on a foreign comment for a manager', async () => {
    const { http, detectChanges } = await setup();
    flushAll(http);
    detectChanges();

    expect(screen.getByRole('button', { name: 'Kommentar bearbeiten' })).toBeInTheDocument();
    flushAttachments(http);
    http.verify();
  });

  it('patches only the body and replaces the comment in the list', async () => {
    const { http, detectChanges, cmp, toast } = await setup();
    flushAll(http);
    detectChanges();
    flushAttachments(http);
    const success = jest.spyOn(toast, 'success');
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = cmp as any;

    c.openEditComment(cmp.comments()[0]);
    c.commentDraft.set('  Neuer Text  ');
    c.saveComment();

    const patch = http.expectOne(url('/comments/c1'));
    expect(patch.request.method).toBe('PATCH');
    expect(patch.request.body).toEqual({ body: 'Neuer Text' });
    patch.flush({ ...COMMENTS[0], body: 'Neuer Text' });
    detectChanges();

    expect(cmp.comments()[0].body).toBe('Neuer Text');
    expect(c.editingComment()).toBeNull();
    expect(success).toHaveBeenCalledWith('Kommentar aktualisiert.');
    http.verify();
  });

  it.each([
    [403, 'Nur die verfassende Person oder eine Antragsverwaltung darf diesen Kommentar ändern.'],
    [404, 'Dieser Kommentar existiert nicht mehr.'],
    [500, 'Kommentar konnte nicht gespeichert werden.'],
  ])('explains a %s on the comment patch', async (status, message) => {
    const { http, detectChanges, cmp, toast } = await setup();
    flushAll(http);
    detectChanges();
    flushAttachments(http);
    const error = jest.spyOn(toast, 'error');
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = cmp as any;

    c.openEditComment(cmp.comments()[0]);
    c.saveComment();
    http.expectOne(url('/comments/c1')).flush({ title: 'e' }, { status, statusText: 'x' });
    expect(error).toHaveBeenCalledWith(message);
    expect(c.savingComment()).toBe(false);
    http.verify();
  });

  it('deletes a comment and drops it from the list', async () => {
    const { http, detectChanges, cmp, toast } = await setup();
    flushAll(http);
    detectChanges();
    flushAttachments(http);
    const success = jest.spyOn(toast, 'success');
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = cmp as any;

    c.askDeleteComment(cmp.comments()[0]);
    c.doDeleteComment();
    const del = http.expectOne(url('/comments/c1'));
    expect(del.request.method).toBe('DELETE');
    del.flush(null, { status: 204, statusText: 'No Content' });
    detectChanges();

    expect(cmp.comments()).toEqual([]);
    expect(success).toHaveBeenCalledWith('Kommentar gelöscht.');
    http.verify();
  });

  it('reports a failed comment delete and keeps the comment', async () => {
    const { http, detectChanges, cmp, toast } = await setup();
    flushAll(http);
    detectChanges();
    flushAttachments(http);
    const error = jest.spyOn(toast, 'error');
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = cmp as any;

    c.askDeleteComment(cmp.comments()[0]);
    c.doDeleteComment();
    http.expectOne(url('/comments/c1')).flush({ title: 'e' }, { status: 403, statusText: 'x' });
    expect(error).toHaveBeenCalledWith(
      'Nur die verfassende Person oder eine Antragsverwaltung darf diesen Kommentar ändern.',
    );
    expect(cmp.comments().length).toBe(1);
    http.verify();
  });

  it('ignores save and delete without a target, an empty body, or while busy', async () => {
    const { http, detectChanges, cmp } = await setup();
    flushAll(http);
    detectChanges();
    flushAttachments(http);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = cmp as any;

    c.saveComment();
    c.doDeleteComment();

    c.openEditComment(cmp.comments()[0]);
    c.commentDraft.set('   ');
    c.saveComment();
    c.commentDraft.set('x');
    c.savingComment.set(true);
    c.saveComment();
    c.closeEditComment();
    expect(c.editingComment()).toBeNull();

    c.askDeleteComment(cmp.comments()[0]);
    c.removingComment.set(true);
    c.doDeleteComment();
    http.verify();
  });
});

// --- PDF render ------------------------------------------------------------

describe('ApplicationsDetailComponent — PDF render', () => {
  beforeEach(() => {
    localStorage.setItem('ap.locale', 'de');
    jest.useFakeTimers();
  });
  afterEach(() => {
    jest.runOnlyPendingTimers();
    jest.useRealTimers();
  });

  /** Load the page and start a render. Returns the flushed POST. */
  async function startRender(permissions?: string[]) {
    const ctx = await setup(permissions);
    flushAll(ctx.http);
    ctx.detectChanges();
    flushAttachments(ctx.http);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = ctx.cmp as any;
    c.startPdf();
    return { ...ctx, c };
  }

  it('starts the job, polls it and offers the finished PDF', async () => {
    const { http, detectChanges, c } = await startRender();
    const post = http.expectOne(url('/pdf'));
    expect(post.request.method).toBe('POST');
    post.flush(PENDING_JOB, { status: 202, statusText: 'Accepted' });
    detectChanges();
    expect(screen.getByText('Der Auftrag wartet auf die Bearbeitung …')).toBeInTheDocument();

    jest.advanceTimersByTime(2000);
    http.expectOne('/api/jobs/job-1').flush({ ...PENDING_JOB, status: 'running' });
    detectChanges();
    expect(screen.getByText('Das PDF wird erzeugt …')).toBeInTheDocument();

    jest.advanceTimersByTime(2000);
    http
      .expectOne('/api/jobs/job-1')
      .flush({ ...PENDING_JOB, status: 'done', resultUrl: 'https://minio/x.pdf' });
    detectChanges();

    expect(c.pdfDone()).toBe(true);
    expect(screen.getByRole('link', { name: 'PDF öffnen' })).toHaveAttribute(
      'href',
      'https://minio/x.pdf',
    );
    http.verify();
  });

  it('says so when the job finished but the store gave no link', async () => {
    const { http, detectChanges } = await startRender();
    http.expectOne(url('/pdf')).flush({ ...PENDING_JOB, status: 'done' });
    detectChanges();
    expect(
      screen.getByText(/Dateispeicher liefert keinen Link/),
    ).toBeInTheDocument();
    http.verify();
  });

  it.each([
    ['render_error', 'Das PDF konnte nicht gesetzt werden.'],
    ['no_application', 'Der Antrag zum Auftrag existiert nicht mehr.'],
    ['render_unavailable', 'Der PDF-Dienst ist derzeit nicht erreichbar.'],
    ['weird_code', 'Der PDF-Auftrag ist fehlgeschlagen.'],
  ])('explains the failure code %s', async (code, message) => {
    const { http, detectChanges } = await startRender();
    http.expectOne(url('/pdf')).flush({ ...PENDING_JOB, status: 'failed', error: code });
    detectChanges();
    expect(screen.getByText(message)).toBeInTheDocument();
    // A failed job can be started again from the dialog.
    expect(screen.getByRole('button', { name: 'Neu starten' })).toBeInTheDocument();
    http.verify();
  });

  it.each([
    [403, 'Keine Berechtigung, für diesen Antrag ein PDF zu erzeugen.'],
    [500, 'Der PDF-Auftrag konnte nicht gestartet werden.'],
  ])('reports a %s on the start', async (status, message) => {
    const { http, detectChanges, c } = await startRender();
    http.expectOne(url('/pdf')).flush({ title: 'e' }, { status, statusText: 'x' });
    detectChanges();
    expect(screen.getByText(message)).toBeInTheDocument();
    expect(c.pdfPolling()).toBe(false);
    http.verify();
  });

  it('reports a broken poll and checks again on demand', async () => {
    const { http, detectChanges, c } = await startRender();
    http.expectOne(url('/pdf')).flush(PENDING_JOB, { status: 202, statusText: 'Accepted' });
    jest.advanceTimersByTime(2000);
    http.expectOne('/api/jobs/job-1').flush({ title: 'e' }, { status: 502, statusText: 'x' });
    detectChanges();
    expect(screen.getByText('Der Status des Auftrags ist nicht abrufbar.')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Erneut prüfen' }), {
      advanceTimers: jest.advanceTimersByTime,
    });
    http
      .expectOne('/api/jobs/job-1')
      .flush({ ...PENDING_JOB, status: 'done', resultUrl: 'https://minio/x.pdf' });
    detectChanges();
    expect(c.pdfDone()).toBe(true);
    http.verify();
  });

  it('gives up after the poll window and stays honest about it', async () => {
    const { http, detectChanges, c } = await startRender();
    http.expectOne(url('/pdf')).flush(PENDING_JOB, { status: 202, statusText: 'Accepted' });
    for (let i = 0; i < 60; i++) {
      jest.advanceTimersByTime(2000);
      http.expectOne('/api/jobs/job-1').flush({ ...PENDING_JOB, status: 'running' });
    }
    detectChanges();
    expect(c.pdfTimedOut()).toBe(true);
    expect(c.pdfPolling()).toBe(false);
    expect(screen.getByText(/Der Auftrag läuft noch/)).toBeInTheDocument();
    // No further poll is scheduled.
    jest.advanceTimersByTime(10_000);
    http.verify();
  });

  it('stops the poll on close and on a navigation to another application', async () => {
    const paramMap$ = new BehaviorSubject(convertToParamMap({ id: 'app-1' }));
    const ctx = await setup(undefined, paramMap$);
    flushAll(ctx.http);
    ctx.detectChanges();
    flushAttachments(ctx.http);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = ctx.cmp as any;

    c.startPdf();
    ctx.http.expectOne(url('/pdf')).flush(PENDING_JOB, { status: 202, statusText: 'Accepted' });
    c.closePdf();
    expect(c.pdfOpen()).toBe(false);
    jest.advanceTimersByTime(10_000);

    c.startPdf();
    ctx.http.expectOne(url('/pdf')).flush(PENDING_JOB, { status: 202, statusText: 'Accepted' });
    paramMap$.next(convertToParamMap({ id: 'app-2' }));
    expect(c.pdfJob()).toBeNull();
    jest.advanceTimersByTime(10_000);
    flushAll(ctx.http, 'app-2');
    ctx.detectChanges();
    flushAttachments(ctx.http);
    ctx.http.verify();
  });

  it('ignores a second start while one runs and a poll without a job', async () => {
    const { http, c } = await startRender();
    c.startPdf();
    http.expectOne(url('/pdf')).flush(PENDING_JOB, { status: 202, statusText: 'Accepted' });
    c.closePdf();
    c.pdfJob.set(null);
    c.pollPdf();
    http.verify();
    // ngOnDestroy clears a pending timer without a leak.
    c.ngOnDestroy();
  });
});
