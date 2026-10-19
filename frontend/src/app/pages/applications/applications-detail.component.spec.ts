import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { ActivatedRoute, convertToParamMap, provideRouter, Router } from '@angular/router';
import { fireEvent, render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { BehaviorSubject } from 'rxjs';
import { ApplicationsDetailComponent } from './applications-detail.component';
import { ApplicationsPageService } from './applications-page.service';
import { DraftAttachmentsService } from '../../features/apply/draft-attachments.service';
import { RailStatusService } from '../../layout/rail-status.service';
import { TestBed } from '@angular/core/testing';
import { AuthService } from '@core/auth/auth.service';
import { USE_MOCK_API } from '@core/api/api.config';
import { ToastService } from '@stupa-makers/ui-kit';
import { provideFormly } from '@shared/formly/formly.providers';
import type {
  Application,
  ApplicationComment,
  ApplicationOutWire,
  CommentOutWire,
  FormFieldDef,
  StateOutWire,
  Transition,
  VersionOutWire,
} from '@core/api/models';
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
    // Mirrors the real AuthService: the admin role holds every permission.
    can: (p: string) => roles.includes('admin') || permissions.includes(p),
    roles: (() => roles) as unknown as AuthService['roles'],
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
  roles: string[] = [],
) {
  const view = await render(ApplicationsDetailComponent, {
    providers: [
      NO_LINKED_TODOS,
      provideRouter([]),
      provideHttpClient(),
      provideHttpClientTesting(),
      provideFormly(),
      { provide: USE_MOCK_API, useValue: false },
      { provide: AuthService, useValue: fakeAuth(permissions, roles) },
      // The real service polls; the page only asks it to refresh.
      { provide: RailStatusService, useValue: { refresh: jest.fn() } },
      {
        provide: ActivatedRoute,
        useValue: { paramMap: paramMap$, fragment: new BehaviorSubject<string | null>(null), snapshot: { fragment: null } },
      },
      // Side by side with the list: every section shows at once, no tabs.
      { provide: ApplicationsPageService, useFactory: splitPage },
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

/** Flush an effective form that defines a `date` and a `daterange` field. */
function flushDateForm(http: HttpTestingController, id = 'app-1') {
  http
    .expectOne((r) => r.url === `/api/applications/${id}/form`)
    .flush({
      applicationTypeId: 't1',
      formVersionId: 'fv1',
      sections: [
        {
          key: 'main',
          label: { de: 'Antrag' },
          fields: [
            { key: 'span', type: 'daterange', label: { de: 'Zeitraum' } },
            { key: 'eventDay', type: 'date', label: { de: 'Tag' } },
          ],
        },
      ],
    });
}

// The form loads on the initial load only. A refresh does not reload the form.
// A status change runs through the flow, so no further /transitions request follows.
function flushAll(http: HttpTestingController, id = 'app-1', form = true) {
  flushTypes(http);
  http.expectOne(url('', id)).flush({ ...appWire(), id });
  http.expectOne(url('/versions', id)).flush(VERSIONS);
  http.expectOne(url('/comments', id)).flush(COMMENTS);
  // A manager also loads the cost-centre tree. An empty answer is fine.
  for (const req of http.match((r) => r.method === 'GET' && r.url === '/api/budgets')) {
    req.flush([]);
  }
  if (form) flushForm(http, id);
}

// The attachments panel loads the attachments on render. An empty answer is fine.
function flushAttachments(http: HttpTestingController) {
  flushTypes(http);
  for (const req of http.match(
    (r) => r.method === 'GET' && /\/(attachments|timeline|mentionable)$/.test(r.url),
  )) {
    req.flush([]);
  }
  // A manager also loads the cost-centre tree. An empty answer is fine.
  for (const req of http.match((r) => r.method === 'GET' && r.url === '/api/budgets')) {
    req.flush([]);
  }
}

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

describe('ApplicationsDetailComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  // jsdom has no structuredClone. startEdit relies on the browser global.
  const g = globalThis as unknown as { structuredClone?: <T>(v: T) => T };
  const savedClone = g.structuredClone;
  beforeAll(() => {
    g.structuredClone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
  });
  afterAll(() => {
    g.structuredClone = savedClone;
  });

  it('renders the header, data fields, version diff and comments', async () => {
    const { http, detectChanges, cmp } = await setup();
    flushAll(http);
    cmp.commentsOpen.set(true);
    detectChanges();

    expect(screen.getByRole('heading', { name: 'Förderung Fest', level: 2 })).toBeInTheDocument();
    expect(screen.getByText('Eingereicht')).toBeInTheDocument();
    // "Version 2" shows in the header and again as a history entry.
    expect(screen.getAllByText('Version 2').length).toBeGreaterThan(0);
    expect(screen.getByText('Mia')).toBeInTheDocument();
    // The history starts collapsed. Expand it to make the diff visible.
    detectChanges();
    expect(screen.getByText('Fest')).toBeInTheDocument();
    expect(screen.getByText('Bitte Kostenplan ergänzen.')).toBeInTheDocument();
    flushAttachments(http);
    http.verify();
  });

  it('uploads a file dropped anywhere on the application as an attachment', async () => {
    const { http, detectChanges, container, cmp, fixture } = await setup();
    flushAll(http);
    detectChanges();
    flushAttachments(http);
    const page = container.querySelector('article.ad') as HTMLElement;
    const frame = () => container.querySelector('app-drop-overlay');
    // The panel is no target of its own: the page shows one frame.
    const panel = container.querySelector('.att') as HTMLElement;
    fireEvent.dragEnter(panel, { dataTransfer: { types: ['Files'] } });
    detectChanges();
    expect(frame()).toHaveTextContent('Dateien zum Hochladen ablegen');
    expect(container.querySelectorAll('app-drop-overlay')).toHaveLength(1);

    const pdf = new File(['x'], 'drop.pdf', { type: 'application/pdf' });
    fireEvent.drop(page, { dataTransfer: { types: ['Files'], files: [pdf] } });
    detectChanges();
    expect(frame()).toBeNull();
    http
      .expectOne((r) => r.method === 'POST' && r.url === '/api/applications/app-1/attachments')
      .flush({ id: 'd', filename: 'drop.pdf', mime: 'application/pdf', size: 1, scanned: false, is_comparison_offer: false });
    detectChanges();
    expect(screen.getByText('drop.pdf')).toBeInTheDocument();

    // In tabs, the drop opens the tab "Anhänge".
    const pageService = fixture.debugElement.injector.get(ApplicationsPageService);
    pageService.split.set(false);
    detectChanges();
    cmp.onFilesDropped([]);
    expect(cmp.tab()).toBe('files');
    pageService.split.set(true);
    // With the comments open, the chat takes its own drop.
    cmp.commentsOpen.set(true);
    detectChanges();
    expect(fireEvent.dragEnter(page, { dataTransfer: { types: ['Files'] } })).toBe(true);
    flushAttachments(http);
    http.verify();
  });

  it('takes no drop without the right to manage the application', async () => {
    const { http, detectChanges, container } = await setup(['application.read']);
    flushAll(http);
    detectChanges();
    flushAttachments(http);
    const page = container.querySelector('article.ad') as HTMLElement;
    expect(fireEvent.dragEnter(page, { dataTransfer: { types: ['Files'] } })).toBe(true);
    detectChanges();
    expect(container.querySelector('app-drop-overlay')).toBeNull();
    http.verify();
  });

  it('marks an edited comment as "bearbeitet", from the list and from the edit answer', async () => {
    const { http, detectChanges, cmp, container } = await setup();
    flushTypes(http);
    http.expectOne(url('')).flush(appWire());
    http.expectOne(url('/versions')).flush(VERSIONS);
    http.expectOne(url('/comments')).flush([
      ...COMMENTS,
      { ...COMMENTS[0], id: 'c2', body: 'Erledigt.', at: '2026-06-05T12:05:00Z', editedAt: '2026-06-05T12:30:00Z' },
    ]);
    for (const req of http.match((r) => r.method === 'GET' && r.url === '/api/budgets')) req.flush([]);
    flushForm(http);
    cmp.commentsOpen.set(true);
    detectChanges();
    const edited = () => [...container.querySelectorAll('.chat__meta')].filter((m) => /bearbeitet/.test(m.textContent ?? ''));
    expect(edited()).toHaveLength(1);

    (cmp as unknown as { editComment(e: { id: string; body: string }): void }).editComment({ id: 'c1', body: 'Neu' });
    http
      .expectOne((r) => r.method === 'PATCH' && r.url === '/api/applications/app-1/comments/c1')
      .flush({ ...COMMENTS[0], body: 'Neu', editedAt: '2026-06-05T13:00:00Z' });
    detectChanges();
    expect(screen.getByText('Neu')).toBeInTheDocument();
    expect(edited()).toHaveLength(2);
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
    detectChanges();
    expect(screen.getByText('Keine Feldänderungen.')).toBeInTheDocument();
    flushForm(http);
    flushAttachments(http);
    http.verify();
  });

  it('shows a date and a date range in the version diff as days, not as JSON', async () => {
    const { http, detectChanges } = await setup();
    http.expectOne(url('')).flush(appWire());
    http.expectOne(url('/versions')).flush([
      VERSIONS[0],
      {
        version: 2,
        data: {},
        diff: {
          added: { eventDay: '2026-07-01' },
          removed: {},
          changed: {
            span: {
              old: { from: '2026-06-01', to: '2026-06-02' },
              new: { from: '2026-07-01', to: '2026-07-02' },
            },
          },
        },
        changedBy: 'Mia',
        at: '2026-06-05T11:00:00Z',
      },
    ]);
    http.expectOne(url('/comments')).flush([]);
    flushDateForm(http);
    detectChanges();
    detectChanges();

    expect(screen.getByText('01.06.2026 – 02.06.2026')).toBeInTheDocument();
    expect(screen.getByText('01.07.2026 – 02.07.2026')).toBeInTheDocument();
    expect(screen.getByText('01.07.2026')).toBeInTheDocument();
    // Neither the raw JSON of the range nor the raw ISO day reaches the reader.
    expect(screen.queryAllByText(/\{"from"/)).toHaveLength(0);
    expect(screen.queryAllByText(/2026-07-01/)).toHaveLength(0);
    flushAttachments(http);
    http.verify();
  });

  it('keeps a diff value raw when the active form defines no such field', async () => {
    const { http, detectChanges } = await setup();
    http.expectOne(url('')).flush(appWire());
    http.expectOne(url('/versions')).flush([
      VERSIONS[0],
      {
        version: 2,
        data: {},
        diff: {
          added: {},
          removed: { legacyRange: { from: '2026-05-01', to: '2026-05-02' } },
          changed: { legacyNote: { old: 'alt', new: 'neu' } },
        },
        changedBy: 'Mia',
        at: '2026-06-05T11:00:00Z',
      },
    ]);
    http.expectOne(url('/comments')).flush([]);
    flushDateForm(http);
    detectChanges();
    detectChanges();

    // A field the active form version dropped keeps the stored text. No crash and no
    // "Invalid Date". A dropped object (the old range) shows only its name.
    expect(screen.getByText(/legacyRange/)).toBeInTheDocument();
    expect(screen.queryAllByText(/\{"from"/)).toHaveLength(0);
    expect(screen.getByText('alt')).toBeInTheDocument();
    expect(screen.getByText('neu')).toBeInTheDocument();
    expect(screen.queryAllByText(/Invalid Date/)).toHaveLength(0);
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

    // Simulate a detail-to-detail navigation. The component instance stays the same.
    paramMap$.next(convertToParamMap({ id: 'app-2' }));
    // A fresh detail GET for app-2 must fire. A snapshot would have stayed on app-1.
    http.expectOne(url('', 'app-2')).flush({ ...appWire(), id: 'app-2' });
    http.expectOne(url('/versions', 'app-2')).flush(VERSIONS);
    http.expectOne(url('/comments', 'app-2')).flush(COMMENTS);
    flushForm(http, 'app-2'); // loadApplication for app-2 also fetches the effective form.
    detectChanges();

    expect(screen.getByRole('heading', { level: 2 })).toBeInTheDocument();
    flushAttachments(http);
    http.verify();
  });

  it('draws the loaded sheet with bars while it loads: header, columns, fixed headings', async () => {
    const { http, container } = await setup([
      'application.read',
      'application.manage',
      'application.transition',
    ]);
    const busy = container.querySelector('article.ad--busy')!;
    // Side by side the busy sheet is the sheet itself, with its surface (`ad--split`).
    expect(busy).toHaveClass('ad--split');
    expect(busy).toHaveAttribute('aria-busy', 'true');
    expect(busy.querySelector('.ad__head .ad__title .skel-text')).not.toBeNull();
    expect(busy.querySelector('.ad__head .ad__line .skel-text')).not.toBeNull();
    // With the right to fire transitions, two button places in the header.
    expect(busy.querySelectorAll('.ad__transitions .ad__skelButton')).toHaveLength(2);
    expect(busy.querySelectorAll('.ad__cols > .ad__col')).toHaveLength(2);
    // Fixed headings are text, headings of the form are bars.
    expect(within(busy as HTMLElement).getByText('Details')).toBeInTheDocument();
    expect(within(busy as HTMLElement).getByText('Verlauf')).toBeInTheDocument();
    expect(busy.querySelector('.ad__skelAnswers h3 .skel-text')).not.toBeNull();
    http.expectOne(url('')).flush(appWire());
    flushAttachments(http);
  });

  it('draws the tabs while it loads in one column', async () => {
    const view = await render(ApplicationsDetailComponent, {
      providers: [
        NO_LINKED_TODOS,
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: false },
        { provide: AuthService, useValue: fakeAuth(['application.read']) },
        { provide: RailStatusService, useValue: { refresh: jest.fn() } },
        {
          provide: ActivatedRoute,
          useValue: {
            paramMap: new BehaviorSubject(convertToParamMap({ id: 'app-1' })),
            fragment: new BehaviorSubject<string | null>(null),
            snapshot: { fragment: null },
          },
        },
      ],
    });
    view.fixture.detectChanges();
    const busy = view.container.querySelector('article.ad--busy')!;
    expect(busy).not.toHaveClass('ad--split');
    expect(busy.querySelector('app-tabs')).not.toBeNull();
    // Without the right to fire transitions the header has no button row.
    expect(busy.querySelector('.ad__transitions')).toBeNull();
    const http = view.fixture.debugElement.injector.get(HttpTestingController);
    for (const req of http.match(() => true)) req.flush(null, { status: 404, statusText: 'x' });
  });

  it('keeps the shown application on a switch, dimmed and inert, until the next arrives', async () => {
    const paramMap$ = new BehaviorSubject(convertToParamMap({ id: 'app-1' }));
    const { http, detectChanges, cmp, container } = await setup(
      ['application.read', 'application.manage'],
      paramMap$,
    );
    flushAll(http);
    detectChanges();
    flushAttachments(http);
    cmp.editing.set(true);

    paramMap$.next(convertToParamMap({ id: 'app-2' }));
    detectChanges();
    const req = http.expectOne(url('', 'app-2'));
    // No placeholder: the first application stays, the edit and its dialogs close.
    expect(cmp.switching()).toBe(true);
    expect(cmp.loading()).toBe(false);
    expect(cmp.editing()).toBe(false);
    expect(cmp.app()?.id).toBe('app-1');
    expect(container.querySelector('article.ad--busy')).toBeNull();
    const sheet = container.querySelector('article.ad')!;
    expect(sheet).toHaveClass('ad--stale');
    expect(sheet).toHaveAttribute('inert');
    expect(sheet).toHaveAttribute('aria-busy', 'true');
    expect(sheet.querySelector('.ad__progress')).not.toBeNull();

    req.flush({ ...appWire(), id: 'app-2' });
    http.expectOne(url('/versions', 'app-2')).flush(VERSIONS);
    http.expectOne(url('/comments', 'app-2')).flush(COMMENTS);
    flushForm(http, 'app-2');
    detectChanges();
    expect(cmp.switching()).toBe(false);
    expect(cmp.app()?.id).toBe('app-2');
    const fresh = container.querySelector('article.ad')!;
    expect(fresh).not.toHaveClass('ad--stale');
    expect(fresh).not.toHaveAttribute('inert');
    expect(fresh.querySelector('.ad__progress')).toBeNull();
    flushAttachments(http);
    http.verify();
  });

  it('replaces the shown application with the error when the switch fails', async () => {
    const paramMap$ = new BehaviorSubject(convertToParamMap({ id: 'app-1' }));
    const { http, detectChanges, cmp } = await setup(['application.read'], paramMap$);
    flushAll(http);
    detectChanges();
    flushAttachments(http);

    paramMap$.next(convertToParamMap({ id: 'app-2' }));
    http.expectOne(url('', 'app-2')).flush({ title: 'Gone' }, { status: 404, statusText: 'Not Found' });
    detectChanges();
    expect(cmp.switching()).toBe(false);
    expect(cmp.app()).toBeNull();
    expect(cmp.notFound()).toBe(true);
    flushAttachments(http);
    http.verify();
  });

  it('keeps the place of the transition buttons while they load', async () => {
    const { http, detectChanges, cmp, container } = await setup([
      'application.read',
      'application.manage',
      'application.transition',
    ]);
    http.expectOne(url('')).flush(appWire());
    http.expectOne(url('/versions')).flush(VERSIONS);
    http.expectOne(url('/comments')).flush(COMMENTS);
    flushForm(http);
    detectChanges();
    const req = http.expectOne(url('/transitions'));
    expect(cmp.transitionsLoading()).toBe(true);
    expect(container.querySelectorAll('.ad__head .ad__skelButton')).toHaveLength(2);
    req.flush([]);
    detectChanges();
    expect(cmp.transitionsLoading()).toBe(false);
    // No transition: the row goes away.
    expect(container.querySelector('.ad__head .ad__transitions')).toBeNull();
    flushAttachments(http);
    http.verify();
  });

  it('ends the wait for the transitions also when they fail', async () => {
    const { http, detectChanges, cmp } = await setup([
      'application.read',
      'application.manage',
      'application.transition',
    ]);
    http.expectOne(url('')).flush(appWire());
    http.expectOne(url('/versions')).flush(VERSIONS);
    http.expectOne(url('/comments')).flush(COMMENTS);
    flushForm(http);
    http.expectOne(url('/transitions')).flush({}, { status: 500, statusText: 'x' });
    detectChanges();
    expect(cmp.transitionsLoading()).toBe(false);
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

    // Now flush the stale app-1 detail GET. The seq guard returns early, so the
    // response must not overwrite the state of app-2 and must not run loadAux.
    stale.flush(appWire());
    detectChanges();
    expect(cmp.app()?.id).toBe('app-2');

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

    // The stale 404 arrives late. The seq guard returns before it sets notFound or error.
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

    // Call the private refresh(), hold its GET, then navigate.
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

    // The stale refresh response must not overwrite app-2 and must not run loadAux.
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

    // The data row uses the field label, not the raw key, and formats the currency.
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
    flushTypes(http);
    http.verify();
  });

  it('shows the generic error message for a non-404 load failure', async () => {
    const { http, detectChanges, cmp } = await setup();
    http.expectOne(url('')).flush({ title: 'Boom' }, { status: 500, statusText: 'Server Error' });
    detectChanges();
    expect(cmp.error()).toBe(true);
    expect(cmp.notFound()).toBe(false);
    expect(screen.getByText('Antrag konnte nicht geladen werden.')).toBeInTheDocument();
    // "Erneut versuchen" reads the application again.
    screen.getByRole('button', { name: 'Erneut versuchen' }).click();
    detectChanges();
    expect(cmp.error()).toBe(false);
    expect(cmp.loading()).toBe(true);
    http.expectOne(url('')).flush({ title: 'Boom' }, { status: 500, statusText: 'Server Error' });
    detectChanges();
    expect(cmp.error()).toBe(true);
    flushTypes(http);
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
    const railRefresh = jest.spyOn(TestBed.inject(RailStatusService), 'refresh');

    await userEvent.click(screen.getByRole('button', { name: 'Annehmen' }));
    const post = http.expectOne((r) => r.url === '/api/applications/app-1/transition');
    expect(post.request.method).toBe('POST');
    expect(post.request.body).toEqual({ transitionId: 'tr-1' });
    post.flush({ newStateId: 's2', statusEventId: 'e1', dispatchedActions: [] });
    expect(cmp.firing()).toBeNull();
    expect(success).toHaveBeenCalled();
    // The new state can add or remove a task: the count in the navigation asks again.
    expect(railRefresh).toHaveBeenCalledTimes(1);

    // The refresh fetches the application and the aux data again, but not the form.
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
    // The guard returns early, so firing stays unchanged.
    expect(cmp.firing()).toBe('other');
  });

  it.each([
    [403, 'Du darfst diesen Übergang nicht ausführen.'],
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

    // The refresh fires even on an error.
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
    // The top budget of the assigned cost centre reloads the fiscal-year list.
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

  /** The value of the "Kostenstelle" row in "Details". */
  function budgetRow(): HTMLElement {
    const label = screen.getByText('Kostenstelle');
    return label.closest('app-field-row') as HTMLElement;
  }

  it('names the cost centre also for a reader without application.manage', async () => {
    const { http, detectChanges } = await setup(['application.read']);
    http.expectOne(url('')).flush({ ...appWire(), budgetId: 'b1' });
    http.expectOne(url('/versions')).flush(VERSIONS);
    http.expectOne(url('/comments')).flush(COMMENTS);
    http.expectOne((r) => r.method === 'GET' && r.url === '/api/budgets').flush(budgetTree());
    http.expectOne((r) => r.url === '/api/budgets/b1/fiscal-years').flush([]);
    flushForm(http);
    detectChanges();
    expect(budgetRow()).toHaveTextContent('Veranstaltungen');
    expect(budgetRow()).not.toHaveTextContent('Keine');
    // Only a manager changes it.
    expect(screen.queryByRole('button', { name: 'Kostenstelle ändern' })).not.toBeInTheDocument();
    flushAttachments(http);
    http.verify();
  });

  it('never says "Keine" for an assigned cost centre outside the tree of the reader', async () => {
    const { http, detectChanges } = await setup(['application.read']);
    http.expectOne(url('')).flush({ ...appWire(), budgetId: 'b1' });
    http.expectOne(url('/versions')).flush(VERSIONS);
    http.expectOne(url('/comments')).flush(COMMENTS);
    http
      .expectOne((r) => r.method === 'GET' && r.url === '/api/budgets')
      .flush({ title: 'e' }, { status: 403, statusText: 'Forbidden' });
    flushForm(http);
    detectChanges();
    expect(budgetRow()).toHaveTextContent('—');
    expect(budgetRow()).not.toHaveTextContent('Keine');
    flushAttachments(http);
    http.verify();
  });

  it('says "Keine" without a cost centre', async () => {
    const { http, detectChanges } = await setup(['application.read']);
    flushAll(http);
    detectChanges();
    expect(budgetRow()).toHaveTextContent('Keine');
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
    // The initial fiscal-year list of the assigned cost centre.
    http.expectOne((r) => r.url === '/api/budgets/b1/fiscal-years').flush([]);
    flushForm(http);
    flushAttachments(http);
    detectChanges();
    const success = jest.spyOn(toast, 'success');

    cmp.openBudgetDialog();
    expect(cmp.budgetDialogOpen()).toBe(true);
    expect(cmp.budgetChoice()).toBe('b1');
    // The open dialog reloads the fiscal-year list of the current top budget.
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

    // The refresh fetches the application and the aux data again.
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
    // The value stays true and no extra request goes out. Other tests verify this.
    expect(cmp.assigningBudget()).toBe(true);
  });

  it.each([
    [422, 'Zuordnung nicht möglich — Kostenstelle/Haushaltsjahr prüfen.'],
    [403, 'Du darfst diesen Übergang nicht ausführen.'],
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

  function setupWithFields(
    fields: FormFieldDef[],
    data: Record<string, unknown>,
    extra: Partial<ApplicationOutWire> = {},
    versions: VersionOutWire[] = VERSIONS,
  ): Promise<Awaited<ReturnType<typeof setup>>> {
    return (async () => {
      const ctx = await setup();
      ctx.http.expectOne(url('')).flush({ ...appWire(), data, ...extra });
      ctx.http.expectOne(url('/versions')).flush(versions);
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

  it('shows the answers by section, the cost positions in their own block', async () => {
    const fields: FormFieldDef[] = [
      { key: 'title', type: 'text', label: { de: 'Titel' } },
      { key: 'agree', type: 'checkbox', label: { de: 'Zustimmung' } },
      { key: 'budget', type: 'currency', label: { de: 'Budget' } },
      { key: 'empty', type: 'text', label: { de: 'Leer' } },
      { key: 'kosten', type: 'positions', label: { de: 'Kostenaufstellung' } },
    ];
    const data = {
      title: 'Förderung Fest',
      agree: true,
      budget: 1234.5,
      empty: '',
      kosten: [{ label: 'Bühne', offers: [{ label: 'A', value: 100, preferred: true }] }],
      legacy: 'alt',
    };
    const { http, container } = await setupWithFields(fields, data);
    flushAttachments(http);
    const answers = container.querySelector('app-answer-view') as HTMLElement;
    expect(within(answers).getByRole('heading', { name: 'Antrag' })).toBeInTheDocument();
    expect(within(answers).getByText('Zustimmung')).toBeInTheDocument();
    expect(within(answers).getByText('Ja')).toBeInTheDocument();
    expect(answers.textContent).toContain('1.234,50');
    // The title is the heading of the sheet, an empty answer does not show.
    expect(within(answers).queryByText('Titel')).not.toBeInTheDocument();
    expect(within(answers).queryByText('Leer')).not.toBeInTheDocument();
    expect(within(answers).getByText('Kostenaufstellung')).toBeInTheDocument();
    expect(within(answers).getByText('Bühne')).toBeInTheDocument();
    // An answer without a field comes last, as text.
    expect(within(answers).getByRole('heading', { name: 'Weitere Angaben' })).toBeInTheDocument();
    http.verify();
  });

  it('waits for the form before it shows the answers', async () => {
    const { http, detectChanges, container } = await setup();
    http.expectOne(url('')).flush(appWire());
    http.expectOne(url('/versions')).flush(VERSIONS);
    http.expectOne(url('/comments')).flush(COMMENTS);
    detectChanges();
    // No raw keys flash while the form is on its way.
    expect(container.querySelector('app-answer-view')).toBeNull();
    // The answers hold their place with field rows, the size of the loaded ones.
    expect(container.querySelector('.ad .ad__skelAnswers .ad__skelRow')).not.toBeNull();
    flushForm(http);
    detectChanges();
    expect(container.querySelector('app-answer-view')).not.toBeNull();
    flushAttachments(http);
    http.verify();
  });

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

  it('#11: notes a capture under the status line and in the history', async () => {
    const { http, detectChanges, cmp } = await setup();
    http.expectOne(url('')).flush({
      ...appWire(),
      capture: {
        capturedBy: { kind: 'principal', displayName: 'Clara Clerk' },
        capturedAt: '2026-06-05T10:00:00Z',
        receivedOn: '2026-06-01',
        intake: 'per PDF',
      },
    });
    http.expectOne(url('/versions')).flush(VERSIONS);
    http.expectOne(url('/comments')).flush([]);
    http.expectOne(url('/timeline')).flush([
      { fromStateId: null, toStateId: 's1', toState: SUBMITTED, actor: 'Clara Clerk', at: '2026-06-05T10:00:00Z' },
    ]);
    flushForm(http);
    detectChanges();
    expect(cmp.captureParts()).toEqual([
      'Erfasst von Clara Clerk am 05.06.2026',
      'eingegangen am 01.06.2026',
      'per PDF',
    ]);
    expect(screen.getAllByTestId('ad-capture').map((e) => e.textContent?.trim())).toEqual([
      'Erfasst von Clara Clerk am 05.06.2026',
      'eingegangen am 01.06.2026',
      'per PDF',
    ]);
    expect(cmp.historyEntries()[0].body).toBe(
      'Version 1\nIm Auftrag der antragstellenden Person erfasst\nEingang: per PDF',
    );
    flushAttachments(http);

    // The same day and no intake: only the first part. An unknown account stays nameless.
    cmp.app.update((a) =>
      a
        ? {
            ...a,
            capture: { capturedBy: null, capturedAt: '2026-06-05T10:00:00Z', receivedOn: '2026-06-05', intake: null },
          }
        : a,
    );
    expect(cmp.captureParts()).toEqual(['Erfasst von Ehemaliges Konto am 05.06.2026']);
    expect(cmp.historyEntries()[0].body).toBe('Version 1\nIm Auftrag der antragstellenden Person erfasst');
    cmp.app.update((a) => (a ? { ...a, capture: { ...a.capture!, receivedOn: null } } : a));
    expect(cmp.captureParts()).toHaveLength(1);
    // An own submission has no note.
    cmp.app.update((a) => (a ? { ...a, capture: null } : a));
    expect(cmp.captureParts()).toBeNull();
    http.verify();
  });

  it('builds the history from the status changes and the versions (A3)', async () => {
    const { http, detectChanges, cmp, container } = await setup();
    http.expectOne(url('')).flush(appWire());
    http.expectOne(url('/versions')).flush(VERSIONS);
    http.expectOne(url('/comments')).flush([]);
    http.expectOne(url('/timeline')).flush([
      { fromStateId: null, toStateId: 's1', toState: SUBMITTED, actor: 'Mia', at: '2026-06-05T10:00:00Z' },
      {
        fromStateId: 's1',
        toStateId: 's2',
        toState: { ...SUBMITTED, id: 's2', label: { de: 'In Prüfung' }, color: '#e8a33d' },
        transitionLabel: { de: 'Prüfung beginnen' },
        actor: 'Mara',
        at: '2026-06-06T09:00:00Z',
        note: 'Bitte Angebote nachreichen.',
      },
    ]);
    flushForm(http);
    detectChanges();

    const entries = cmp.historyEntries();
    expect(entries.map((e) => e.title)).toEqual(['Eingereicht', 'In Prüfung', 'Version 2']);
    // The submission carries version 1; the transition and the note follow the state.
    expect(entries[0].body).toBe('Version 1');
    expect(entries[0].icon).toBe('send');
    expect(entries[1].body).toBe('Übergang „Prüfung beginnen“\nBitte Angebote nachreichen.');
    expect(entries[1].kind).toBe('warn');
    expect(entries[2].changes?.[0]).toMatchObject({ tag: 'Geändert', label: 'title', old: 'Fest', new: 'Förderung Fest' });
    // The tab counts the entries; the history renders them by day.
    expect(cmp.tabs().find((t) => t.id === 'history')?.count).toBe(3);
    expect(container.querySelector('#ad-history app-history')).not.toBeNull();
    flushAttachments(http);
    http.verify();
  });

  it('links the vote of a branch event without its machine note, or names it as deleted', async () => {
    const { http, detectChanges, cmp } = await setup();
    http.expectOne(url('')).flush(appWire());
    http.expectOne(url('/versions')).flush([]);
    http.expectOne(url('/comments')).flush([]);
    http.expectOne(url('/timeline')).flush([
      { toStateId: 's1', toState: SUBMITTED, at: '2026-06-05T10:00:00Z', note: 'vote:passed', voteId: 'v1' },
      { toStateId: 's1', toState: SUBMITTED, at: '2026-06-06T10:00:00Z', note: 'vote:rejected', voteDeleted: true },
    ]);
    flushForm(http);
    detectChanges();
    const [linked, deleted] = cmp.historyEntries();
    expect(linked.link).toEqual({ label: 'Zur Abstimmung', route: ['/voting', 'v1'] });
    expect(linked.body).toBeNull();
    expect(deleted.link).toBeNull();
    expect(deleted.body).toBe('Abstimmung gelöscht (mit Sitzung)');
    flushAttachments(http);
    http.verify();
  });

  it('F1: notes the deviations of a decision in the history', async () => {
    const { http, detectChanges, cmp } = await setup();
    http.expectOne(url('')).flush(appWire());
    http.expectOne(url('/versions')).flush([]);
    http.expectOne(url('/comments')).flush([]);
    http.expectOne(url('/timeline')).flush([
      { toStateId: 's1', toState: SUBMITTED, at: '2026-06-05T10:00:00Z' },
      {
        toStateId: 's1',
        toState: SUBMITTED,
        at: '2026-06-06T10:00:00Z',
        decision: { requestedAmount: '820.00', approvedAmount: '820.00', amountDeviates: false, conditionCount: 1 },
      },
      {
        toStateId: 's1',
        toState: SUBMITTED,
        at: '2026-06-07T10:00:00Z',
        decision: { requestedAmount: '820.00', approvedAmount: null, amountDeviates: false, conditionCount: 0 },
      },
    ]);
    flushForm(http);
    detectChanges();
    const [, conditions, plain] = cmp.historyEntries();
    expect(conditions.body).toBe('Mit Abweichungen: 1 Auflage');
    expect(plain.body).toBeNull();
    flushAttachments(http);
    http.verify();
  });

  it('renders every resolved actor and never a raw id or key', async () => {
    const { http, detectChanges, cmp, container } = await setup();
    http.expectOne(url('')).flush(appWire());
    http.expectOne(url('/versions')).flush([
      { ...VERSIONS[0], changedBy: 'applicant', changedByInfo: { kind: 'applicant' } },
      { ...VERSIONS[1], changedBy: null, changedByInfo: { kind: 'deleted' } },
    ]);
    http.expectOne(url('/comments')).flush([]);
    const uuid = 'e03ad7d7-f039-40d1-b56d-7939b1628e46';
    http.expectOne(url('/timeline')).flush([
      { toStateId: 's1', toState: SUBMITTED, actor: 'applicant', actorInfo: { kind: 'applicant' }, at: '2026-06-05T10:00:00Z' },
      {
        toStateId: 's1',
        toState: SUBMITTED,
        actor: 'Frederik Beimgraben',
        actorInfo: { kind: 'principal', displayName: 'Frederik Beimgraben' },
        at: '2026-06-05T11:00:00Z',
      },
      {
        toStateId: 's1',
        toState: SUBMITTED,
        actor: 'system:deadlines',
        actorInfo: { kind: 'system', key: 'deadlines' },
        at: '2026-06-05T12:00:00Z',
      },
      // An older server sends only the raw string: the UI still hides the id.
      { toStateId: 's1', toState: SUBMITTED, actor: uuid, at: '2026-06-05T13:00:00Z' },
    ]);
    flushForm(http);
    detectChanges();
    flushAttachments(http);
    const actors = cmp.historyEntries().map((e) => e.actor);
    expect(actors).toEqual([
      'Antragsteller:in',
      'Frederik Beimgraben',
      'System · Fristen',
      'Ehemaliges Konto',
      'Ehemaliges Konto',
    ]);
    detectChanges();
    const text = container.textContent ?? '';
    expect(text).not.toContain(uuid);
    expect(text).not.toContain('system:deadlines');
    http.verify();
  });

  it('falls back to the label of an event without a state and to no body', async () => {
    const { http, detectChanges, cmp } = await setup();
    http.expectOne(url('')).flush(appWire());
    http.expectOne(url('/versions')).flush([]);
    http.expectOne(url('/comments')).flush([]);
    http.expectOne(url('/timeline')).flush([
      { fromStateId: null, toStateId: 's9', toState: null, actor: null, at: '2026-06-05T10:00:00Z' },
    ]);
    flushForm(http);
    detectChanges();
    const [entry] = cmp.historyEntries();
    expect(entry.title).toBe('');
    expect(entry.body).toBeNull();
    expect(entry.kind).toBe('neutral');
    flushAttachments(http);
    http.verify();
  });

  it('shows version 1 as an entry of its own without status changes', async () => {
    const { http, detectChanges, cmp } = await setup();
    flushAll(http);
    detectChanges();
    flushAttachments(http);
    const entries = cmp.historyEntries();
    expect(entries.map((e) => e.title)).toEqual(['Version 1', 'Version 2']);
    expect(entries[0].body).toBe('Erste Fassung');
    expect(entries[0].actor).toBe('Mia');
    http.verify();
  });

  it('keeps a long or complex value of the diff out of the line and in a block', async () => {
    const fields: FormFieldDef[] = [
      { key: 'kosten', type: 'positions', label: { de: 'Kostenaufstellung' } },
      { key: 'text', type: 'textarea', label: { de: 'Beschreibung' } },
      { key: 'tbl', type: 'table', label: { de: 'Tabelle' } },
      { key: 'agree', type: 'checkbox', label: { de: 'Zustimmung' } },
    ];
    const { http, cmp } = await setupWithFields(fields, {});
    flushAttachments(http);
    const positions = [
      {
        label: 'Raummiete',
        offers: [
          { label: 'Studierendenwerk', value: 177.75, preferred: true },
          { label: 'Hotel', value: 200, preferred: false },
        ],
      },
      { label: '', noOffers: true, noOffersReason: 'Einziger Anbieter', offers: [{ label: 'Mensa', value: 20, preferred: true }] },
    ];
    // Cost positions: the summary on the line, every position and offer in the block.
    expect(cmp.fmt(positions, 'kosten')).toBe('2 Kostenpositionen · 197,75\u00a0€');
    expect(cmp.fmt([positions[0]], 'kosten')).toBe('1 Kostenposition · 177,75\u00a0€');
    expect(cmp.fmt([], 'kosten')).toBe('—');
    expect(cmp.fmtBlock(positions, 'kosten')).toBe(
      [
        'Raummiete · 177,75\u00a0€',
        '   – Studierendenwerk · 177,75\u00a0€ · bevorzugt',
        '   – Hotel · 200,00\u00a0€',
        'Position ohne Namen · 20,00\u00a0€',
        '   ohne Vergleichsangebote: Einziger Anbieter',
        '   – Mensa · 20,00\u00a0€ · bevorzugt',
      ].join('\n'),
    );
    expect(cmp.fmtBlock(null, 'kosten')).toBe('—');
    // A long text: only the field name on the line, the whole text in the block.
    expect(cmp.fmt('lang', 'text')).toBeNull();
    expect(cmp.fmtBlock('Zeile 1\nZeile 2', 'text')).toBe('Zeile 1\nZeile 2');
    expect(cmp.fmtBlock('  ', 'text')).toBe('—');
    // A table: one line per row.
    expect(cmp.fmt([{ a: 1 }], 'tbl')).toBeNull();
    expect(cmp.fmtBlock([{ a: 1, b: 'x' }, 'frei', { c: { d: 2 } }], 'tbl')).toBe(
      'a: 1 · b: x\nfrei\nc: {"d":2}',
    );
    expect(cmp.fmtBlock(null, 'tbl')).toBe('—');
    // A short field: on the line, no block.
    expect(cmp.fmt(false, 'agree')).toBe('Nein');
    expect(cmp.fmt(null, 'agree')).toBe('—');
    expect(cmp.fmtBlock(false, 'agree')).toBeNull();
    // A key without a field: a scalar stays text, an object goes into the block.
    expect(cmp.fmt('alt', 'gone')).toBe('alt');
    expect(cmp.fmtBlock('alt', 'gone')).toBeNull();
    expect(cmp.fmt({ a: 1 }, 'gone')).toBeNull();
    expect(cmp.fmtBlock({ a: 1, b: [2] }, 'gone')).toBe('a: 1\nb: [2]');
    expect(cmp.fmt('ohne', undefined)).toBe('ohne');
    http.verify();
  });

  it('opens the old and the new text of a changed long text below its line', async () => {
    const fields: FormFieldDef[] = [{ key: 'title', type: 'textarea', label: { de: 'Beschreibung' } }];
    const { http, cmp, detectChanges, container } = await setupWithFields(fields, {});
    flushAttachments(http);
    const version2 = cmp.historyEntries().find((e) => e.title === 'Version 2');
    expect(version2?.changes?.[0]).toMatchObject({
      label: 'Beschreibung',
      old: null,
      new: null,
      detail: { old: 'Fest', new: 'Förderung Fest' },
    });
    const more = screen.getByRole('button', { name: 'Werte anzeigen' });
    expect(more).toHaveAttribute('aria-expanded', 'false');
    expect(more).not.toHaveAttribute('aria-controls');
    await userEvent.click(more);
    detectChanges();
    const less = screen.getByRole('button', { name: 'Werte ausblenden' });
    expect(less).toHaveAttribute('aria-expanded', 'true');
    const values = container.querySelector(`#${less.getAttribute('aria-controls')}`);
    expect(values?.querySelector('del')?.textContent?.trim()).toBe('Fest');
    expect(values?.querySelector('ins')?.textContent?.trim()).toBe('Förderung Fest');
    expect(values).toHaveTextContent('Vorher');
    expect(values).toHaveTextContent('Nachher');
    http.verify();
  });

  it('leaves out a summary that did not change and keeps the blocks', async () => {
    const fields: FormFieldDef[] = [{ key: 'kosten', type: 'positions', label: { de: 'Kostenaufstellung' } }];
    const offer = (label: string) => [
      { label: 'Raum', offers: [{ label, value: 10, preferred: true }] },
    ];
    const { http, cmp } = await setupWithFields(fields, {}, {}, [
      VERSIONS[0],
      {
        ...VERSIONS[1],
        diff: {
          added: { kosten: offer('Neu') },
          removed: {},
          changed: { kosten: { old: offer('A'), new: offer('B') } },
        },
      },
    ]);
    flushAttachments(http);
    const changes = cmp.historyEntries().find((e) => e.title === 'Version 2')?.changes ?? [];
    // Only an offer text changed: the totals are the same, so only the blocks differ.
    expect(changes[0]).toMatchObject({ old: null, new: null });
    expect(changes[0].detail?.old).toContain('– A · 10,00');
    expect(changes[0].detail?.new).toContain('– B · 10,00');
    // An added field keeps its summary and has only the new block.
    expect(changes[1]).toMatchObject({ new: '1 Kostenposition · 10,00\u00a0€' });
    expect(changes[1].detail?.old).toBeNull();
    http.verify();
  });

  it('names the applicant as the author of a version', async () => {
    const { http, detectChanges, cmp } = await setup();
    http.expectOne(url('')).flush(appWire());
    http.expectOne(url('/versions')).flush([
      { ...VERSIONS[0], changedBy: 'applicant' },
      { ...VERSIONS[1], changedBy: null, diff: { added: { a: 'neu' }, removed: { b: 'alt' }, changed: {} } },
    ]);
    http.expectOne(url('/comments')).flush([]);
    flushForm(http);
    detectChanges();
    flushAttachments(http);
    const [first, second] = cmp.historyEntries();
    expect(first.actor).toBe('Antragsteller:in');
    expect(second.actor).toBeNull();
    expect(second.changes?.map((c) => [c.tag, c.kind])).toEqual([
      ['Hinzugefügt', 'accent'],
      ['Entfernt', 'error'],
    ]);
    http.verify();
  });

  it('derives the author name', async () => {
    const { cmp } = await setup();
    expect(cmp['authorName']({ author: 'Mia Müller' } as ApplicationComment)).toBe('Mia Müller');
    expect(
      cmp['authorName']({ author: null, authorKind: 'applicant' } as ApplicationComment),
    ).toBe('Antragsteller:in');
    expect(
      cmp['authorName']({ author: null, authorKind: 'principal' } as ApplicationComment),
    ).toBe('Gremium');
  });

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
    patch.flush({ ...appWire(), version: 3, data: { title: 'Neu' } });
    expect(cmp.savingEdit()).toBe(false);
    expect(cmp.editing()).toBe(false);
    expect(success).toHaveBeenCalledWith('Gespeichert. Version 3 angelegt.');

    // The save triggers a refresh.
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

  const PII_FIELDS: FormFieldDef[] = [
    { key: 'title', type: 'text', label: { de: 'Titel' } },
    { key: 'iban', type: 'text', label: { de: 'IBAN' }, isPII: true, required: true },
    { key: 'mail', type: 'text', label: { de: 'Mail' }, isPII: true },
  ];

  type KeyedField = { key?: unknown; fieldGroup?: unknown[] };
  const editKeysOf = (fields: KeyedField[]): unknown[] =>
    fields.flatMap((f) => [f.key, ...editKeysOf((f.fieldGroup ?? []) as KeyedField[])]);

  it('leaves a stripped PII field out of the edit form (O21)', async () => {
    // A reader without the PII right gets `data` without the isPII fields, and the
    // server names them in `hiddenKeys`.
    const { http, cmp } = await setupWithFields(
      PII_FIELDS,
      { title: 'Förderung Fest' },
      { hiddenKeys: ['iban', 'mail'] },
    );
    flushAttachments(http);

    cmp.startEdit(cmp.app() as Application);
    const editKeys = editKeysOf(cmp.editFields() as KeyedField[]);
    expect(editKeys).toContain('title');
    expect(editKeys).not.toContain('iban');
    expect(editKeys).not.toContain('mail');
    expect(screen.queryByText('IBAN')).not.toBeInTheDocument();
  });

  it('keeps an unanswered PII field editable for a reader with the PII right (O21)', async () => {
    // The optional `mail` was never answered, so its key is missing from `data`. The
    // server hid nothing, so the reader can still fill the field.
    const { http, cmp } = await setupWithFields(PII_FIELDS, {
      title: 'Förderung Fest',
      iban: 'DE02120300000000202051',
    });
    flushAttachments(http);

    cmp.startEdit(cmp.app() as Application);
    const editKeys = editKeysOf(cmp.editFields() as KeyedField[]);
    expect(editKeys).toContain('iban');
    expect(editKeys).toContain('mail');
  });

  it('lists the changed keys of a version without values (A11 metadata view)', async () => {
    const { http, detectChanges } = await setup();
    http.expectOne(url('')).flush(appWire());
    http.expectOne(url('/versions')).flush([
      { version: 1, data: null, diff: null, changedKeys: [], changedBy: 'applicant', at: '2026-06-05T10:00:00Z' },
      { version: 2, data: null, diff: null, changedKeys: ['projectNote'], changedBy: 'StuPa', at: '2026-06-05T11:00:00Z' },
    ]);
    http.expectOne(url('/comments')).flush([]);
    detectChanges();
    detectChanges();
    expect(screen.getByText('projectNote')).toBeInTheDocument();
    expect(screen.queryByText('Keine Feldänderungen.')).not.toBeInTheDocument();
    flushForm(http);
    flushAttachments(http);
    http.verify();
  });

  it('does not save while the edit form is invalid or already saving', async () => {
    const { http, detectChanges, cmp, toast } = await setup();
    flushAll(http);
    detectChanges();
    flushAttachments(http);
    const error = jest.spyOn(toast, 'error');
    jest.useFakeTimers();

    jest.spyOn(cmp.editForm, 'invalid', 'get').mockReturnValue(true);
    const touched = jest.spyOn(cmp.editForm, 'markAllAsTouched');
    cmp.saveEdit();
    expect(cmp.savingEdit()).toBe(false);
    // The fields show their errors, and the toast says why nothing happened.
    expect(touched).toHaveBeenCalled();
    expect(error).toHaveBeenCalledWith('Prüfe die markierten Felder.');
    jest.runOnlyPendingTimers();
    jest.useRealTimers();

    jest.spyOn(cmp.editForm, 'invalid', 'get').mockReturnValue(false);
    cmp.savingEdit.set(true);
    cmp.saveEdit();
    http.verify();
  });

  it.each([
    [422, 'Die Nachricht ist zu lang.', [{ field: 'body.body', msg: 'String should have at most 10000 characters' }]],
    [403, 'Du darfst hier nicht schreiben.', []],
    [500, 'Kommentar konnte nicht gespeichert werden.', []],
  ])('toasts a failed comment %s and discards it on request', async (status, message, errors) => {
    const { http, detectChanges, cmp, toast } = await setup();
    flushAll(http);
    detectChanges();
    flushAttachments(http);
    const error = jest.spyOn(toast, 'error');
    cmp['sendComment']({ body: 'Hallo', visibility: 'internal' });
    http
      .expectOne((r) => r.method === 'POST' && r.url === '/api/applications/app-1/comments')
      .flush({ title: 'e', errors }, { status, statusText: 'x' });
    expect(error).toHaveBeenCalledWith(message);
    const failed = cmp.chatMessages().find((m) => m.state === 'failed');
    expect(failed?.body).toBe('Hallo');
    cmp['discardComment']({ id: failed!.id });
    expect(cmp.chatMessages().some((m) => m.state === 'failed')).toBe(false);
  });

  it('reads the comments again when the chat asks, and keeps them on a failure', async () => {
    const { http, detectChanges, cmp } = await setup();
    flushAll(http);
    detectChanges();
    flushAttachments(http);
    const file = { id: 'f1', filename: 'plan.pdf', mime: 'application/pdf', size: 20 };
    cmp.comments.set([{ ...cmp.comments()[0], attachments: [{ ...file, scanState: 'scanning' }] }]);
    cmp['refreshComments']();
    // Only the scan state comes from the read: the text on screen stays.
    http.expectOne(url('/comments')).flush([{ ...COMMENTS[0], body: 'Alt', attachments: [{ ...file, scanState: 'clean' }] }]);
    expect(cmp.comments().map((c) => c.body)).toEqual(['Bitte Kostenplan ergänzen.']);
    expect(cmp.comments()[0].attachments?.[0].scanState).toBe('clean');
    cmp['refreshComments']();
    http.expectOne(url('/comments')).flush(null, { status: 500, statusText: 'x' });
    expect(cmp.comments()[0].attachments?.[0].scanState).toBe('clean');
    // An answer from before another load is dropped.
    cmp['refreshComments']();
    const late = http.expectOne(url('/comments'));
    (cmp as unknown as { loadSeq: number }).loadSeq++;
    late.flush([]);
    expect(cmp.comments()).toHaveLength(1);
  });

  it('keeps a comment the outbox delivered while a background read was in flight, once', async () => {
    const { http, detectChanges, cmp } = await setup();
    flushAll(http);
    detectChanges();
    flushAttachments(http);
    cmp['refreshComments']();
    const stale = http.expectOne(url('/comments'));
    cmp['sendComment']({ body: 'Neu' });
    const created = { ...COMMENTS[0], id: 'c2', body: 'Neu' };
    // The read was served after the send committed: it already holds c2.
    stale.flush([...COMMENTS, created]);
    expect(cmp.comments().map((c) => c.id)).toEqual(['c1']);
    http.expectOne((r) => r.method === 'POST' && r.url === '/api/applications/app-1/comments').flush(created);
    expect(cmp.comments().map((c) => c.id)).toEqual(['c1', 'c2']);
  });

  it('offers no paperclip on an anonymized application', async () => {
    const { http, detectChanges, cmp } = await setup();
    flushAll(http);
    cmp.commentsOpen.set(true);
    detectChanges();
    flushAttachments(http);
    expect(screen.getByRole('button', { name: 'Datei anhängen' })).toBeInTheDocument();
    cmp.app.update((a) => a && { ...a, applicant: { ...a.applicant!, anonymized: true } });
    detectChanges();
    expect(screen.queryByRole('button', { name: 'Datei anhängen' })).toBeNull();
  });

  it('hides the paperclip once the server refuses files, for a reader without the applicant block', async () => {
    // A reader without the PII right gets no applicant block: the refusal is the only sign.
    const id = 'app-nofiles';
    const params = new BehaviorSubject(convertToParamMap({ id }));
    const { http, detectChanges, cmp } = await setup(['application.read'], params);
    const show = (appId: string) => {
      http.expectOne(url('', appId)).flush({ ...appWire(), id: appId, applicant: null });
      http.expectOne(url('/versions', appId)).flush(VERSIONS);
      http.expectOne(url('/comments', appId)).flush(COMMENTS);
      flushForm(http, appId);
      detectChanges();
      flushAttachments(http);
      // Another application closes the sheet; open it again for its composer.
      cmp.commentsOpen.set(true);
      detectChanges();
    };
    const post = () => http.expectOne((r) => r.method === 'POST' && r.url === `/api/applications/${id}/comments`);
    flushTypes(http);
    show(id);
    expect(screen.getByRole('button', { name: 'Datei anhängen' })).toBeInTheDocument();
    cmp['sendComment']({ body: 'Siehe Anhang', attachmentIds: ['d1'], draftToken: 'tok' });
    post().flush({ code: 'application_anonymized', errors: [] }, { status: 422, statusText: 'x' });
    detectChanges();
    expect(screen.queryByRole('button', { name: 'Datei anhängen' })).toBeNull();
    // Another failure keeps the paperclip as it is.
    cmp['sendComment']({ body: 'Nochmal' });
    post().flush(null, { status: 500, statusText: 'x' });
    detectChanges();
    expect(screen.queryByRole('button', { name: 'Datei anhängen' })).toBeNull();

    // Another application takes files; the next visit of this one knows it without a refusal.
    params.next(convertToParamMap({ id: 'app-takes' }));
    show('app-takes');
    expect(screen.getByRole('button', { name: 'Datei anhängen' })).toBeInTheDocument();
    params.next(convertToParamMap({ id }));
    show(id);
    expect(screen.queryByRole('button', { name: 'Datei anhängen' })).toBeNull();
  });

  it('keeps the paperclip of a thread that takes files after another failed send', async () => {
    const { http, detectChanges, cmp } = await setup();
    flushAll(http);
    cmp.commentsOpen.set(true);
    detectChanges();
    flushAttachments(http);
    cmp['sendComment']({ body: 'Text' });
    http
      .expectOne((r) => r.method === 'POST' && r.url === '/api/applications/app-1/comments')
      .flush({ code: 'validation_error', errors: [] }, { status: 422, statusText: 'x' });
    detectChanges();
    expect(screen.getByRole('button', { name: 'Datei anhängen' })).toBeInTheDocument();
  });

  it.each([
    [true, true],
    [false, false],
  ])('lets the log grow with the thread in the bottom sheet of a phone (phone %s)', async (phone, sheet) => {
    const realMatchMedia = window.matchMedia;
    window.matchMedia = ((query: string) => ({
      matches: phone && query.includes('max-width'),
      media: query,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    })) as unknown as typeof window.matchMedia;
    try {
      const { http, detectChanges, fixture, cmp } = await setup();
      flushAll(http);
      cmp.commentsOpen.set(true);
      detectChanges();
      flushAttachments(http);
      const chat = fixture.debugElement.query((d) => d.name === 'app-chat').nativeElement as HTMLElement;
      expect(chat.classList.contains('ad__chat')).toBe(true);
      expect(chat.classList.contains('ad__chat--sheet')).toBe(sheet);
    } finally {
      window.matchMedia = realMatchMedia;
    }
  });

  it('keeps the composer files of the chat while the sheet closes and opens', async () => {
    const { http, detectChanges, fixture, cmp } = await setup();
    flushAll(http);
    cmp.commentsOpen.set(true);
    detectChanges();
    flushAttachments(http);
    const chat = () => fixture.debugElement.query((d) => d.name === 'app-chat');
    const before = chat();
    const drafts = before.injector.get(DraftAttachmentsService);
    cmp.commentsOpen.set(false);
    detectChanges();
    // The sheet drops its content once the pane has gone.
    await new Promise((resolve) => setTimeout(resolve));
    detectChanges();
    expect(chat()).toBeNull();
    cmp.commentsOpen.set(true);
    detectChanges();
    for (const req of http.match(() => true)) req.flush([]);
    // The chat exists only while the sheet is open (a hidden one would mark the thread
    // as seen); the page holds its drafts, so the new chat takes the same files.
    expect(chat().componentInstance).not.toBe(before.componentInstance);
    expect(chat().injector.get(DraftAttachmentsService)).toBe(drafts);
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

  it('shows a 422 of the server on the cost position it names (D12)', async () => {
    const fields: FormFieldDef[] = [
      { key: 'title', type: 'text', label: { de: 'Titel' } },
      { key: 'kosten', type: 'positions', label: { de: 'Kostenaufstellung' } },
    ];
    const kosten = [
      { label: 'A', offers: [{ label: 'X', value: 10, preferred: true }, { label: 'Y', value: 12, preferred: false }, { label: 'Z', value: 13, preferred: false }] },
      { label: 'B', noOffers: true, noOffersReason: 'Einziger Anbieter', offers: [{ label: 'Q', value: 5, preferred: true }] },
    ];
    const { http, detectChanges, cmp, toast } = await setupWithFields(fields, { title: 'Fest', kosten });
    flushAttachments(http);
    const error = jest.spyOn(toast, 'error');
    cmp.startEdit(cmp.app() as Application);
    detectChanges();
    await new Promise((r) => setTimeout(r));
    detectChanges();

    // "Speichern" shows after the first change of a field.
    expect(screen.queryByRole('button', { name: 'Speichern' })).not.toBeInTheDocument();
    await userEvent.type(screen.getByRole('textbox', { name: /Titel/ }), 'e');
    detectChanges();
    await userEvent.click(screen.getByRole('button', { name: 'Speichern' }));
    http
      .expectOne((r) => r.method === 'PATCH' && r.url === '/api/applications/app-1')
      .flush(
        {
          type: 'about:blank',
          title: 'Unprocessable',
          status: 422,
          code: 'validation_error',
          errors: [{ field: 'kosten[1]', msg: 'needs at least 1 comparison offer(s)' }],
        },
        { status: 422, statusText: 'Unprocessable' },
      );
    detectChanges();
    expect(error).toHaveBeenCalledWith('Prüfe die markierten Felder.');
    expect(cmp.editing()).toBe(true);
    // The position opens and names the rule of the server.
    expect(
      screen.getByText(
        'Diese Position braucht mehr Angebote. Ohne Vergleichsangebote: ein Angebot und eine Begründung.',
      ),
    ).toBeInTheDocument();
    await new Promise((r) => setTimeout(r));
    http.verify();
  });

  it('falls back to the save toast for a 422 without a known field', async () => {
    const { http, detectChanges, cmp, toast } = await setupWithFields(
      [{ key: 'title', type: 'text', label: { de: 'Titel' } }],
      { title: 'Fest' },
    );
    flushAttachments(http);
    const error = jest.spyOn(toast, 'error');
    cmp.startEdit(cmp.app() as Application);
    detectChanges();
    cmp.saveEdit();
    http
      .expectOne((r) => r.method === 'PATCH')
      .flush(
        { status: 422, code: 'validation_error', errors: [{ field: 'nope', msg: 'x' }] },
        { status: 422, statusText: 'Unprocessable' },
      );
    expect(error).toHaveBeenCalledWith('Speichern fehlgeschlagen.');
    http.verify();
  });

  it('shows the decision and opens the decision dialog for an accepted state (F1)', async () => {
    const { http, detectChanges, cmp, container } = await setup([
      'application.read',
      'application.transition',
    ]);
    http.expectOne(url('')).flush({
      ...appWire(),
      budgetId: 'c1',
      approvedAmount: '200.00',
      decision: {
        requestedAmount: '250.00',
        approvedAmount: '200.00',
        amountDeviates: true,
        conditions: ['Belege einreichen'],
        decidedAt: '2026-06-06T10:00:00Z',
        voteId: null,
        gremiumName: 'StuPa',
        meetingTitle: null,
        agendaPosition: null,
      },
    });
    http.expectOne(url('/versions')).flush(VERSIONS);
    http.expectOne(url('/comments')).flush([]);
    http.expectOne(url('/transitions')).flush([
      {
        id: 'tr-ok',
        fromStateId: 's1',
        toStateId: 's2',
        label: { de: 'Bewilligen' },
        color: null,
        allowsDecision: true,
      },
    ]);
    flushForm(http);
    detectChanges();

    expect(screen.getByRole('heading', { name: 'Beschluss' })).toBeInTheDocument();
    expect(screen.getByText('Belege einreichen')).toBeInTheDocument();
    expect(container.querySelector('app-amount .amt__struck')?.textContent?.replace(/\u00a0/g, ' ')).toBe('250,00 €');
    expect(container.querySelector('.ad__bound')?.textContent).toContain('bewilligt statt beantragt');

    await userEvent.click(screen.getByRole('button', { name: 'Bewilligen' }));
    http.expectNone((r) => r.url === '/api/applications/app-1/transition');
    expect(cmp.decisionOpen()).toBe(true);
    expect(cmp.decisionTransition()?.id).toBe('tr-ok');
  });

  it('names no approved amount when it equals the requested one (F1)', async () => {
    const { cmp } = await setup(['application.read']);
    const base = { ...appWire(), amount: '250.00', currency: 'EUR' } as unknown as Parameters<
      typeof cmp.approvedAmount
    >[0];
    expect(cmp.approvedAmount({ ...base, approvedAmount: null })).toBe('');
    expect(cmp.approvedAmount({ ...base, approvedAmount: '250.00' })).toBe('');
    expect(cmp.approvedAmount({ ...base, approvedAmount: '200.00' }).replace(/\u00a0/g, ' ')).toBe('200,00 €');
  });

  it('opens the agenda dialog for a transition onto the agenda (A1)', async () => {
    const { http, detectChanges, cmp } = await setup([
      'application.read',
      'application.transition',
    ]);
    http.expectOne(url('')).flush(appWire());
    http.expectOne(url('/versions')).flush(VERSIONS);
    http.expectOne(url('/comments')).flush([]);
    http.expectOne(url('/transitions')).flush([
      {
        id: 'tr-a',
        fromStateId: 's1',
        toStateId: 's2',
        label: { de: 'Auf Tagesordnung setzen' },
        color: null,
        addsToAgenda: true,
        agendaGremiumId: 'g1',
      },
    ]);
    flushForm(http);
    detectChanges();

    await userEvent.click(screen.getByRole('button', { name: 'Auf Tagesordnung setzen' }));
    // No fire yet: the dialog asks for the meeting first.
    http.expectNone((r) => r.url === '/api/applications/app-1/transition');
    expect(cmp.agendaOpen()).toBe(true);
    expect(cmp.agendaTransition()?.id).toBe('tr-a');
    http
      .expectOne((r) => r.url === '/api/meetings' && r.params.get('gremiumId') === 'g1')
      .flush([]);
    detectChanges();
    expect(screen.getByText(/Keine geplante Sitzung sichtbar/)).toBeInTheDocument();

    // The dialog fired: the detail loads the application again.
    cmp.onAgendaDone();
    http.expectOne(url('')).flush(appWire());
    http.expectOne(url('/versions')).flush(VERSIONS);
    http.expectOne(url('/comments')).flush([]);
    http.expectOne(url('/transitions')).flush([]);
    flushAttachments(http);
    http.verify();
  });

  // #g9: delete is gated on `application.delete`, not on the literal admin role.
  it('offers delete to a non-admin role that holds application.delete', async () => {
    const { cmp } = await setup(
      ['application.read', 'application.delete'],
      new BehaviorSubject(convertToParamMap({ id: 'app-1' })),
      ['office'],
    );
    expect(cmp.canDelete()).toBe(true);
  });

  it('hides delete from a manager without application.delete', async () => {
    const { cmp } = await setup(
      ['application.read', 'application.manage'],
      new BehaviorSubject(convertToParamMap({ id: 'app-1' })),
      ['manager'],
    );
    expect(cmp.canDelete()).toBe(false);
  });

  // An admin holds `application.delete` through the role bypass.
  it('deletes the application and navigates to the list', async () => {
    const { http, detectChanges, cmp, toast, router } = await setup(
      ['application.read', 'application.manage'],
      new BehaviorSubject(convertToParamMap({ id: 'app-1' })),
      ['admin'],
    );
    flushAll(http);
    // The admin role holds every permission, so the aux load also asks for the
    // transitions. An empty answer is fine.
    http.expectOne(url('/transitions')).flush([]);
    detectChanges();
    flushAttachments(http);
    const success = jest.spyOn(toast, 'success');
    const nav = jest.spyOn(router, 'navigate').mockResolvedValue(true);
    expect(cmp.canDelete()).toBe(true);

    cmp.doDelete();
    http
      .expectOne((r) => r.method === 'DELETE' && r.url === '/api/applications/app-1')
      .flush(null, { status: 204, statusText: 'No Content' });
    expect(cmp.deleting()).toBe(false);
    expect(cmp.confirmDelete()).toBe(false);
    expect(success).toHaveBeenCalled();
    expect(nav).toHaveBeenCalledWith(['/applications'], { queryParamsHandling: 'preserve' });
    http.verify();
  });

  // The tasks page shows the same detail under `/tasks` and sets the list path.
  it('goes back to the list path of the page after a delete', async () => {
    const { http, detectChanges, cmp, router, fixture } = await setup(
      ['application.read', 'application.manage'],
      new BehaviorSubject(convertToParamMap({ id: 'app-1' })),
      ['admin'],
    );
    fixture.debugElement.injector.get(ApplicationsPageService).listPath.set(['/tasks']);
    flushAll(http);
    http.expectOne(url('/transitions')).flush([]);
    detectChanges();
    flushAttachments(http);
    const nav = jest.spyOn(router, 'navigate').mockResolvedValue(true);

    cmp.doDelete();
    http
      .expectOne((r) => r.method === 'DELETE' && r.url === '/api/applications/app-1')
      .flush(null, { status: 204, statusText: 'No Content' });
    expect(nav).toHaveBeenCalledWith(['/tasks'], { queryParamsHandling: 'preserve' });
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

  it('outlines the detail layout while it loads, never a bare sentence', async () => {
    // The most-opened view in the platform. One line of text standing in for the whole
    // layout until it arrives at once is the worst place for it.
    const view = await render(ApplicationsDetailComponent, {
      providers: [
        NO_LINKED_TODOS,
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: USE_MOCK_API, useValue: false },
        { provide: AuthService, useValue: fakeAuth(['application.read']) },
        // The real service polls; the page only asks it to refresh.
        { provide: RailStatusService, useValue: { refresh: jest.fn() } },
        {
          provide: ActivatedRoute,
          useValue: {
            paramMap: new BehaviorSubject(convertToParamMap({ id: 'app-1' })),
            fragment: new BehaviorSubject<string | null>(null),
            snapshot: { fragment: null },
          },
        },
      ],
    });
    view.fixture.detectChanges();

    expect(view.container.querySelectorAll('.skel-text').length).toBeGreaterThan(0);
    expect(view.container.querySelector('[aria-busy="true"]')).toBeTruthy();
    // The wording stays for a screen reader, because the blocks are decorative.
    expect(view.container.querySelector('[role="status"]')).toHaveClass('sr-only');

    const http = view.fixture.debugElement.injector.get(HttpTestingController);
    for (const req of http.match(() => true)) req.flush(null, { status: 404, statusText: 'x' });
  });

  describe('archiving', () => {
    it('offers no archive control without the permission', async () => {
      const { http, detectChanges } = await setup(['application.read']);
      flushAll(http);
      detectChanges();
      expect(screen.queryByRole('button', { name: /Archivieren/ })).not.toBeInTheDocument();
    });

    it('archives without asking for confirmation, because it is reversible', async () => {
      // The delete and the erasure request beside it both confirm. This one does not:
      // the way back is one click on the same button, and a confirm would imply a risk
      // that is not there.
      const { http, detectChanges } = await setup(['application.read', 'application.archive']);
      flushAll(http);
      detectChanges();

      await userEvent.click(screen.getByRole('button', { name: /Archivieren/ }));
      const req = http.expectOne((r) => r.url.endsWith('/archive') && r.method === 'POST');
      req.flush({ ...appWire(), archivedAt: '2026-09-02T10:00:00Z' });
      detectChanges();

      expect(screen.getByRole('button', { name: /Aus Archiv holen/ })).toBeInTheDocument();
    });

    it('keeps the applicant block and the closed paperclip of an anonymized application after the archive', async () => {
      // The archive answers without the applicant block.
      const { http, detectChanges, cmp } = await setup(['application.read', 'application.manage', 'application.archive']);
      flushTypes(http);
      http.expectOne(url('')).flush({ ...appWire(), applicant: { email: null, name: null, anonymized: true } });
      http.expectOne(url('/versions')).flush(VERSIONS);
      http.expectOne(url('/comments')).flush(COMMENTS);
      for (const req of http.match((r) => r.method === 'GET' && r.url === '/api/budgets')) req.flush([]);
      flushForm(http);
      detectChanges();
      flushAttachments(http);
      expect(screen.queryByRole('button', { name: 'Datei anhängen' })).toBeNull();
      await userEvent.click(screen.getByRole('button', { name: /Archivieren/ }));
      http
        .expectOne((r) => r.url.endsWith('/archive') && r.method === 'POST')
        .flush({ ...appWire(), applicant: null, archivedAt: '2026-09-02T10:00:00Z' });
      detectChanges();
      expect(cmp.app()?.archivedAt).not.toBeNull();
      expect(cmp.app()?.applicant?.anonymized).toBe(true);
      expect(screen.queryByRole('button', { name: 'Datei anhängen' })).toBeNull();
    });

    it('takes the archive answer as it is when no applicant block was shown', async () => {
      const { http, detectChanges, cmp } = await setup(['application.read', 'application.archive']);
      flushTypes(http);
      http.expectOne(url('')).flush({ ...appWire(), applicant: null });
      http.expectOne(url('/versions')).flush(VERSIONS);
      http.expectOne(url('/comments')).flush(COMMENTS);
      flushForm(http);
      detectChanges();
      await userEvent.click(screen.getByRole('button', { name: /Archivieren/ }));
      http
        .expectOne((r) => r.url.endsWith('/archive') && r.method === 'POST')
        .flush({ ...appWire(), applicant: null, archivedAt: '2026-09-02T10:00:00Z' });
      detectChanges();
      expect(cmp.app()?.archivedAt).not.toBeNull();
      expect(cmp.app()?.applicant).toBeNull();
    });

    it('says on the page that an application is archived', async () => {
      // It looks exactly like an active one, and someone arriving from a link has no
      // other way to know.
      const { http, detectChanges } = await setup(['application.read']);
      http.expectOne(url('')).flush({ ...appWire(), archivedAt: '2026-09-02T10:00:00Z' });
      http.expectOne(url('/versions')).flush(VERSIONS);
      http.expectOne(url('/comments')).flush(COMMENTS);
      for (const req of http.match((r) => r.method === 'GET' && r.url === '/api/budgets')) {
        req.flush([]);
      }
      flushForm(http);
      detectChanges();
      expect(screen.getByText(/Archiviert am/)).toBeInTheDocument();
    });
  });
});
