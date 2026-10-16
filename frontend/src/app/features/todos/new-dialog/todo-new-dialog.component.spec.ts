import { fireEvent, render, screen } from '@testing-library/angular';
import { of, throwError } from 'rxjs';
import { TodosApiService, type TodoBoardSummary } from '@core/api/todos.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { BOARDS, MEMBERS, board, detail } from '../../../../testing/todo-fixtures';
import { TodoNewDialogComponent, type NewTodoLink } from './todo-new-dialog.component';

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
    // Only boards that take cards, people with a fallback name.
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
    expect(cmp.icon('ticket')).toBe('ticket');
    // The button opens and closes the picker.
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

  it('cancels', async () => {
    const { cmp, open } = await setup();
    open();
    fireEvent.click(screen.getAllByRole('button', { name: 'Abbrechen' }).at(-1)!);
    expect(cmp.open()).toBe(false);
  });
});
