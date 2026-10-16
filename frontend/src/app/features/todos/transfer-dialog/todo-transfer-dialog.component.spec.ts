import { fireEvent, render, screen } from '@testing-library/angular';
import { Subject, of, throwError, type Observable } from 'rxjs';
import { TodosApiService, type TodoBoard, type TodoBoardSummary } from '@core/api/todos.service';
import { BOARDS, board } from '../../../../testing/todo-fixtures';
import { TodoTransferDialogComponent } from './todo-transfer-dialog.component';

interface Opts {
  boards?: TodoBoardSummary[];
  boardsFail?: boolean;
  board?: (id: string) => Observable<TodoBoard>;
  inputs?: Record<string, unknown>;
}

async function setup(opts: Opts = {}) {
  const api = {
    boards: jest.fn(() => (opts.boardsFail ? throwError(() => new Error('x')) : of(opts.boards ?? BOARDS))),
    board: jest.fn(opts.board ?? ((id: string) => of(board({ id, name: `Board ${id}` })))),
  };
  const transferred = jest.fn();
  const view = await render(TodoTransferDialogComponent, {
    // A card of a personal board: every other writable board is a target.
    inputs: { open: false, boardId: 'b-1', boardKind: 'personal', ...opts.inputs },
    on: { transferred },
    providers: [{ provide: TodosApiService, useValue: api }],
  });
  const cmp = view.fixture.componentInstance;
  const open = () => {
    cmp.open.set(true);
    view.fixture.detectChanges();
  };
  return { ...view, api, transferred, cmp, open };
}

describe('TodoTransferDialogComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('offers the other writable boards and starts on the first one and its first column', async () => {
    const { cmp, open, api, transferred } = await setup({
      boards: [BOARDS[0], BOARDS[1], { ...BOARDS[2], canWrite: false }, BOARDS[3]],
    });
    expect(api.boards).not.toHaveBeenCalled();
    open();
    expect(screen.getByRole('dialog', { name: 'In anderes Board verschieben' })).toBeInTheDocument();
    // No helper text and no sub line with the card title.
    expect(screen.queryByText(/Labels, die es im Ziel-Board nicht gibt/)).toBeNull();
    expect(screen.queryByText('Raum buchen')).toBeNull();
    expect(cmp.boardOptions().map((o) => o.value)).toEqual(['b-0', 'b-3']);
    expect(cmp.selectedBoard()).toBe('b-0');
    expect(cmp.column()).toBe('c-1');
    expect(cmp.columnOptions().map((o) => o.label)).toEqual(['Offen', 'In Arbeit', 'Wartet', 'Erledigt']);
    cmp.setBoard('b-3');
    cmp.column.set('c-4');
    fireEvent.click(screen.getByRole('button', { name: 'Verschieben' }));
    expect(transferred).toHaveBeenCalledWith({ boardId: 'b-3', columnId: 'c-4', boardName: 'Board b-3' });
  });

  it('leaves the personal board out for a card of a shared board', async () => {
    const { cmp, open } = await setup({ inputs: { boardKind: 'gremium' } });
    open();
    expect(cmp.boardOptions().map((o) => o.value)).toEqual(['b-2', 'b-3']);
    expect(cmp.selectedBoard()).toBe('b-2');
  });

  it('shows the transfer error when the chosen board does not load', async () => {
    const { cmp, open, fixture } = await setup({
      board: (id) => (id === 'b-3' ? throwError(() => new Error('x')) : of(board({ id }))),
    });
    open();
    expect(cmp.failed()).toBe(false);
    cmp.setBoard('b-3');
    fixture.detectChanges();
    expect(cmp.failed()).toBe(true);
    expect(screen.getByRole('alert')).toHaveTextContent('Die Karte konnte nicht verschoben werden.');
    cmp.setBoard('b-0');
    fixture.detectChanges();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('drops the board list of an earlier open', async () => {
    const lists: Subject<TodoBoardSummary[]>[] = [];
    const { cmp, open, api, fixture } = await setup();
    api.boards.mockImplementation(() => {
      const s = new Subject<TodoBoardSummary[]>();
      lists.push(s);
      return s;
    });
    open();
    cmp.open.set(false);
    fixture.detectChanges();
    open();
    expect(lists).toHaveLength(2);
    lists[0].next([BOARDS[3]]);
    lists[0].error(new Error('late'));
    expect(cmp.loaded()).toBe(false);
    expect(cmp.boards()).toEqual([]);
    lists[1].next(BOARDS);
    expect(cmp.loaded()).toBe(true);
    expect(cmp.boardOptions().map((o) => o.value)).toEqual(['b-0', 'b-2', 'b-3']);
  });

  it('says so when there is no other board and offers only the cancel button', async () => {
    const { open, cmp } = await setup({ boards: [BOARDS[1], { ...BOARDS[2], canWrite: false }] });
    open();
    expect(screen.getByText('Es gibt kein anderes Board, in das du verschieben kannst.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Verschieben' })).toBeNull();
    fireEvent.click(screen.getAllByRole('button', { name: 'Abbrechen' }).at(-1)!);
    expect(cmp.open()).toBe(false);
  });

  it('shows the transfer error, not the empty line, when the boards do not load', async () => {
    const { open, cmp } = await setup({ boardsFail: true });
    open();
    expect(cmp.none()).toBe(false);
    expect(cmp.unloadable()).toBe(true);
    expect(screen.getByRole('alert')).toHaveTextContent('Die Karte konnte nicht verschoben werden.');
    expect(screen.queryByText('Es gibt kein anderes Board, in das du verschieben kannst.')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Verschieben' })).toBeNull();
  });

  it('waits for the board and its column, drops a stale answer and a failed read', async () => {
    const answers = new Map<string, Subject<TodoBoard>>();
    const { open, cmp, transferred, fixture } = await setup({
      board: (id) => {
        const s = new Subject<TodoBoard>();
        answers.set(id, s);
        return s;
      },
    });
    open();
    expect(cmp.canConfirm()).toBe(false);
    cmp.setBoard('b-3');
    answers.get('b-0')!.next(board({ id: 'b-0' }));
    answers.get('b-0')!.error(new Error('late'));
    expect(cmp.board()).toBeNull();
    answers.get('b-3')!.next(board({ id: 'b-3', columns: [] }));
    expect(cmp.column()).toBe('');
    expect(cmp.canConfirm()).toBe(false);
    cmp.confirm();
    expect(transferred).not.toHaveBeenCalled();
    cmp.setBoard('b-2');
    answers.get('b-2')!.error(new Error('x'));
    expect(cmp.board()).toBeNull();
    cmp.setBoard('b-0');
    answers.get('b-0')!.next(board({ id: 'b-0' }));
    expect(cmp.canConfirm()).toBe(true);
    fixture.componentRef.setInput('busy', true);
    fixture.detectChanges();
    expect(cmp.canConfirm()).toBe(false);
  });
});
