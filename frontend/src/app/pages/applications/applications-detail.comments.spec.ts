/**
 * Comment edit and delete on the application detail page.
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
import { render, screen } from '@testing-library/angular';
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
