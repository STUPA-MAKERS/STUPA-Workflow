import { HttpErrorResponse } from '@angular/common/http';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { Observable, Subject, of, throwError } from 'rxjs';
import type { TicketDetail } from '@core/api/tickets.service';
import {
  TodosApiService,
  type TodoBoard,
  type TodoBoardSummary,
  type TodoCardCreate,
  type TodoLinkTarget,
  type TodoMember,
} from '@core/api/todos.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { TicketTodoDialogComponent } from './ticket-todo-dialog.component';
import { pickOption } from '../../../../testing/select';

const TICKET = {
  id: 't40',
  number: 'T-0040',
  title: 'Protokoll-PDF zeigt im Kopf das falsche Datum',
} as TicketDetail;

function summary(over: Partial<TodoBoardSummary>): TodoBoardSummary {
  return {
    id: 'b1',
    name: 'Plattform',
    kind: 'team',
    gremiumId: null,
    canWrite: true,
    canConfigure: false,
    openCount: 3,
    ...over,
  };
}

function board(id: string, columns = [
  { id: `${id}-c2`, name: 'In Arbeit', position: 2, isDone: false, cardCount: 0 },
  { id: `${id}-c1`, name: 'Offen', position: 1, isDone: false, cardCount: 0 },
]): TodoBoard {
  return {
    id,
    name: id,
    kind: 'team',
    gremiumId: null,
    archiveAfterDays: null,
    canWrite: true,
    canConfigure: false,
    columns,
    labels: [],
    cards: [],
    archivedCount: 0,
  };
}

const MEMBERS: TodoMember[] = [
  { principalId: 'p1', displayName: 'Mara Keller' },
  { principalId: 'p2', displayName: null },
];

const BOARDS = [
  summary({ id: 'gb', name: 'StuPa', kind: 'gremium', gremiumId: 'g1' }),
  summary({ id: 'pb', name: 'Persönlich', kind: 'personal' }),
  summary({ id: 'tb', name: 'Plattform', kind: 'team' }),
  summary({ id: 'ro', name: 'Nur lesen', kind: 'team', canWrite: false }),
];

interface Opts {
  boards?: Observable<TodoBoardSummary[]>;
  board?: (id: string) => Observable<TodoBoard>;
  members?: (id: string) => Observable<TodoMember[]>;
  create?: jest.Mock;
}

async function setup(opts: Opts = {}) {
  localStorage.setItem('ap.locale', 'de');
  const api = {
    boards: jest.fn(() => opts.boards ?? of(BOARDS)),
    board: jest.fn((id: string) => (opts.board ?? ((b: string) => of(board(b))))(id)),
    members: jest.fn((id: string) => (opts.members ?? (() => of(MEMBERS)))(id)),
    createCard: opts.create ?? jest.fn((_b: TodoCardCreate) => of({ id: 'card1' })),
  };
  const toast = { success: jest.fn(), error: jest.fn() };
  const created = jest.fn();
  const view = await render(TicketTodoDialogComponent, {
    inputs: { ticket: TICKET, open: true },
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

describe('TicketTodoDialogComponent', () => {
  afterEach(() => localStorage.clear());

  it('starts from the ticket, the team board and its first column', async () => {
    const { c, api } = await setup();
    expect(screen.getByRole('dialog', { name: 'To-Do aus Ticket anlegen' })).toBeInTheDocument();
    expect(c.title()).toBe(TICKET.title);
    expect(c.boardId()).toBe('tb');
    expect(api.board).toHaveBeenCalledWith('tb');
    expect(c.columnId()).toBe('tb-c1');
    // Read-only boards are no choice.
    expect(c.boardOptions().map((o) => o.value)).toEqual(['gb', 'pb', 'tb']);
    expect(c.columnOptions().map((o) => o.label)).toEqual(['In Arbeit', 'Offen']);
    expect(c.memberOptions().map((o) => o.label)).toEqual(['Niemand', 'Mara Keller', 'Gelöschte Person']);
    const chip = document.querySelector('.ttd__chipText');
    expect(chip?.textContent?.replace(/\s+/g, ' ').trim()).toBe('Ticket · T-0040 Protokoll-PDF zeigt im Kopf das falsche Datum');
  });

  it('creates the card with the link and closes', async () => {
    const { c, api, toast, created, fixture } = await setup();
    c.assigneeId.set('p1');
    c.dueDate.set('2026-10-17');
    c.title.set('  PDF-Kopf: Beginn statt Ende  ');
    fixture.detectChanges();
    await userEvent.click(createButton());
    expect(api.createCard).toHaveBeenCalledWith({
      boardId: 'tb',
      columnId: 'tb-c1',
      title: 'PDF-Kopf: Beginn statt Ende',
      dueDate: '2026-10-17',
      assigneeIds: ['p1'],
      links: [{ kind: 'ticket', targetId: 't40' }],
    });
    expect(toast.success).toHaveBeenCalledWith('To-Do angelegt.');
    expect(created).toHaveBeenCalled();
    expect(c.open()).toBe(false);
  });

  it('takes the link off and puts it back', async () => {
    const { c, api, fixture } = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Verknüpfung entfernen' }));
    fixture.detectChanges();
    expect(c.linked()).toBe(false);
    c.save();
    expect(api.createCard).toHaveBeenLastCalledWith(expect.objectContaining({ links: [], assigneeIds: [], dueDate: null }));
    // The picker puts the ticket back.
    c.pickLink({ kind: 'ticket', targetId: 't40', title: TICKET.title } as TodoLinkTarget);
    expect(c.linked()).toBe(true);
  });

  it('adds further links with the picker and takes them off again', async () => {
    const { c, api, fixture } = await setup();
    expect(screen.getByRole('button', { name: 'Verknüpfen' })).toBeTruthy();
    const top = { kind: 'agenda_item', targetId: 'a2', title: 'Haushaltsplan 2027' } as TodoLinkTarget;
    c.pickLink(top);
    c.pickLink({ kind: 'meeting', targetId: 'm1', title: '33. Sitzung' } as TodoLinkTarget);
    fixture.detectChanges();
    expect(c.linkedKeys()).toEqual(new Set(['agenda_item:a2', 'meeting:m1', 'ticket:t40']));
    expect(screen.getByText('Haushaltsplan 2027')).toBeTruthy();
    // A second pick of a linked target takes it off; the chip's × does the same.
    c.pickLink(top);
    fixture.detectChanges();
    await userEvent.click(screen.getByRole('button', { name: 'Verknüpfung mit 33. Sitzung entfernen' }));
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

  it('switches the board and its columns and members', async () => {
    const { c, api } = await setup({
      board: (id) => of(board(id, id === 'gb' ? [] : undefined)),
    });
    c.assigneeId.set('p1');
    c.setBoard('gb');
    expect(api.members).toHaveBeenLastCalledWith('gb');
    expect(c.assigneeId()).toBe('');
    // A board without columns: the server takes its first one.
    expect(c.columnId()).toBe('');
    c.save();
    expect(api.createCard).toHaveBeenLastCalledWith(expect.objectContaining({ boardId: 'gb', columnId: undefined }));
  });

  it.each([
    ['the personal board', [BOARDS[0], BOARDS[1]], 'pb'],
    ['the first writable board', [BOARDS[0]], 'gb'],
  ])('falls back to %s', async (_label, boards, id) => {
    const { c } = await setup({ boards: of(boards) });
    expect(c.boardId()).toBe(id);
  });

  it('says that no board takes a card', async () => {
    const { c } = await setup({ boards: of([BOARDS[3]]) });
    expect(c.noBoard()).toBe(true);
    expect(screen.getByRole('alert')).toHaveTextContent('Es gibt kein Board, in dem du To-Dos anlegen kannst.');
    expect(createButton()).toBeDisabled();
  });

  it('says that no board takes a card when the boards fail', async () => {
    const { c } = await setup({ boards: throwError(() => new Error('x')) });
    expect(c.noBoard()).toBe(true);
  });

  it('keeps the selects empty when a board or its members fail', async () => {
    const { c } = await setup({
      board: () => throwError(() => new Error('x')),
      members: () => throwError(() => new Error('x')),
    });
    expect(c.board()).toBeNull();
    expect(c.members()).toEqual([]);
  });

  it('drops the answers of a board the user left', async () => {
    const slowBoard = new Subject<TodoBoard>();
    const slowMembers = new Subject<TodoMember[]>();
    const { c } = await setup({
      board: (id) => (id === 'gb' ? slowBoard : of(board(id))),
      members: (id) => (id === 'gb' ? slowMembers : of(MEMBERS)),
    });
    c.setBoard('gb');
    c.setBoard('pb');
    slowBoard.next(board('gb'));
    slowMembers.next([]);
    expect(c.columnId()).toBe('pb-c1');
    expect(c.members()).toEqual(MEMBERS);
  });

  it('drops the failures of a board the user left', async () => {
    const slowBoard = new Subject<TodoBoard>();
    const slowMembers = new Subject<TodoMember[]>();
    const { c } = await setup({
      board: (id) => (id === 'gb' ? slowBoard : of(board(id))),
      members: (id) => (id === 'gb' ? slowMembers : of(MEMBERS)),
    });
    c.setBoard('gb');
    c.setBoard('pb');
    slowBoard.error(new Error('late'));
    slowMembers.error(new Error('late'));
    expect(c.board()!.id).toBe('pb');
    expect(c.members()).toEqual(MEMBERS);
  });

  it('refuses an empty or a too long title', async () => {
    const { c, api, fixture } = await setup();
    c.title.set('   ');
    expect(c.canSave()).toBe(false);
    c.title.set('x'.repeat(301));
    fixture.detectChanges();
    expect(screen.getByText('Höchstens 300 Zeichen.')).toBeInTheDocument();
    c.save();
    expect(api.createCard).not.toHaveBeenCalled();
  });

  it.each([
    ['assignee_not_allowed', 'Diese Person ist kein Mitglied des Boards.'],
    [undefined, 'Das To-Do konnte nicht angelegt werden.'],
  ])('names a refused card (%s)', async (code, text) => {
    const create = jest.fn(() => throwError(() => new HttpErrorResponse({ status: 422, error: code ? { code } : null })));
    const { c, toast } = await setup({ create });
    c.save();
    expect(toast.error).toHaveBeenCalledWith(text);
    expect(c.saving()).toBe(false);
    expect(c.open()).toBe(true);
  });

  it('names a failure without a problem body', async () => {
    const create = jest.fn(() => throwError(() => undefined));
    const { c, toast } = await setup({ create });
    c.save();
    expect(toast.error).toHaveBeenCalledWith('Das To-Do konnte nicht angelegt werden.');
  });

  it('closes on Abbrechen and starts again on the next opening', async () => {
    const { c, api, fixture } = await setup();
    c.title.set('Anders');
    await userEvent.click(screen.getAllByRole('button', { name: 'Abbrechen' }).at(-1)!);
    expect(c.open()).toBe(false);
    c.open.set(true);
    fixture.detectChanges();
    await fixture.whenStable();
    expect(c.title()).toBe(TICKET.title);
    expect(api.boards).toHaveBeenCalledTimes(2);
  });

  it('sets the column, the person and the date from the fields', async () => {
    const { c, fixture } = await setup();
    await pickOption(screen.getByLabelText('Spalte'), 'In Arbeit');
    await pickOption(screen.getByLabelText('Zuständig'), 'Mara Keller');
    await pickOption(screen.getByLabelText('Board'), 'Persönlich');
    fixture.detectChanges();
    expect(c.boardId()).toBe('pb');
    await userEvent.clear(screen.getByLabelText(/Titel/));
    await userEvent.type(screen.getByLabelText(/Titel/), 'Neu');
    expect(c.title()).toBe('Neu');
  });
});
