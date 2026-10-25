import { fireEvent, render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { Subject, of, throwError, type Observable } from 'rxjs';
import {
  TodosApiService,
  type TodoBoard,
  type TodoBoardSummary,
  type TodoCardCreate,
  type TodoLinkTarget,
  type TodoMember,
} from '@core/api/todos.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { BOARDS, MEMBERS, board, detail } from '../../../../testing/todo-fixtures';
import { TodoNewDialogComponent, type NewTodoLink } from './todo-new-dialog.component';
import { LINK_ICON } from '../todos.util';
import { MarkdownImageUploadDirective } from '@shared/markdown/markdown-image-upload.directive';
import { pickOption } from '../../../../testing/select';

interface Opts {
  boards?: TodoBoardSummary[];
  boardsFail?: boolean;
  boardFail?: boolean;
  membersFail?: boolean;
  inputs?: Record<string, unknown>;
}

async function setup(opts: Opts = {}) {
  const api = {
    boards: jest.fn(() => (opts.boardsFail ? throwError(() => new Error('x')) : of(opts.boards ?? BOARDS))),
    board: jest.fn((id: string) => (opts.boardFail ? throwError(() => new Error('x')) : of(board({ id })))),
    members: jest.fn(() => (opts.membersFail ? throwError(() => new Error('x')) : of(MEMBERS))),
    createCard: jest.fn(() => of(detail())),
    linkTargets: jest.fn(() => of([])),
  };
  const toast = { success: jest.fn(), error: jest.fn() };
  const created = jest.fn();
  const view = await render(TodoNewDialogComponent, {
    inputs: { open: false, ...opts.inputs },
    on: { created },
    providers: [
      { provide: TodosApiService, useValue: api },
      { provide: ToastService, useValue: toast },
    ],
  });
  const cmp = view.fixture.componentInstance;
  const open = () => {
    cmp.open.set(true);
    view.fixture.detectChanges();
  };
  return { ...view, api, toast, created, cmp, open };
}

describe('TodoNewDialogComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  /** Only boards that take cards show, and people get a fallback name. */
  it('starts on the given board and column with the given title and links', async () => {
    const links: NewTodoLink[] = [{ kind: 'agenda_item', targetId: 't-1', label: 'TOP 5 · Haushalt' }];
    const { cmp, open, api } = await setup({
      inputs: { boardId: 'b-2', columnId: 'c-2', initialTitle: 'Bus', initialLinks: links },
    });
    open();
    expect(screen.getByRole('dialog', { name: 'Neues To-Do' })).toBeInTheDocument();
    expect(api.board).toHaveBeenCalledWith('b-2');
    expect(cmp.selectedBoard()).toBe('b-2');
    expect(cmp.column()).toBe('c-2');
    expect(cmp.title()).toBe('Bus');
    expect(screen.getByText('TOP 5 · Haushalt')).toBeInTheDocument();
    expect(cmp.boardOptions().map((o) => o.value)).toEqual(['b-0', 'b-1', 'b-2', 'b-3']);
    expect(cmp.memberOptions().map((o) => o.label)).toEqual(['Niemand', 'Selin Yıldız', 'Jonas Weber', 'Gelöschte Person']);
    expect(cmp.columnOptions().map((o) => o.label)).toEqual(['Offen', 'In Arbeit', 'Wartet', 'Erledigt']);
  });

  it('starts on the board of the gremium', async () => {
    const byGremium = await setup({ inputs: { gremiumId: 'g-2' } });
    byGremium.open();
    expect(byGremium.cmp.selectedBoard()).toBe('b-2');
    expect(byGremium.cmp.column()).toBe('c-1');
  });

  it('else starts on the first writable board and its first column', async () => {
    const first = await setup({
      boards: [{ ...BOARDS[0], canWrite: false }, BOARDS[1]],
      inputs: { boardId: 'b-0', gremiumId: 'g-9', columnId: 'nope' },
    });
    first.open();
    expect(first.cmp.selectedBoard()).toBe('b-1');
    expect(first.cmp.column()).toBe('c-1');
  });

  it('says so when no board takes cards', async () => {
    const none = await setup({ boards: [{ ...BOARDS[0], canWrite: false }] });
    none.open();
    expect(screen.getByRole('alert')).toHaveTextContent('Kein Board, in dem du To-Dos anlegen darfst.');
  });

  it('says so when the boards fail', async () => {
    const failing = await setup({ boardsFail: true });
    failing.open();
    expect(failing.cmp.noBoard()).toBe(true);
  });

  it('keeps going when the board or its people fail', async () => {
    const { cmp, open } = await setup({ boardFail: true, membersFail: true });
    open();
    expect(cmp.board()).toBeNull();
    expect(cmp.column()).toBe('');
    expect(cmp.members()).toEqual([]);
  });

  it('leaves the column empty for a board without columns', async () => {
    const { cmp, open, api } = await setup();
    api.board.mockReturnValue(of(board({ columns: [], cards: [] })) as never);
    open();
    expect(cmp.column()).toBe('');
  });

  it('drops a late answer of a board that is no longer chosen', async () => {
    const { cmp, open, api } = await setup();
    open();
    const { Subject } = await import('rxjs');
    const late = new Subject<ReturnType<typeof board>>();
    const lateMembers = new Subject<typeof MEMBERS>();
    api.board.mockReturnValueOnce(late as never);
    api.members.mockReturnValueOnce(lateMembers as never);
    cmp.setBoard('b-2');
    cmp.setBoard('b-3');
    late.next(board({ id: 'b-2', columns: [{ id: 'x', name: 'X', position: 0, isDone: false, cardCount: 0 }] }));
    lateMembers.next([]);
    late.error(new Error('x'));
    expect(cmp.board()?.id).toBe('b-3');
    expect(cmp.members()).toEqual(MEMBERS);
    const failLate = new Subject<typeof MEMBERS>();
    api.members.mockReturnValueOnce(failLate as never);
    cmp.setBoard('b-1');
    cmp.setBoard('b-2');
    failLate.error(new Error('x'));
    expect(cmp.members()).toEqual(MEMBERS);
  });

  /** The button opens and closes the picker. */
  it('adds a picked target, takes a linked one off and removes a chip', async () => {
    const { cmp, open, fixture } = await setup();
    open();
    cmp.pickLink({ kind: 'ticket', targetId: 't-7', title: 'Login', detail: null });
    fixture.detectChanges();
    expect(screen.getByText('Ticket · Login')).toBeInTheDocument();
    expect(cmp.linkedKeys().has('ticket:t-7')).toBe(true);
    cmp.pickLink({ kind: 'ticket', targetId: 't-7', title: 'Login', detail: null });
    expect(cmp.links()).toEqual([]);
    cmp.pickLink({ kind: 'todo', targetId: 'k-9', title: 'Andere', detail: null });
    fixture.detectChanges();
    fireEvent.click(screen.getByRole('button', { name: 'Verknüpfung mit To-Do · Andere entfernen' }));
    expect(cmp.links()).toEqual([]);
    expect(cmp.icon('ticket')).toBe(LINK_ICON.ticket);
    fireEvent.click(screen.getByRole('button', { name: /Verknüpfen/ }));
    expect(cmp.pickerOpen()).toBe(true);
  });

  it('checks the title and creates the card with every field', async () => {
    const { cmp, open, api, toast, created, fixture } = await setup({
      inputs: { initialLinks: [{ kind: 'application', targetId: 'a-1', label: 'Antrag · X' }] },
    });
    open();
    expect(cmp.canSave()).toBe(false);
    cmp.save();
    expect(api.createCard).not.toHaveBeenCalled();
    cmp.title.set('x'.repeat(301));
    expect(cmp.titleError()).toBe('Höchstens 300 Zeichen.');
    expect(cmp.canSave()).toBe(false);
    cmp.title.set('  Raum buchen ');
    cmp.assignee.set('p-2');
    cmp.due.set('2026-10-23');
    cmp.description.set(' Raum **A** ');
    fixture.detectChanges();
    fireEvent.click(screen.getByRole('button', { name: 'Anlegen' }));
    expect(api.createCard).toHaveBeenCalledWith({
      boardId: 'b-0',
      columnId: 'c-1',
      title: 'Raum buchen',
      descriptionMd: 'Raum **A**',
      dueDate: '2026-10-23',
      assigneeIds: ['p-2'],
      links: [{ kind: 'application', targetId: 'a-1' }],
    });
    expect(toast.success).toHaveBeenCalledWith('To-Do angelegt');
    expect(created).toHaveBeenCalledWith(detail());
    expect(cmp.open()).toBe(false);
  });

  it('sends the empty fields as empty and names the error of the server', async () => {
    const { cmp, open, api, toast } = await setup();
    open();
    cmp.title.set('Bus');
    cmp.column.set('');
    for (const [code, text] of [
      ['assignee_not_allowed', 'Diese Person kann dem Board nicht zugewiesen werden.'],
      ['link_target_not_found', 'Das Ziel gibt es nicht oder du hast keinen Zugriff.'],
      [undefined, 'Das To-Do konnte nicht angelegt werden.'],
    ] as const) {
      api.createCard.mockReturnValueOnce(throwError(() => ({ error: code ? { code } : undefined })) as never);
      cmp.save();
      expect(toast.error).toHaveBeenLastCalledWith(text);
      expect(cmp.saving()).toBe(false);
    }
    expect(api.createCard).toHaveBeenLastCalledWith(
      expect.objectContaining({ columnId: undefined, descriptionMd: null, dueDate: null, assigneeIds: [] }),
    );
    api.createCard.mockReturnValueOnce(throwError(() => null) as never);
    cmp.save();
    expect(toast.error).toHaveBeenLastCalledWith('Das To-Do konnte nicht angelegt werden.');
  });

  it('does not create the card while an image uploads', async () => {
    const { cmp, open, api, fixture, debugElement } = await setup();
    open();
    cmp.title.set('Bus');
    fixture.detectChanges();
    const images = debugElement
      .query((d) => d.nativeElement instanceof HTMLTextAreaElement)
      .injector.get(MarkdownImageUploadDirective);
    images.uploading.set(1);
    fixture.detectChanges();
    expect(cmp.canSave()).toBe(false);
    expect(screen.getByRole('button', { name: 'Anlegen' })).toBeDisabled();
    cmp.save();
    expect(api.createCard).not.toHaveBeenCalled();
    images.uploading.set(0);
    expect(cmp.canSave()).toBe(true);
  });

  it('cancels', async () => {
    const { cmp, open } = await setup();
    open();
    fireEvent.click(screen.getAllByRole('button', { name: 'Abbrechen' }).at(-1)!);
    expect(cmp.open()).toBe(false);
  });
});

/** The dialog as the ticket page opens it ("To-Do aus Ticket anlegen"). */
describe('TodoNewDialogComponent from a ticket', () => {
  const TICKET = { id: 't40', number: 'T-0040', title: 'Protokoll-PDF zeigt im Kopf das falsche Datum' };
  const TICKET_LINK: NewTodoLink = {
    kind: 'ticket',
    targetId: TICKET.id,
    label: `Ticket · ${TICKET.number} ${TICKET.title}`,
  };

  function ticketBoard(
    id: string,
    columns = [
      { id: `${id}-c2`, name: 'In Arbeit', position: 2, isDone: false, cardCount: 0 },
      { id: `${id}-c1`, name: 'Offen', position: 1, isDone: false, cardCount: 0 },
    ],
  ): TodoBoard {
    return board({ id, name: id, kind: 'team', gremiumId: null, columns, cards: [] });
  }

  const TICKET_MEMBERS: TodoMember[] = [
    { principalId: 'p1', displayName: 'Mara Keller' },
    { principalId: 'p2', displayName: null },
  ];

  const TICKET_BOARDS: TodoBoardSummary[] = [
    { ...BOARDS[1], id: 'gb', name: 'StuPa', kind: 'gremium', gremiumId: 'g1', canWrite: true },
    { ...BOARDS[1], id: 'pb', name: 'Persönlich', kind: 'personal', gremiumId: null, canWrite: true },
    { ...BOARDS[1], id: 'tb', name: 'Plattform', kind: 'team', gremiumId: null, canWrite: true },
    { ...BOARDS[1], id: 'ro', name: 'Nur lesen', kind: 'team', gremiumId: null, canWrite: false },
  ];

  interface TicketOpts {
    boards?: Observable<TodoBoardSummary[]>;
    board?: (id: string) => Observable<TodoBoard>;
    members?: (id: string) => Observable<TodoMember[]>;
    create?: jest.Mock;
  }

  async function ticketSetup(opts: TicketOpts = {}) {
    localStorage.setItem('ap.locale', 'de');
    const api = {
      boards: jest.fn(() => opts.boards ?? of(TICKET_BOARDS)),
      board: jest.fn((id: string) => (opts.board ?? ((b: string) => of(ticketBoard(b))))(id)),
      members: jest.fn((id: string) => (opts.members ?? (() => of(TICKET_MEMBERS)))(id)),
      createCard: opts.create ?? jest.fn((_b: TodoCardCreate) => of(detail({ id: 'card1' }))),
      linkTargets: jest.fn(() => of([])),
    };
    const toast = { success: jest.fn(), error: jest.fn() };
    const created = jest.fn();
    const view = await render(TodoNewDialogComponent, {
      inputs: {
        heading: 'tickets.todo.title',
        withDescription: false,
        boardKinds: ['team', 'personal'],
        initialTitle: TICKET.title,
        initialLinks: [TICKET_LINK],
        open: true,
      },
      on: { created },
      providers: [
        { provide: TodosApiService, useValue: api },
        { provide: ToastService, useValue: toast },
      ],
    });
    await view.fixture.whenStable();
    view.fixture.detectChanges();
    const c = view.fixture.componentInstance;
    return { ...view, c, api, toast, created };
  }

  const createButton = () => screen.getByRole('button', { name: 'Anlegen' });

  afterEach(() => localStorage.clear());

  /** Read-only boards are no choice. */
  it('starts from the ticket, the team board and its first column, without a description', async () => {
    const { c, api } = await ticketSetup();
    expect(screen.getByRole('dialog', { name: 'To-Do aus Ticket anlegen' })).toBeInTheDocument();
    expect(c.title()).toBe(TICKET.title);
    expect(c.selectedBoard()).toBe('tb');
    expect(api.board).toHaveBeenCalledWith('tb');
    expect(c.column()).toBe('tb-c1');
    expect(c.boardOptions().map((o) => o.value)).toEqual(['gb', 'pb', 'tb']);
    expect(c.columnOptions().map((o) => o.label)).toEqual(['Offen', 'In Arbeit']);
    expect(c.memberOptions().map((o) => o.label)).toEqual(['Niemand', 'Mara Keller', 'Gelöschte Person']);
    expect(screen.getByText('Ticket · T-0040 Protokoll-PDF zeigt im Kopf das falsche Datum')).toBeInTheDocument();
    expect(screen.queryByLabelText('Beschreibung (Markdown)')).toBeNull();
  });

  it('creates the card with the link to the ticket and closes', async () => {
    const { c, api, toast, created, fixture } = await ticketSetup();
    c.assignee.set('p1');
    c.due.set('2026-10-17');
    c.title.set('  PDF-Kopf: Beginn statt Ende  ');
    fixture.detectChanges();
    await userEvent.click(createButton());
    expect(api.createCard).toHaveBeenCalledWith({
      boardId: 'tb',
      columnId: 'tb-c1',
      title: 'PDF-Kopf: Beginn statt Ende',
      descriptionMd: null,
      dueDate: '2026-10-17',
      assigneeIds: ['p1'],
      links: [{ kind: 'ticket', targetId: 't40' }],
    });
    expect(toast.success).toHaveBeenCalledWith('To-Do angelegt');
    expect(created).toHaveBeenCalled();
    expect(c.open()).toBe(false);
  });

  it('takes the link to the ticket off and puts it back with the picker', async () => {
    const { c, api, fixture } = await ticketSetup();
    await userEvent.click(
      screen.getByRole('button', {
        name: 'Verknüpfung mit Ticket · T-0040 Protokoll-PDF zeigt im Kopf das falsche Datum entfernen',
      }),
    );
    fixture.detectChanges();
    expect(c.linkedKeys().has('ticket:t40')).toBe(false);
    c.save();
    expect(api.createCard).toHaveBeenLastCalledWith(expect.objectContaining({ links: [], assigneeIds: [], dueDate: null }));
    c.pickLink({ kind: 'ticket', targetId: 't40', title: TICKET.title } as TodoLinkTarget);
    expect(c.linkedKeys().has('ticket:t40')).toBe(true);
  });

  it('adds further links after the ticket', async () => {
    const { c, api, fixture } = await ticketSetup();
    const top = { kind: 'agenda_item', targetId: 'a2', title: 'Haushaltsplan 2027' } as TodoLinkTarget;
    c.pickLink(top);
    c.pickLink({ kind: 'meeting', targetId: 'm1', title: '33. Sitzung' } as TodoLinkTarget);
    fixture.detectChanges();
    expect(c.linkedKeys()).toEqual(new Set(['agenda_item:a2', 'meeting:m1', 'ticket:t40']));
    c.pickLink(top);
    c.pickLink({ kind: 'meeting', targetId: 'm1', title: '33. Sitzung' } as TodoLinkTarget);
    c.pickLink({ kind: 'todo', targetId: 'c9', title: 'Kassenprüfung' } as TodoLinkTarget);
    c.save();
    expect(api.createCard).toHaveBeenLastCalledWith(
      expect.objectContaining({
        links: [
          { kind: 'ticket', targetId: 't40' },
          { kind: 'todo', targetId: 'c9' },
        ],
      }),
    );
  });

  it('switches the board, drops the person and leaves a board without columns to the server', async () => {
    const { c, api } = await ticketSetup({
      board: (id) => of(ticketBoard(id, id === 'gb' ? [] : undefined)),
    });
    c.assignee.set('p1');
    c.setBoard('gb');
    expect(api.members).toHaveBeenLastCalledWith('gb');
    expect(c.assignee()).toBe('');
    expect(c.column()).toBe('');
    c.save();
    expect(api.createCard).toHaveBeenLastCalledWith(expect.objectContaining({ boardId: 'gb', columnId: undefined }));
  });

  it.each([
    ['the personal board', [TICKET_BOARDS[0], TICKET_BOARDS[1]], 'pb'],
    ['the first writable board', [TICKET_BOARDS[0]], 'gb'],
  ])('falls back to %s', async (_label, boards, id) => {
    const { c } = await ticketSetup({ boards: of(boards) });
    expect(c.selectedBoard()).toBe(id);
  });

  it('says that no board takes a card', async () => {
    const { c } = await ticketSetup({ boards: of([TICKET_BOARDS[3]]) });
    expect(c.noBoard()).toBe(true);
    expect(screen.getByRole('alert')).toHaveTextContent('Kein Board, in dem du To-Dos anlegen darfst.');
    expect(createButton()).toBeDisabled();
  });

  it('drops the answers of a board the user left', async () => {
    const slowBoard = new Subject<TodoBoard>();
    const slowMembers = new Subject<TodoMember[]>();
    const { c } = await ticketSetup({
      board: (id) => (id === 'gb' ? slowBoard : of(ticketBoard(id))),
      members: (id) => (id === 'gb' ? slowMembers : of(TICKET_MEMBERS)),
    });
    c.setBoard('gb');
    c.setBoard('pb');
    slowBoard.next(ticketBoard('gb'));
    slowMembers.next([]);
    expect(c.column()).toBe('pb-c1');
    expect(c.members()).toEqual(TICKET_MEMBERS);
  });

  it('closes on Abbrechen and starts from the ticket again on the next opening', async () => {
    const { c, api, fixture } = await ticketSetup();
    c.title.set('Anders');
    c.unlink(TICKET_LINK);
    await userEvent.click(screen.getAllByRole('button', { name: 'Abbrechen' }).at(-1)!);
    expect(c.open()).toBe(false);
    c.open.set(true);
    fixture.detectChanges();
    await fixture.whenStable();
    expect(c.title()).toBe(TICKET.title);
    expect(c.links()).toEqual([TICKET_LINK]);
    expect(api.boards).toHaveBeenCalledTimes(2);
  });

  it('sets the column, the person, the board and the title from the fields', async () => {
    const { c, fixture } = await ticketSetup();
    await pickOption(screen.getByLabelText('Spalte'), 'In Arbeit');
    expect(c.column()).toBe('tb-c2');
    await pickOption(screen.getByLabelText('Zuständig'), 'Mara Keller');
    expect(c.assignee()).toBe('p1');
    await pickOption(screen.getByLabelText('Board'), 'Persönlich');
    fixture.detectChanges();
    expect(c.selectedBoard()).toBe('pb');
    await userEvent.clear(screen.getByLabelText(/Titel/));
    await userEvent.type(screen.getByLabelText(/Titel/), 'Neu');
    expect(c.title()).toBe('Neu');
  });
});
