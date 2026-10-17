import { HttpErrorResponse } from '@angular/common/http';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { Observable, Subject, of, throwError } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import type { PersonRef } from '@core/api/models';
import {
  TicketsApiService,
  type MyTicketDetail,
  type TicketDetail,
  type TicketListItem,
  type TicketNote,
  type TicketPage,
  type TicketPatch,
} from '@core/api/tickets.service';
import { TodosApiService, type TodoLinkedCard } from '@core/api/todos.service';
import { AuthService } from '@core/auth/auth.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { DraftAttachmentsService } from '../../features/apply/draft-attachments.service';
import { TicketDetailComponent, reportScanState } from './ticket-detail.component';
import { TicketsPageService } from './tickets-page.service';

const MARA: PersonRef = { principalId: 'p1', displayName: 'Mara Keller' };
const JONAS: PersonRef = { principalId: 'p2', displayName: 'Jonas Albrecht' };

function mine(over: Partial<MyTicketDetail> = {}): MyTicketDetail {
  return {
    id: 't40',
    number: 'T-0040',
    kind: 'question',
    title: 'Wo finde ich das Protokoll?',
    status: 'in_progress',
    createdAt: '2026-10-14T19:14:00Z',
    updatedAt: '2026-10-15T06:12:00Z',
    body: 'Ich finde das Protokoll nicht.',
    attachments: [{ id: 'a1', filename: 'screen.png', mime: 'image/png', size: 9, scanned: true }],
    notes: [
      {
        id: 'n1',
        author: MARA,
        body: 'Unter Sitzungen.',
        at: '2026-10-15T06:20:00Z',
        editedAt: null,
        isOwn: false,
        attachments: [],
        visibility: 'public',
      },
    ],
    events: [
      {
        id: 'e1',
        kind: 'status',
        at: '2026-10-15T06:12:00Z',
        payload: { from: 'new', to: 'in_progress' },
      },
    ],
    closedAt: null,
    canReply: true,
    ...over,
  };
}

function detail(over: Partial<TicketDetail> = {}): TicketDetail {
  return {
    id: 't40',
    number: 'T-0040',
    kind: 'bug',
    title: 'Protokoll-PDF zeigt im Kopf das falsche Datum',
    status: 'in_progress',
    reporter: {
      principalId: 'r1',
      displayName: 'Tobias Brandt',
      email: 'tobias@example.org',
      anonymized: false,
    },
    assignee: MARA,
    createdAt: '2026-10-14T19:14:00Z',
    updatedAt: '2026-10-15T06:12:00Z',
    body: 'Im Protokoll steht das falsche Datum.',
    context: {
      url: 'https://stupa.example.org/meetings/m1/protocol',
      route: '/meetings/m1/protocol',
      appVersion: 'v2026.10.10',
      userAgent:
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/19.0 Safari/605.1.15',
      viewport: '1512x945',
    },
    attachments: [
      { id: 'a1', filename: 'protokoll-kopf.png', mime: 'image/png', size: 98304, scanned: true },
    ],
    notes: [
      {
        id: 'n1',
        author: MARA,
        body: 'Prüfe ich.',
        at: '2026-10-15T06:20:00Z',
        editedAt: null,
        isOwn: true,
        attachments: [
          { id: 'f1', filename: 'log.txt', mime: 'text/plain', size: 10, scanState: 'clean' },
        ],
      },
    ],
    events: [
      {
        id: 'e1',
        kind: 'created',
        actor: null,
        at: '2026-10-14T19:14:00Z',
        payload: { confirmationSent: true },
      },
      {
        id: 'e2',
        kind: 'assignee',
        actor: MARA,
        at: '2026-10-15T06:12:00Z',
        payload: { to: MARA },
      },
    ],
    duplicateOf: null,
    contextTarget: { kind: 'meeting', id: 'm1', title: '33. Sitzung STUPA' },
    openTodoCount: 0,
    closedAt: null,
    anonymizedAt: null,
    senderBlocked: false,
    ...over,
  };
}

function card(over: Partial<TodoLinkedCard> = {}): TodoLinkedCard {
  return {
    id: 'c1',
    boardId: 'b1',
    boardName: 'Plattform',
    title: 'PDF-Kopf: Beginn statt Ende verwenden',
    columnName: 'In Arbeit',
    isDone: false,
    dueDate: '2026-10-17',
    assignees: [MARA],
    ...over,
  };
}

interface Opts {
  get?: (id: string) => Observable<TicketDetail>;
  todos?: Observable<TodoLinkedCard[]>;
  assignees?: Observable<PersonRef[]>;
  split?: boolean | null;
  /** The e-mail of the signed-in viewer. */
  me?: string | null;
  /** The viewer holds `ticket.manage` (default); false: the reporter view. */
  manager?: boolean;
  /** The reporter view: the answer of `GET /tickets/mine/{id}`. */
  mine?: (id: string) => Observable<MyTicketDetail>;
}

async function start(url = '/tickets/t40', opts: Opts = {}) {
  localStorage.setItem('ap.locale', 'de');
  let get = opts.get ?? (() => of(detail()));
  let todos = opts.todos ?? of<TodoLinkedCard[]>([]);
  const api = {
    get: jest.fn((id: string) => get(id)),
    assignees: jest.fn(
      () => opts.assignees ?? of([MARA, JONAS, { principalId: null, displayName: 'Weg' }]),
    ),
    patch: jest.fn((id: string, body: TicketPatch) =>
      of(detail({ ...body, id } as Partial<TicketDetail>)),
    ),
    addNote: jest.fn((_id: string, body: string, _files?: unknown) =>
      of<TicketNote>({
        id: 'n9',
        author: MARA,
        body,
        at: '2026-10-15T09:00:00Z',
        editedAt: null,
        isOwn: true,
        attachments: [],
      }),
    ),
    editNote: jest.fn((_id: string, noteId: string, body: string) =>
      of<TicketNote>({
        id: noteId,
        author: MARA,
        body,
        at: '2026-10-15T06:20:00Z',
        editedAt: '2026-10-15T09:00:00Z',
        isOwn: true,
        attachments: [],
      }),
    ),
    blockSender: jest.fn((id: string) => of(detail({ id, senderBlocked: true }))),
    unblockSender: jest.fn((id: string) => of(detail({ id, senderBlocked: false }))),
    deleteNote: jest.fn(() => of(undefined)),
    list: jest.fn(() => of<TicketPage>({ items: [], total: 0, limit: 8, offset: 0 })),
    getMine: jest.fn((id: string) => (opts.mine ?? (() => of(mine({ id }))))(id)),
    addMyNote: jest.fn((_id: string, body: string, _files?: unknown) =>
      of<TicketNote>({
        id: 'n9',
        author: { principalId: 'r1', displayName: 'Lea Hoffmann' },
        body,
        at: '2026-10-15T09:00:00Z',
        editedAt: null,
        isOwn: true,
        attachments: [],
        visibility: 'public',
        fromReporter: true,
      }),
    ),
    editMyNote: jest.fn((_id: string, noteId: string, body: string) =>
      of<TicketNote>({
        id: noteId,
        author: { principalId: 'r1', displayName: 'Lea Hoffmann' },
        body,
        at: '2026-10-15T06:20:00Z',
        editedAt: '2026-10-15T09:00:00Z',
        isOwn: true,
        attachments: [],
      }),
    ),
    deleteMyNote: jest.fn(() => of(undefined)),
    attachmentUrl: (id: string) => `/api/attachments/${id}/download`,
  };
  const todosApi = {
    linked: jest.fn(() => todos),
    boards: jest.fn(() => of([])),
    board: jest.fn(),
    members: jest.fn(),
    createCard: jest.fn(),
  };
  const toast = { success: jest.fn(), error: jest.fn() };
  const files = {
    deleteDraftAttachment: jest.fn(() => of(undefined)),
    uploadDraftAttachment: jest.fn(),
  };
  const page = opts.split === null ? null : new TicketsPageService();
  page?.split.set(opts.split ?? false);
  const notify = page ? jest.spyOn(page, 'notify') : null;
  TestBed.configureTestingModule({
    providers: [
      provideRouter([{ path: 'tickets/:id', component: TicketDetailComponent }]),
      { provide: TicketsApiService, useValue: api },
      { provide: ApiClient, useValue: files },
      { provide: TodosApiService, useValue: todosApi },
      { provide: ToastService, useValue: toast },
      ...(page ? [{ provide: TicketsPageService, useValue: page }] : []),
      {
        provide: AuthService,
        useValue: {
          principal: signal(opts.me == null ? null : { email: opts.me }),
          isAuthenticated: signal(true),
          displayName: signal('Lea Hoffmann'),
          can: (p: string) => (opts.manager ?? true) && p === 'ticket.manage',
        },
      },
    ],
  });
  const harness = await RouterTestingHarness.create();
  const cmp = await harness.navigateByUrl(url, TicketDetailComponent);
  harness.detectChanges();
  const router = TestBed.inject(Router);
  const settle = async () => {
    await harness.fixture.whenStable();
    harness.detectChanges();
  };
  return {
    harness,
    page,
    cmp,
    api,
    files,
    todosApi,
    toast,
    router,
    notify,
    settle,
    setGet: (g: (id: string) => Observable<TicketDetail>) => (get = g),
    setTodos: (t: Observable<TodoLinkedCard[]>) => (todos = t),
  };
}

const notFound = () => new HttpErrorResponse({ status: 404 });

describe('TicketDetailComponent', () => {
  afterEach(() => localStorage.clear());

  it('shows the header with the state, the kind and the assignee', async () => {
    await start();
    expect(screen.getByRole('heading', { level: 2, name: /Protokoll-PDF/ })).toBeInTheDocument();
    const line = document.querySelector('.td__line')!;
    expect(line).toHaveTextContent('In Bearbeitung');
    expect(line).toHaveTextContent('Fehler');
    expect(line).toHaveTextContent('Mara Keller');
    expect(document.querySelector('app-sheet-bar')).toHaveTextContent(/Ticket · T-0040/);
    expect(document.querySelector('app-sheet-bar .mono')).toHaveTextContent('T-0040');
    expect(screen.getByRole('button', { name: /Erledigt/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Ablehnen' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Wieder öffnen/ })).not.toBeInTheDocument();
  });

  it('shows the thread with the report, the notes and the events in tabs', async () => {
    const { cmp } = await start();
    expect(screen.getByRole('tab', { name: /Verlauf/ })).toHaveAttribute('aria-selected', 'true');
    const msgs = cmp.messages();
    expect(msgs.map((m) => m.id)).toEqual(['ticket-body', 'n1']);
    expect(msgs[0].authorLabel).toBe('Tobias Brandt');
    expect(msgs[0].author).toEqual({ principalId: 'r1', displayName: 'Tobias Brandt' });
    expect(msgs[0].attachments![0].url).toBe('/api/attachments/a1/download');
    const events = cmp.events().map((e) => e.text);
    expect(events[0]).toBe('Eingangsbestätigung an Tobias Brandt gesendet');
    expect(events[1]).toBe('Mara Keller hat das Ticket übernommen');

    cmp.selectTab('details');
    cmp.selectTab('bogus');
    cmp.selectTab(null);
    expect(cmp.tab()).toBe('details');
  });

  it('shows the details: reporter, mail, the context and the linked object', async () => {
    await start('/tickets/t40', { split: true });
    expect(screen.getByRole('heading', { name: 'Verlauf' })).toHaveClass('sr-only');
    expect(screen.getByRole('link', { name: 'tobias@example.org' })).toHaveAttribute(
      'href',
      'mailto:tobias@example.org',
    );
    expect(
      screen.getByRole('link', { name: 'https://stupa.example.org/meetings/m1/protocol' }),
    ).toHaveAttribute('target', '_blank');
    expect(screen.getByText('v2026.10.10')).toBeInTheDocument();
    expect(screen.getByText('Safari 19 · macOS · 1512 × 945')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '33. Sitzung STUPA' })).toHaveAttribute(
      'href',
      '/meetings/m1',
    );
  });

  const fieldLabels = () =>
    [...document.querySelectorAll('[aria-labelledby="td-details"] app-field-row .fld__label')].map(
      (l) => l.textContent?.trim(),
    );

  it('pairs the fields side by side', async () => {
    await start('/tickets/t40', { split: true });
    expect(document.querySelectorAll('.td__pair')).toHaveLength(2);
    expect(fieldLabels()).toEqual(['Gemeldet von', 'Gemeldet', 'E-Mail', 'Zugewiesen', 'Art']);
  });

  it('puts the mail after the reporter in one column', async () => {
    await start('/tickets/t40', { split: false });
    expect(document.querySelectorAll('.td__pair')).toHaveLength(0);
    expect(fieldLabels()).toEqual(['Gemeldet von', 'E-Mail', 'Gemeldet', 'Zugewiesen', 'Art']);
  });

  it('shows the avatar of the assignee in the select, and none without one', async () => {
    const { cmp } = await start('/tickets/t40', {
      get: () => of(detail({ assignee: { principalId: 'p9', displayName: 'Selin' } })),
    });
    expect(cmp.assigneePerson()).toEqual({ name: 'Selin', principalId: 'p9' });
    cmp.ticket.set(detail({ assignee: null }));
    expect(cmp.assigneePerson()).toBeNull();
  });

  it('links an application, and leaves out what the context lacks', async () => {
    const { cmp } = await start('/tickets/t40', {
      get: () =>
        of(
          detail({
            reporter: { principalId: null, displayName: null, email: null, anonymized: true },
            context: { viewport: '390x844' },
            contextTarget: { kind: 'application', id: 'a9', title: 'Lastenrad' },
            attachments: [],
            anonymizedAt: '2026-11-01T00:00:00Z',
          }),
        ),
      split: true,
    });
    expect(cmp.contextRows()).toEqual([{ label: 'tickets.context.browser', value: '390 × 844' }]);
    expect(cmp.contextLink()).toEqual({ title: 'Lastenrad', link: ['/applications', 'a9'] });
    expect(cmp.messages()[0].author).toBeNull();
    expect(screen.queryByText('tobias@example.org')).not.toBeInTheDocument();
    expect(screen.getByText(/Anonymisiert am/)).toBeInTheDocument();
  });

  it('hides the technical details without any context', async () => {
    const { cmp } = await start('/tickets/t40', {
      get: () => of(detail({ context: { userAgent: 'curl/8.5' }, contextTarget: null })),
    });
    expect(cmp.contextRows()).toEqual([{ label: 'tickets.context.browser', value: 'curl/8.5' }]);
    cmp.ticket.set(detail({ context: {}, contextTarget: null }));
    expect(cmp.contextRows()).toEqual([]);
    expect(cmp.contextLink()).toBeNull();
  });

  it('marks a duplicate and offers "Wieder öffnen" for a closed ticket', async () => {
    const { cmp, api, harness } = await start('/tickets/t40', {
      get: () => of(detail({ status: 'rejected', duplicateOf: { id: 't12', number: 'T-0012' } })),
    });
    expect(screen.getByRole('link', { name: 'T-0012' })).toHaveAttribute('href', '/tickets/t12');
    expect(cmp.menuSections().map((s) => s.items.map((i) => i.id))).toEqual([['reset'], ['block']]);
    await userEvent.click(screen.getByRole('button', { name: /Wieder öffnen/ }));
    harness.detectChanges();
    expect(api.patch).toHaveBeenCalledWith('t40', { status: 'in_progress' });
  });

  it('puts the duplicate in its own section of the menu', async () => {
    const { cmp } = await start('/tickets/t40', {
      get: () => of(detail({ status: 'in_progress' })),
    });
    expect(cmp.menuSections().map((s) => s.items.map((i) => i.id))).toEqual([
      ['reset'],
      ['duplicate', 'block'],
    ]);
  });

  it('offers only the duplicate for a new ticket', async () => {
    const { cmp } = await start('/tickets/t40', { get: () => of(detail({ status: 'new' })) });
    expect(cmp.menuSections().map((s) => s.items.map((i) => i.id))).toEqual([
      ['duplicate', 'block'],
    ]);
  });

  it('offers the unblock for a blocked sender, and no block on an anonymized ticket', async () => {
    const { cmp, setGet, harness } = await start('/tickets/t40', {
      get: () => of(detail({ status: 'new', senderBlocked: true })),
    });
    const items = cmp.menuSections()[0].items;
    expect(items.map((i) => i.id)).toEqual(['duplicate', 'unblock']);
    expect(items[1]).toMatchObject({ label: 'Absender entsperren', icon: 'lock' });
    setGet(() => of(detail({ status: 'done', anonymizedAt: '2026-10-15T00:00:00Z' })));
    await harness.navigateByUrl('/tickets/t41');
    harness.detectChanges();
    expect(cmp.menuSections().map((s) => s.items.map((i) => i.id))).toEqual([['reset']]);
    // An anonymized ticket takes no note files.
    expect(
      harness.fixture.debugElement
        .query((d) => d.name === 'app-chat')
        .componentInstance.canAttach(),
    ).toBe(false);
  });

  it('blocks the sender at once from the menu, without a question, and unblocks at once', async () => {
    const { cmp, api, toast, harness } = await start();
    expect(
      harness.fixture.debugElement
        .query((d) => d.name === 'app-chat')
        .componentInstance.canAttach(),
    ).toBe(true);
    cmp.onMenu({ id: 'block', label: '' });
    harness.detectChanges();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(api.blockSender).toHaveBeenCalledWith('t40');
    expect(cmp.ticket()!.senderBlocked).toBe(true);
    expect(toast.success).toHaveBeenCalledWith('Absender gesperrt.');

    cmp.onMenu({ id: 'unblock', label: '' });
    expect(api.unblockSender).toHaveBeenCalledWith('t40');
    expect(cmp.ticket()!.senderBlocked).toBe(false);
    expect(toast.success).toHaveBeenCalledWith('Absender entsperrt.');
  });

  it('names a failed block, runs one at a time and drops the answer for a ticket the user left', async () => {
    const { cmp, api, toast, harness } = await start();
    api.blockSender.mockReturnValueOnce(throwError(() => new Error('x')));
    cmp.onMenu({ id: 'block', label: '' });
    expect(toast.error).toHaveBeenCalledWith('Die Sperre konnte nicht geändert werden.');
    expect(cmp.blocking()).toBe(false);

    const late = new Subject<TicketDetail>();
    api.unblockSender.mockReturnValueOnce(late);
    cmp.onMenu({ id: 'unblock', label: '' });
    expect(cmp.blocking()).toBe(true);
    cmp.onMenu({ id: 'block', label: '' });
    expect(api.blockSender).toHaveBeenCalledTimes(1);
    await harness.navigateByUrl('/tickets/t41');
    late.next(detail({ id: 't40', senderBlocked: false, title: 'Alt' }));
    expect(cmp.blocking()).toBe(false);
    expect(cmp.ticket()!.title).not.toBe('Alt');
  });

  it('offers no block on the own report, by the e-mail in any case', async () => {
    const { cmp } = await start('/tickets/t40', {
      me: ' Tobias@Example.org',
      get: () => of(detail({ status: 'new' })),
    });
    expect(cmp.menuSections().map((s) => s.items.map((i) => i.id))).toEqual([['duplicate']]);
  });

  it('offers the block while the viewer is not known', async () => {
    const { cmp } = await start('/tickets/t40', {
      me: null,
      get: () => of(detail({ status: 'new' })),
    });
    expect(cmp.menuSections()[0].items.map((i) => i.id)).toEqual(['duplicate', 'block']);
  });

  it('offers the block on a report without an e-mail', async () => {
    const { cmp } = await start('/tickets/t40', {
      me: 'tobias@example.org',
      get: () =>
        of(
          detail({
            status: 'new',
            reporter: { principalId: null, displayName: null, email: null, anonymized: false },
          }),
        ),
    });
    expect(cmp.menuSections()[0].items.map((i) => i.id)).toEqual(['duplicate', 'block']);
  });

  it('says why a block was refused', async () => {
    const { cmp, api, toast } = await start();
    const refuse = (status: number, error: unknown) =>
      api.blockSender.mockReturnValueOnce(
        throwError(() => new HttpErrorResponse({ status, error })),
      );
    refuse(422, { code: 'sender_is_self' });
    cmp.onMenu({ id: 'block', label: '' });
    expect(toast.error).toHaveBeenLastCalledWith('Das eigene Konto kann nicht gesperrt werden.');
    refuse(409, { code: 'ticket_sender_unknown' });
    cmp.onMenu({ id: 'block', label: '' });
    expect(toast.error).toHaveBeenLastCalledWith('Der Absender ist nicht mehr bekannt.');
    refuse(409, { code: 'other' });
    cmp.onMenu({ id: 'block', label: '' });
    expect(toast.error).toHaveBeenLastCalledWith('Die Sperre konnte nicht geändert werden.');
    refuse(500, null);
    cmp.onMenu({ id: 'block', label: '' });
    expect(toast.error).toHaveBeenLastCalledWith('Die Sperre konnte nicht geändert werden.');
  });

  it('closes a ticket without to-dos at once and tells the list', async () => {
    const { api, notify, harness } = await start();
    await userEvent.click(screen.getByRole('button', { name: /Erledigt/ }));
    harness.detectChanges();
    expect(api.patch).toHaveBeenCalledWith('t40', { status: 'done' });
    expect(notify).toHaveBeenCalledWith('t40');
    expect(screen.getByRole('button', { name: /Wieder öffnen/ })).toBeInTheDocument();
  });

  it('moves the focus to the button that replaces the status action', async () => {
    const { harness } = await start();
    const done = screen.getByRole('button', { name: /Erledigt/ });
    done.focus();
    await userEvent.click(done);
    harness.detectChanges();
    await harness.fixture.whenStable();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: /Wieder öffnen/ }));
    await userEvent.click(screen.getByRole('button', { name: /Wieder öffnen/ }));
    harness.detectChanges();
    await harness.fixture.whenStable();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: /Erledigt/ }));
  });

  it('asks first when open to-dos are linked, and completes them by default', async () => {
    const { cmp, api, todosApi, harness } = await start('/tickets/t40', {
      todos: of([
        card(),
        card({ id: 'c2', title: 'Zweite', isDone: true, dueDate: null, assignees: [] }),
      ]),
    });
    await userEvent.click(screen.getByRole('button', { name: /Erledigt/ }));
    harness.detectChanges();
    expect(screen.getByRole('dialog', { name: 'Ticket erledigen?' })).toBeInTheDocument();
    expect(screen.getByText('Offenes To-Do mit erledigen')).toBeInTheDocument();
    expect(cmp.completeTodos()).toBe(true);
    todosApi.linked.mockClear();
    cmp.confirmClose();
    harness.detectChanges();
    expect(api.patch).toHaveBeenCalledWith('t40', { status: 'done', completeTodos: true });
    expect(todosApi.linked).toHaveBeenCalled();
    // Without a question, a confirm does nothing.
    api.patch.mockClear();
    cmp.confirmClose();
    expect(api.patch).not.toHaveBeenCalled();
  });

  it('asks before a rejection with to-dos only the server counts', async () => {
    const { cmp, api, harness } = await start('/tickets/t40', {
      get: () => of(detail({ openTodoCount: 2 })),
    });
    cmp.close('rejected');
    harness.detectChanges();
    expect(screen.getByRole('dialog', { name: 'Ticket ablehnen?' })).toBeInTheDocument();
    expect(screen.getByText('2 offene To-Dos mit erledigen')).toBeInTheDocument();
    cmp.completeTodos.set(false);
    cmp.confirmClose();
    expect(api.patch).toHaveBeenCalledWith('t40', { status: 'rejected', completeTodos: false });
  });

  it('says "1 offenes To-Do" when only the server counts one', async () => {
    const { cmp, harness } = await start('/tickets/t40', {
      get: () => of(detail({ openTodoCount: 1 })),
    });
    cmp.close('done');
    harness.detectChanges();
    expect(cmp.openTodoN()).toBe(1);
    expect(screen.getByText('Offenes To-Do mit erledigen')).toBeInTheDocument();
  });

  it('lists the linked to-dos and links each to its board', async () => {
    const { cmp } = await start('/tickets/t40', {
      todos: of([
        card(),
        card({ id: 'c2', title: 'Zweite', isDone: true, dueDate: null, assignees: [] }),
      ]),
      split: true,
    });
    const link = screen.getByRole('link', { name: 'PDF-Kopf: Beginn statt Ende verwenden' });
    expect(link).toHaveAttribute('href', '/todos/b1?card=c1');
    expect(cmp.todoSub(card())).toBe('Plattform · In Arbeit · fällig 17.10.');
    expect(cmp.todoSub(card({ dueDate: null }))).toBe('Plattform · In Arbeit');
    expect(
      cmp.todoNames(card({ assignees: [MARA, { principalId: null, displayName: null }] })),
    ).toEqual(['Mara Keller', 'Gelöschte Person']);
    expect(cmp.todoIds(card())).toEqual(['p1']);
    expect(cmp.openTodos().map((c) => c.id)).toEqual(['c1']);
  });

  it('opens the to-do dialog and reloads after a new card', async () => {
    const { cmp, api, todosApi, harness } = await start('/tickets/t40', { split: true });
    await userEvent.click(screen.getByRole('button', { name: /To-Do anlegen/ }));
    harness.detectChanges();
    expect(cmp.todoOpen()).toBe(true);
    api.get.mockClear();
    todosApi.linked.mockClear();
    cmp.onTodoCreated();
    expect(api.get).toHaveBeenCalledWith('t40');
    expect(todosApi.linked).toHaveBeenCalledWith('ticket', 't40');
  });

  it('keeps no to-dos when their read fails', async () => {
    const { cmp } = await start('/tickets/t40', { todos: throwError(() => new Error('x')) });
    expect(cmp.todos()).toEqual([]);
  });

  it('drops to-dos and a ticket of a ticket the user left', async () => {
    const todos = new Subject<TodoLinkedCard[]>();
    const slow = new Subject<TicketDetail>();
    const { cmp, router, setGet, setTodos, settle } = await start('/tickets/t40', { todos });
    setGet((id) => (id === 't41' ? slow : of(detail({ id: 't42' }))));
    setTodos(of([]));
    await router.navigateByUrl('/tickets/t41');
    await router.navigateByUrl('/tickets/t42');
    await settle();
    todos.next([card()]);
    todos.error(new Error('late'));
    slow.next(detail({ id: 't41', title: 'Alt' }));
    expect(cmp.ticket()!.id).toBe('t42');
    expect(cmp.todos()).toEqual([]);
  });

  it('drops a late failure of a ticket the user left', async () => {
    const slow = new Subject<TicketDetail>();
    const { cmp, router, setGet, settle } = await start();
    setGet((id) => (id === 't41' ? slow : of(detail({ id: 't42' }))));
    await router.navigateByUrl('/tickets/t41');
    await router.navigateByUrl('/tickets/t42');
    await settle();
    slow.error(notFound());
    expect(cmp.notFound()).toBe(false);
  });

  it('drops a late to-do failure of a ticket the user left', async () => {
    const todos = new Subject<TodoLinkedCard[]>();
    const { cmp, router, setTodos, settle } = await start('/tickets/t40', { todos });
    setTodos(of([card()]));
    await router.navigateByUrl('/tickets/t41');
    await settle();
    todos.error(new Error('late'));
    expect(cmp.todos()).toHaveLength(1);
  });

  it('says that the ticket is not there', async () => {
    await start('/tickets/t40', { get: () => throwError(() => notFound()) });
    expect(screen.getByText('Ticket nicht gefunden')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Zur Liste' })).toHaveAttribute('href', '/tickets');
  });

  it('names only the ticket number in the kicker', async () => {
    await start('/tickets/t40');
    const kicker = document.querySelector('app-sheet-bar [appSheetBarKicker]');
    expect(kicker?.textContent?.trim()).toBe('Ticket · T-0040');
  });

  it('names a failed read', async () => {
    const { cmp } = await start('/tickets/t40', { get: () => throwError(() => new Error('down')) });
    expect(screen.getByRole('alert')).toHaveTextContent('Das Ticket konnte nicht geladen werden.');
    // Without a ticket the header parts fall back.
    expect(cmp.kicker()).toBe('');
    expect(cmp.kickerParts()).toEqual({ before: '', number: '', after: '' });
    expect(cmp.reporter()).toBe('');
    expect(cmp.statusKind()).toBe('accent');
    expect(cmp.statusLabel()).toBe('Neu');
    expect(cmp.kindLabel()).toBe('Fehler');
    expect(cmp.kindIcon()).toBe('bug');
    expect(cmp.assigneeName()).toBe('Niemand');
    expect(cmp.menuSections()).toEqual([]);
    expect(cmp.messages()).toEqual([]);
    expect(cmp.events()).toEqual([]);
    expect(cmp.contextRows()).toEqual([]);
    expect(cmp.open()).toBe(false);
    cmp.close('done');
  });

  it('shows the skeleton while the ticket loads', async () => {
    await start('/tickets/t40', { get: () => new Subject<TicketDetail>() });
    expect(document.querySelector('[aria-busy="true"]')).not.toBeNull();
    // The loaded shape: the head, then the chat with its bubbles and its composer.
    expect(document.querySelector('.td__head .td__skelTitle')).not.toBeNull();
    expect(document.querySelectorAll('.td__chat .sk__msg').length).toBeGreaterThan(0);
    expect(document.querySelector('.td__chat .sk__composer')).not.toBeNull();
    expect(screen.getByRole('status')).toHaveTextContent('Ticket wird geladen');
  });

  it('reloads the same ticket in place', async () => {
    const { cmp, router, settle, api } = await start();
    api.get.mockClear();
    await router.navigateByUrl('/tickets/t40?x=1');
    await settle();
    cmp.onTodoCreated();
    expect(cmp.loading()).toBe(false);
    expect(api.get).toHaveBeenCalled();
  });

  it('changes the assignee and the kind, and only on a real change', async () => {
    const { cmp, api } = await start();
    cmp.setAssignee('p1');
    expect(api.patch).not.toHaveBeenCalled();
    cmp.setAssignee('p2');
    expect(api.patch).toHaveBeenLastCalledWith('t40', { assigneeId: 'p2' });
    cmp.setAssignee('');
    expect(api.patch).toHaveBeenLastCalledWith('t40', { assigneeId: null });
    api.patch.mockClear();
    cmp.setKind('bug');
    cmp.setKind('nonsense');
    expect(api.patch).not.toHaveBeenCalled();
    cmp.setKind('idea');
    expect(api.patch).toHaveBeenLastCalledWith('t40', { kind: 'idea' });
  });

  it('unassigns from a ticket without an assignee only on a change', async () => {
    const { cmp, api } = await start('/tickets/t40', { get: () => of(detail({ assignee: null })) });
    expect(cmp.assigneeName()).toBe('Niemand');
    cmp.setAssignee('');
    expect(api.patch).not.toHaveBeenCalled();
  });

  it('lists the possible assignees once each, with the current one', async () => {
    const { cmp } = await start('/tickets/t40', {
      get: () => of(detail({ assignee: { principalId: 'p9', displayName: 'Selin' } })),
    });
    expect(cmp.assigneeOptions().map((o) => o.value)).toEqual(['', 'p1', 'p2', 'p9']);
    cmp.assignees.set([MARA, MARA]);
    expect(cmp.assigneeOptions().map((o) => o.value)).toEqual(['', 'p1', 'p9']);
  });

  it('works without the list of people', async () => {
    const { cmp } = await start('/tickets/t40', { assignees: throwError(() => new Error('x')) });
    expect(cmp.assignees()).toEqual([]);
  });

  it.each([
    ['assignee_not_allowed', 'Diese Person kann keine Tickets bearbeiten.'],
    ['duplicate_invalid', 'Das Duplikat konnte nicht gesetzt werden.'],
    ['other', 'Die Änderung konnte nicht gespeichert werden.'],
  ])('names a refused change (%s)', async (code, text) => {
    const { cmp, api, toast } = await start();
    api.patch.mockReturnValueOnce(
      throwError(() => new HttpErrorResponse({ status: 422, error: { code } })),
    );
    cmp.setKind('idea');
    expect(toast.error).toHaveBeenCalledWith(text);
    expect(cmp.saving()).toBeNull();
  });

  it('names a failed change without a problem body', async () => {
    const { cmp, api, toast } = await start();
    api.patch.mockReturnValueOnce(throwError(() => new Error('offline')));
    cmp.setKind('idea');
    expect(toast.error).toHaveBeenCalledWith('Die Änderung konnte nicht gespeichert werden.');
  });

  it('runs one change at a time and drops the answer for a ticket the user left', async () => {
    const pending = new Subject<TicketDetail>();
    const { cmp, api, router, settle, notify } = await start();
    api.patch.mockReturnValueOnce(pending);
    cmp.setKind('idea');
    cmp.setKind('question');
    cmp.close('done');
    expect(api.patch).toHaveBeenCalledTimes(1);
    await router.navigateByUrl('/tickets/t41');
    await settle();
    pending.next(detail({ kind: 'idea' }));
    expect(notify).not.toHaveBeenCalled();
    expect(cmp.saving()).toBeNull();
  });

  it('closes as a duplicate of a found ticket', async () => {
    const hits: TicketListItem[] = [
      detail(),
      detail({ id: 't12', number: 'T-0012', title: 'Gleicher Fehler', status: 'done' }),
    ];
    const { cmp, api, harness, settle } = await start();
    api.list.mockReturnValue(of({ items: hits, total: 2, limit: 8, offset: 0 }));
    cmp.onMenu({ id: 'duplicate', label: '' });
    harness.detectChanges();
    expect(screen.getByRole('dialog', { name: 'Als Duplikat schließen' })).toBeInTheDocument();
    cmp.duplicateSearch.set('Fehler');
    cmp.duplicateSearch.flush();
    await settle();
    expect(api.list).toHaveBeenCalledWith({ q: 'Fehler', limit: 8, offset: 0 });
    // The ticket itself is no candidate.
    expect(cmp.duplicateHits().map((h) => h.id)).toEqual(['t12']);
    expect(screen.getByText('Erledigt', { selector: '.td__dupState' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Gleicher Fehler/ }));
    expect(api.patch).toHaveBeenCalledWith('t40', { status: 'rejected', duplicateOfId: 't12' });
    expect(cmp.duplicateOpen()).toBe(false);
  });

  it('asks about the open to-dos before it closes as a duplicate', async () => {
    const { cmp, api, harness } = await start('/tickets/t40', {
      get: () => of(detail({ status: 'new', openTodoCount: 1 })),
    });
    cmp.onMenu({ id: 'duplicate', label: '' });
    cmp.pickDuplicate(detail({ id: 't12', number: 'T-0012' }));
    harness.detectChanges();
    expect(api.patch).not.toHaveBeenCalled();
    expect(cmp.duplicateOpen()).toBe(false);
    expect(screen.getByRole('dialog', { name: 'Ticket ablehnen?' })).toBeInTheDocument();
    cmp.confirmClose();
    expect(api.patch).toHaveBeenCalledWith('t40', {
      status: 'rejected',
      duplicateOfId: 't12',
      completeTodos: true,
    });
  });

  it('forgets the duplicate when the question is cancelled', async () => {
    const { cmp, api } = await start('/tickets/t40', {
      get: () => of(detail({ status: 'new', openTodoCount: 1 })),
    });
    cmp.pickDuplicate(detail({ id: 't12', number: 'T-0012' }));
    cmp.cancelClose();
    expect(cmp.closing()).toBeNull();
    cmp.close('rejected');
    cmp.completeTodos.set(false);
    cmp.confirmClose();
    expect(api.patch).toHaveBeenCalledWith('t40', { status: 'rejected', completeTodos: false });
  });

  it('says that the duplicate search found nothing, and empties on a failure', async () => {
    const { cmp, api, harness, settle } = await start();
    cmp.onMenu({ id: 'duplicate', label: '' });
    cmp.duplicateSearch.set('nichts');
    cmp.duplicateSearch.flush();
    await settle();
    harness.detectChanges();
    expect(screen.getByText('Kein Ticket gefunden.')).toBeInTheDocument();
    api.list.mockReturnValue(throwError(() => new Error('x')));
    cmp.duplicateHits.set([detail({ id: 'x' })]);
    cmp.duplicateSearch.set('kaputt');
    cmp.duplicateSearch.flush();
    await settle();
    expect(cmp.duplicateHits()).toEqual([]);
    cmp.duplicateHits.set([detail({ id: 'x' })]);
    cmp.duplicateSearch.set('');
    cmp.duplicateSearch.flush();
    await settle();
    expect(cmp.duplicateHits()).toEqual([]);
  });

  it('resets a ticket to "Neu" from the menu', async () => {
    const { cmp, api } = await start();
    cmp.onMenu({ id: 'reset', label: '' });
    expect(api.patch).toHaveBeenCalledWith('t40', { status: 'new' });
    api.patch.mockClear();
    cmp.onMenu({ id: 'other', label: '' });
    expect(api.patch).not.toHaveBeenCalled();
  });

  it('copies the link of the ticket, and names a failure', async () => {
    const { cmp, toast } = await start('/tickets/t40?kind=bug');
    expect(screen.getByRole('button', { name: 'Link kopieren' })).toBeInTheDocument();
    const writeText = jest.fn(async (_text: string) => undefined);
    const original = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    try {
      await cmp.copyLink();
      expect(writeText).toHaveBeenCalledWith(location.href.split('?')[0]);
      expect(toast.success).toHaveBeenCalledWith('Link kopiert.');
      writeText.mockRejectedValueOnce(new Error('denied'));
      await cmp.copyLink();
      expect(toast.error).toHaveBeenCalledWith('Der Link konnte nicht kopiert werden.');
    } finally {
      if (original) Object.defineProperty(navigator, 'clipboard', original);
    }
  });

  it('opens a link to a note in the log and scrolls the note into view', async () => {
    const proto = Element.prototype as { scrollIntoView?: unknown };
    const before = proto.scrollIntoView;
    const scroll = jest.fn();
    proto.scrollIntoView = scroll;
    try {
      const { cmp, harness } = await start('/tickets/t40#note-n1');
      harness.detectChanges();
      await harness.fixture.whenStable();
      expect(cmp.tab()).toBe('log');
      expect(scroll).toHaveBeenCalledWith({ block: 'center' });
    } finally {
      proto.scrollIntoView = before;
    }
  });

  it('leaves the log at its end for a link to a note that is gone', async () => {
    const proto = Element.prototype as { scrollIntoView?: unknown };
    const before = proto.scrollIntoView;
    const scroll = jest.fn();
    proto.scrollIntoView = scroll;
    try {
      const { harness } = await start('/tickets/t40#note-gone');
      await harness.fixture.whenStable();
      expect(scroll).not.toHaveBeenCalled();
    } finally {
      proto.scrollIntoView = before;
    }
  });

  it('offers the staff the ticket team after "@", and the reporter nobody', async () => {
    const { cmp } = await start();
    expect(cmp.mentionables().map((p: { displayName: string }) => p.displayName)).toEqual(
      expect.arrayContaining([MARA.displayName, JONAS.displayName]),
    );
    expect(cmp.mentionables()).toHaveLength(2);
  });

  it('sends, edits and deletes notes, and never the report', async () => {
    const { cmp, api, toast } = await start();
    cmp.sendNote({ body: 'Fix ist offen.' });
    expect(api.addNote).toHaveBeenCalledWith(
      't40',
      'Fix ist offen.',
      { body: 'Fix ist offen.' },
      undefined,
      undefined,
    );
    cmp.sendNote({ body: '@Ada hilft', mentions: ['p-ada'] });
    expect(api.addNote).toHaveBeenLastCalledWith(
      't40',
      '@Ada hilft',
      { body: '@Ada hilft', mentions: ['p-ada'] },
      undefined,
      ['p-ada'],
    );
    expect(cmp.notes().map((n) => n.id)).toEqual(['n1', 'n9']);

    cmp.editNote({ id: 'n1', body: 'Prüfe ich morgen.' });
    expect(api.editNote).toHaveBeenCalledWith('t40', 'n1', 'Prüfe ich morgen.', undefined);
    expect(cmp.notes()[0].body).toBe('Prüfe ich morgen.');
    cmp.deleteNote({ id: 'n9' });
    expect(cmp.notes().map((n) => n.id)).toEqual(['n1']);

    api.editNote.mockClear();
    api.deleteNote.mockClear();
    cmp.editNote({ id: 'ticket-body', body: 'x' });
    cmp.deleteNote({ id: 'ticket-body' });
    expect(api.editNote).not.toHaveBeenCalled();
    expect(api.deleteNote).not.toHaveBeenCalled();

    api.editNote.mockReturnValueOnce(throwError(() => new Error('x')));
    const restore = jest.fn();
    cmp.editNote({ id: 'n1', body: 'y', restore });
    expect(restore).toHaveBeenCalledTimes(1);
    api.deleteNote.mockReturnValueOnce(throwError(() => new Error('x')));
    cmp.deleteNote({ id: 'n1' });
    expect(toast.error).toHaveBeenCalledTimes(2);
    expect(toast.error).toHaveBeenCalledWith('Die Notiz konnte nicht gespeichert werden.');
  });

  it('keeps a failed note and sends it again', async () => {
    const { cmp, api } = await start();
    api.addNote.mockReturnValueOnce(throwError(() => new Error('offline')));
    cmp.sendNote({ body: 'Später' });
    const failed = cmp.messages().at(-1)!;
    expect(failed.state).toBe('failed');
    cmp.retryNote({ id: failed.id });
    expect(cmp.notes().at(-1)!.body).toBe('Später');
  });

  it('says why a note failed, and discards it on request', async () => {
    const { cmp, api, toast } = await start();
    api.addNote.mockReturnValueOnce(
      throwError(() => ({
        status: 422,
        error: {
          errors: [{ field: 'body.body', msg: 'String should have at most 10000 characters' }],
        },
      })),
    );
    cmp.sendNote({ body: 'Zu lang' });
    expect(toast.error).toHaveBeenCalledWith('Die Nachricht ist zu lang.');
    const failed = cmp.messages().at(-1)!;
    cmp.discardNote({ id: failed.id });
    expect(cmp.messages().some((m) => m.id === failed.id)).toBe(false);
  });

  it('shows the files of the notes and of the report with their scan state', async () => {
    const { cmp } = await start('/tickets/t40', {
      get: () =>
        of(
          detail({
            attachments: [
              { id: 'a2', filename: 'neu.png', mime: 'image/png', size: 5, scanned: false },
            ],
          }),
        ),
    });
    const [body, note] = cmp.messages();
    expect(body.attachments).toEqual([
      {
        id: 'a2',
        filename: 'neu.png',
        mime: 'image/png',
        size: 5,
        url: '/api/attachments/a2/download',
        scanState: 'scanning',
      },
    ]);
    expect(note.attachments).toEqual([
      {
        id: 'f1',
        filename: 'log.txt',
        mime: 'text/plain',
        size: 10,
        scanState: 'clean',
        url: '/api/attachments/f1/download',
      },
    ]);
  });

  it('shows a report file with a finding as quarantined, not as a link', () => {
    const a = { id: 'a', filename: 'a.png', mime: 'image/png', size: 1 };
    expect(reportScanState({ ...a, scanned: true, scanState: 'quarantined' })).toBe('quarantined');
    expect(reportScanState({ ...a, scanned: false, scanState: 'scanning' })).toBe('scanning');
    expect(reportScanState({ ...a, scanned: true })).toBe('clean');
    expect(reportScanState({ ...a, scanned: false })).toBe('scanning');
  });

  it('reads the ticket again when the chat asks, for the scan state of its files', async () => {
    const { cmp, api, setGet, harness } = await start();
    const note = (scanState: 'scanning' | 'clean') =>
      detail({
        notes: [
          {
            id: 'n1',
            author: MARA,
            body: 'Log',
            at: '2026-10-15T06:20:00Z',
            editedAt: null,
            isOwn: true,
            attachments: [{ id: 'f9', filename: 'a.png', mime: 'image/png', size: 1, scanState }],
          },
        ],
      });
    cmp.notes.set(note('scanning').notes);
    setGet(() => of(note('clean')));
    harness.fixture.debugElement.query((d) => d.name === 'app-chat').triggerEventHandler('refresh');
    expect(api.get).toHaveBeenLastCalledWith('t40');
    expect(cmp.notes()[0].attachments[0].scanState).toBe('clean');

    // A failed read keeps the page; an answer for a ticket the user left is dropped.
    setGet(() => throwError(() => new Error('offline')));
    cmp.refreshThread();
    expect(cmp.error()).toBe(false);
    const late = new Subject<TicketDetail>();
    setGet((id) => (id === 't40' ? late : of(detail({ id: 't41' }))));
    cmp.refreshThread();
    await harness.navigateByUrl('/tickets/t41');
    late.next(note('scanning'));
    expect(cmp.ticket()!.id).toBe('t41');
  });

  it('takes only the scan states of a background read, never older notes or an older block', async () => {
    const { cmp, setGet } = await start();
    const stale = new Subject<TicketDetail>();
    setGet(() => stale);
    cmp.refreshThread();
    // While the read is in flight: a note goes out, n1 goes away, the sender gets blocked.
    cmp.sendNote({ body: 'Neu' });
    cmp.deleteNote({ id: 'n1' });
    cmp.onMenu({ id: 'block', label: '' });
    expect(cmp.ticket()!.senderBlocked).toBe(true);
    stale.next(
      detail({
        attachments: [
          {
            id: 'a1',
            filename: 'protokoll-kopf.png',
            mime: 'image/png',
            size: 98304,
            scanned: true,
            scanState: 'quarantined',
          },
        ],
        senderBlocked: false,
      }),
    );
    expect(cmp.notes().map((n) => n.id)).toEqual(['n9']);
    expect(cmp.ticket()!.senderBlocked).toBe(true);
    expect(cmp.messages()[0].attachments![0].scanState).toBe('quarantined');

    // A report file the read does not know keeps its state; a delivered note joins once.
    setGet(() => of(detail({ attachments: [], notes: [{ ...detail().notes[0], id: 'n9' }] })));
    cmp.refreshThread();
    expect(cmp.messages()[0].attachments![0].scanState).toBe('quarantined');
    cmp.sendNote({ body: 'Neu' });
    expect(cmp.notes().map((n) => n.id)).toEqual(['n9']);
  });

  it('takes the note scan states of a read that lands before the ticket', async () => {
    const first = new Subject<TicketDetail>();
    const { cmp, setGet } = await start('/tickets/t40', { get: () => first });
    expect(cmp.ticket()).toBeNull();
    setGet(() => of(detail()));
    cmp.refreshThread();
    expect(cmp.ticket()).toBeNull();
    expect(cmp.notes()).toEqual([]);
  });

  it('keeps the composer files with the page when the layout switch re-creates the chat', async () => {
    const { harness, page } = await start();
    const drafts = () =>
      harness.fixture.debugElement
        .query((d) => d.name === 'app-chat')
        .injector.get(DraftAttachmentsService);
    const chat = () =>
      harness.fixture.debugElement.query((d) => d.name === 'app-chat').componentInstance;
    const before = drafts();
    const old = chat();
    page!.split.set(true);
    harness.detectChanges();
    expect(chat()).not.toBe(old);
    expect(drafts()).toBe(before);
  });

  it('sends a note with files, and deletes the drafts of a discarded one', async () => {
    const { cmp, api, files } = await start();
    const file = {
      id: 'd1',
      filename: 'a.png',
      mime: 'image/png',
      size: 3,
      scanState: 'scanning' as const,
      url: '/x',
    };
    api.addNote.mockReturnValueOnce(throwError(() => new Error('offline')));
    cmp.sendNote({ body: '', attachmentIds: ['d1'], draftToken: 'tok', files: [file] });
    expect(api.addNote).toHaveBeenCalledWith(
      't40',
      '',
      expect.objectContaining({ attachmentIds: ['d1'], draftToken: 'tok' }),
      undefined,
      undefined,
    );
    const failed = cmp.messages().at(-1)!;
    expect(failed.attachments).toEqual([file]);
    cmp.discardNote({ id: failed.id });
    expect(files.deleteDraftAttachment).toHaveBeenCalledWith('d1', 'tok');
  });

  it('runs without the list page as one pane', async () => {
    const { cmp } = await start('/tickets/t40', { split: null });
    expect(cmp.split()).toBe(false);
    cmp.setKind('idea');
    expect(cmp.ticket()!.kind).toBe('idea');
  });

  it('names the tabs without a count', async () => {
    const { cmp } = await start();
    expect(cmp.tabs()[0]).toEqual({ id: 'log', label: 'Verlauf' });
  });

  describe('as the reporter', () => {
    it('reads the own ticket without the work of the team', async () => {
      const { cmp, api, todosApi } = await start('/tickets/t40', { manager: false, split: true });
      expect(api.getMine).toHaveBeenCalledWith('t40');
      expect(api.get).not.toHaveBeenCalled();
      expect(api.assignees).not.toHaveBeenCalled();
      expect(todosApi.linked).not.toHaveBeenCalled();
      expect(screen.getByRole('heading', { level: 2, name: /Wo finde ich/ })).toBeInTheDocument();
      const line = document.querySelector('.td__line')!;
      expect(line).toHaveTextContent('In Bearbeitung');
      expect(line).toHaveTextContent('Frage');
      expect(line).not.toHaveTextContent('Niemand');
      expect(screen.queryByRole('button', { name: /Erledigt/ })).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Ablehnen' })).not.toBeInTheDocument();
      expect(cmp.menuSections()).toEqual([]);
      expect(screen.queryByText('Technische Angaben')).not.toBeInTheDocument();
      expect(screen.queryByText('Gemeldet von')).not.toBeInTheDocument();
      expect(cmp.visibilityOptions()).toEqual([]);
      expect(cmp.placeholder()).toBe('chat.placeholder');
      const [report, note] = cmp.messages();
      expect(report.own).toBe(true);
      expect(report.canEdit).toBe(false);
      expect(report.authorLabel).toBeNull();
      expect(note.visibility).toBeNull();
      expect(cmp.events()[0].text).toBe('Status Neu → In Bearbeitung');
    });

    it('writes, edits and deletes own messages through the reporter routes', async () => {
      const { cmp, api } = await start('/tickets/t40', { manager: false });
      cmp.sendNote({ body: 'Danke!' });
      expect(api.addMyNote).toHaveBeenCalledWith('t40', 'Danke!', { body: 'Danke!' });
      expect(api.addNote).not.toHaveBeenCalled();
      expect(cmp.messages().at(-1)!.body).toBe('Danke!');
      cmp.editNote({ id: 'n9', body: 'Danke sehr!' });
      expect(api.editMyNote).toHaveBeenCalledWith('t40', 'n9', 'Danke sehr!');
      cmp.deleteNote({ id: 'n9' });
      expect(api.deleteMyNote).toHaveBeenCalledWith('t40', 'n9');
      expect(cmp.notes().map((n) => n.id)).toEqual(['n1']);
      cmp.refreshThread();
      expect(api.getMine).toHaveBeenCalledTimes(2);
    });

    it('hides the composer while a block holds the reporter back', async () => {
      const { cmp } = await start('/tickets/t40', {
        manager: false,
        mine: (id) => of(mine({ id, canReply: false })),
      });
      expect(cmp.canReply()).toBe(false);
    });

    it('closes the composer when a block arrives while the ticket is open', async () => {
      const { cmp, api, toast } = await start('/tickets/t40', { manager: false });
      const blocked = new HttpErrorResponse({ status: 403, error: { code: 'sender_blocked' } });
      api.editMyNote.mockReturnValueOnce(throwError(() => blocked));
      cmp.editNote({ id: 'n9', body: 'x' });
      expect(cmp.canReply()).toBe(false);
      expect(toast.error).toHaveBeenLastCalledWith(
        'Du kannst auf dieses Ticket nicht mehr antworten.',
      );
      cmp.canReply.set(true);
      api.addMyNote.mockReturnValueOnce(throwError(() => blocked));
      cmp.sendNote({ body: 'noch was' });
      expect(cmp.canReply()).toBe(false);
      api.editMyNote.mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 403 })));
      cmp.editNote({ id: 'n9', body: 'y' });
      expect(toast.error).toHaveBeenLastCalledWith('Die Notiz konnte nicht gespeichert werden.');
    });

    it('names a ticket of somebody else as not found', async () => {
      await start('/tickets/t99', { manager: false, mine: () => throwError(() => notFound()) });
      expect(screen.getByText('Ticket nicht gefunden')).toBeInTheDocument();
    });
  });

  describe('the visibility of a team note', () => {
    it('offers internal first on a ticket of an account and marks every note', async () => {
      const { cmp, api } = await start();
      expect(cmp.visibilityOptions()).toEqual(['internal', 'public']);
      expect(cmp.placeholder()).toBe('chat.placeholder');
      const [report, note] = cmp.messages();
      expect(report.visibility).toBe('public');
      expect(note.visibility).toBe('internal');
      cmp.sendNote({ body: 'Antwort', visibility: 'public' });
      expect(api.addNote).toHaveBeenCalledWith(
        't40',
        'Antwort',
        { body: 'Antwort', visibility: 'public' },
        'public',
        undefined,
      );
    });

    it('keeps every note internal on a report without an account', async () => {
      const { cmp } = await start('/tickets/t40', {
        get: () =>
          of(
            detail({
              reporter: {
                principalId: null,
                displayName: null,
                email: 'x@example.org',
                anonymized: false,
              },
            }),
          ),
      });
      expect(cmp.visibilityOptions()).toEqual([]);
      expect(cmp.placeholder()).toBe('tickets.detail.notePlaceholder');
      expect(cmp.messages()[0].visibility).toBeNull();
    });
  });
});
