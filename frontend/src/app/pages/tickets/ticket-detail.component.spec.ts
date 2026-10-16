import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { Observable, Subject, of, throwError } from 'rxjs';
import type { PersonRef } from '@core/api/models';
import {
  TicketsApiService,
  type TicketDetail,
  type TicketListItem,
  type TicketNote,
  type TicketPage,
  type TicketPatch,
} from '@core/api/tickets.service';
import { TodosApiService, type TodoLinkedCard } from '@core/api/todos.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { TicketDetailComponent } from './ticket-detail.component';
import { TicketsPageService } from './tickets-page.service';

const MARA: PersonRef = { principalId: 'p1', displayName: 'Mara Keller' };
const JONAS: PersonRef = { principalId: 'p2', displayName: 'Jonas Albrecht' };

function detail(over: Partial<TicketDetail> = {}): TicketDetail {
  return {
    id: 't40',
    number: 'T-0040',
    kind: 'bug',
    title: 'Protokoll-PDF zeigt im Kopf das falsche Datum',
    status: 'in_progress',
    reporter: { principalId: 'r1', displayName: 'Tobias Brandt', email: 'tobias@example.org', anonymized: false },
    assignee: MARA,
    createdAt: '2026-10-14T19:14:00Z',
    updatedAt: '2026-10-15T06:12:00Z',
    body: 'Im Protokoll steht das falsche Datum.',
    context: {
      url: 'https://stupa.example.org/meetings/m1/protocol',
      route: '/meetings/m1/protocol',
      appVersion: 'v2026.10.10',
      userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/19.0 Safari/605.1.15',
      viewport: '1512x945',
    },
    attachments: [{ id: 'a1', filename: 'protokoll-kopf.png', mime: 'image/png', size: 98304, scanned: true }],
    notes: [
      { id: 'n1', author: MARA, body: 'Prüfe ich.', at: '2026-10-15T06:20:00Z', editedAt: null, isOwn: true },
    ],
    events: [
      { id: 'e1', kind: 'created', actor: null, at: '2026-10-14T19:14:00Z', payload: { confirmationSent: true } },
      { id: 'e2', kind: 'assignee', actor: MARA, at: '2026-10-15T06:12:00Z', payload: { to: MARA } },
    ],
    duplicateOf: null,
    contextTarget: { kind: 'meeting', id: 'm1', title: '33. Sitzung STUPA' },
    openTodoCount: 0,
    closedAt: null,
    anonymizedAt: null,
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
}

async function start(url = '/tickets/t40', opts: Opts = {}) {
  localStorage.setItem('ap.locale', 'de');
  let get = opts.get ?? (() => of(detail()));
  let todos = opts.todos ?? of<TodoLinkedCard[]>([]);
  const api = {
    get: jest.fn((id: string) => get(id)),
    assignees: jest.fn(() => opts.assignees ?? of([MARA, JONAS, { principalId: null, displayName: 'Weg' }])),
    patch: jest.fn((id: string, body: TicketPatch) => of(detail({ ...body, id } as Partial<TicketDetail>))),
    addNote: jest.fn((_id: string, body: string) =>
      of<TicketNote>({ id: 'n9', author: MARA, body, at: '2026-10-15T09:00:00Z', editedAt: null, isOwn: true }),
    ),
    editNote: jest.fn((_id: string, noteId: string, body: string) =>
      of<TicketNote>({ id: noteId, author: MARA, body, at: '2026-10-15T06:20:00Z', editedAt: '2026-10-15T09:00:00Z', isOwn: true }),
    ),
    deleteNote: jest.fn(() => of(undefined)),
    list: jest.fn(() => of<TicketPage>({ items: [], total: 0, limit: 8, offset: 0 })),
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
  const page = opts.split === null ? null : new TicketsPageService();
  page?.split.set(opts.split ?? false);
  const notify = page ? jest.spyOn(page, 'notify') : null;
  TestBed.configureTestingModule({
    providers: [
      provideRouter([{ path: 'tickets/:id', component: TicketDetailComponent }]),
      { provide: TicketsApiService, useValue: api },
      { provide: TodosApiService, useValue: todosApi },
      { provide: ToastService, useValue: toast },
      ...(page ? [{ provide: TicketsPageService, useValue: page }] : []),
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
    cmp,
    api,
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
    expect(document.querySelector('app-sheet-bar')).toHaveTextContent(/Ticket · T-0040 · gemeldet/);
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
    expect(screen.getByRole('heading', { name: 'Verlauf' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'tobias@example.org' })).toHaveAttribute('href', 'mailto:tobias@example.org');
    expect(screen.getByRole('link', { name: 'https://stupa.example.org/meetings/m1/protocol' })).toHaveAttribute(
      'target',
      '_blank',
    );
    expect(screen.getByText('v2026.10.10')).toBeInTheDocument();
    expect(screen.getByText('Safari 19 · macOS · 1512 × 945')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '33. Sitzung STUPA' })).toHaveAttribute('href', '/meetings/m1');
  });

  const fieldLabels = () =>
    [...document.querySelectorAll('[aria-labelledby="td-details"] app-field-row .fld__label')].map((l) =>
      l.textContent?.trim(),
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
    expect(cmp.menuSections()[0].items.map((i) => i.id)).toEqual(['reset']);
    await userEvent.click(screen.getByRole('button', { name: /Wieder öffnen/ }));
    harness.detectChanges();
    expect(api.patch).toHaveBeenCalledWith('t40', { status: 'in_progress' });
  });

  it('puts the duplicate in its own section of the menu', async () => {
    const { cmp } = await start('/tickets/t40', { get: () => of(detail({ status: 'in_progress' })) });
    expect(cmp.menuSections().map((s) => s.items.map((i) => i.id))).toEqual([['reset'], ['duplicate']]);
  });

  it('offers only the duplicate for a new ticket', async () => {
    const { cmp } = await start('/tickets/t40', { get: () => of(detail({ status: 'new' })) });
    expect(cmp.menuSections()[0].items.map((i) => i.id)).toEqual(['duplicate']);
  });

  it('closes a ticket without to-dos at once and tells the list', async () => {
    const { api, notify, harness } = await start();
    await userEvent.click(screen.getByRole('button', { name: /Erledigt/ }));
    harness.detectChanges();
    expect(api.patch).toHaveBeenCalledWith('t40', { status: 'done' });
    expect(notify).toHaveBeenCalledWith('t40');
    expect(screen.getByRole('button', { name: /Wieder öffnen/ })).toBeInTheDocument();
  });

  it('asks first when open to-dos are linked, and completes them by default', async () => {
    const { cmp, api, todosApi, harness } = await start('/tickets/t40', {
      todos: of([card(), card({ id: 'c2', title: 'Zweite', isDone: true, dueDate: null, assignees: [] })]),
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
    const { cmp, api, harness } = await start('/tickets/t40', { get: () => of(detail({ openTodoCount: 2 })) });
    cmp.close('rejected');
    harness.detectChanges();
    expect(screen.getByRole('dialog', { name: 'Ticket ablehnen?' })).toBeInTheDocument();
    expect(screen.getByText('2 offene To-Dos mit erledigen')).toBeInTheDocument();
    cmp.completeTodos.set(false);
    cmp.confirmClose();
    expect(api.patch).toHaveBeenCalledWith('t40', { status: 'rejected', completeTodos: false });
  });

  it('says "1 offenes To-Do" when only the server counts one', async () => {
    const { cmp, harness } = await start('/tickets/t40', { get: () => of(detail({ openTodoCount: 1 })) });
    cmp.close('done');
    harness.detectChanges();
    expect(cmp.openTodoN()).toBe(1);
    expect(screen.getByText('Offenes To-Do mit erledigen')).toBeInTheDocument();
  });

  it('lists the linked to-dos and links each to its board', async () => {
    const { cmp } = await start('/tickets/t40', {
      todos: of([card(), card({ id: 'c2', title: 'Zweite', isDone: true, dueDate: null, assignees: [] })]),
      split: true,
    });
    const link = screen.getByRole('link', { name: 'PDF-Kopf: Beginn statt Ende verwenden' });
    expect(link).toHaveAttribute('href', '/todos/b1?card=c1');
    expect(cmp.todoSub(card())).toBe('Plattform · In Arbeit · fällig 17.10.');
    expect(cmp.todoSub(card({ dueDate: null }))).toBe('Plattform · In Arbeit');
    expect(cmp.todoNames(card({ assignees: [MARA, { principalId: null, displayName: null }] }))).toEqual([
      'Mara Keller',
      'Gelöschte Person',
    ]);
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

  it('names the report time relative to today in the kicker', async () => {
    const { cmp } = await start('/tickets/t40');
    const rel = (at: Date) => (cmp as unknown as { relativeWhen(at: string): string }).relativeWhen(at.toISOString());
    expect(rel(new Date())).toMatch(/^heute, \d\d:\d\d$/);
    expect(rel(new Date(Date.now() - 86_400_000))).toMatch(/^gestern, \d\d:\d\d$/);
    expect(rel(new Date('2026-01-05T09:00:00Z'))).toMatch(/^05\.01\., \d\d:\d\d$/);
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
    api.patch.mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 422, error: { code } })));
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
    const hits: TicketListItem[] = [detail(), detail({ id: 't12', number: 'T-0012', title: 'Gleicher Fehler', status: 'done' })];
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

  it('sends, edits and deletes notes, and never the report', async () => {
    const { cmp, api, toast } = await start();
    cmp.sendNote({ body: 'Fix ist offen.' });
    expect(api.addNote).toHaveBeenCalledWith('t40', 'Fix ist offen.');
    expect(cmp.notes().map((n) => n.id)).toEqual(['n1', 'n9']);

    cmp.editNote({ id: 'n1', body: 'Prüfe ich morgen.' });
    expect(api.editNote).toHaveBeenCalledWith('t40', 'n1', 'Prüfe ich morgen.');
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
    cmp.editNote({ id: 'n1', body: 'y' });
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
});
