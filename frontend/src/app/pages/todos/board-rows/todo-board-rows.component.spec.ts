import type { CdkDragDrop } from '@angular/cdk/drag-drop';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { fireEvent, render, screen, within } from '@testing-library/angular';
import { Subject, of, throwError, type Observable } from 'rxjs';
import { TodosApiService, type TodoAssignedBoard, type TodoAssignedPoll, type TodoCardTile } from '@core/api/todos.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { NO_FILTER } from '../../../features/todos/todos.util';
import { TODAY, board, detail, tile } from '../../../../testing/todo-fixtures';
import { DONE_PREVIEW } from '../board-view/todo-board-view.component';
import { COLLAPSED_KEY, TodoBoardRowsComponent, boardRows } from './todo-board-rows.component';

const ME = { principalId: 'me', displayName: 'Mara Keller' };

function row(over: Partial<TodoAssignedBoard> = {}): TodoAssignedBoard {
  const b = board({
    cards: [
      tile({ id: 'k-1', columnId: 'c-1', title: 'Raum buchen', assignees: [ME] }),
      tile({ id: 'k-2', columnId: 'c-1', title: 'Haushalt Kapitel 3', labelIds: ['l-1'], assignees: [ME], dueDate: '2026-10-01' }),
      tile({ id: 'k-3', columnId: 'c-4', title: 'Bus anfragen', assignees: [ME] }),
    ],
  });
  const { id, name, kind, gremiumId, canWrite, columns, labels, cards } = b;
  return { id, name, kind, gremiumId, canWrite, columns, labels, cards, ...over };
}

function team(over: Partial<TodoAssignedBoard> = {}): TodoAssignedBoard {
  return {
    id: 'b-9',
    name: 'Plattform',
    kind: 'team',
    gremiumId: null,
    canWrite: false,
    columns: [
      { id: 't-1', name: 'Neu', position: 0, isDone: false, cardCount: 1 },
      { id: 't-2', name: 'Fertig', position: 1, isDone: true, cardCount: 0 },
    ],
    labels: [],
    cards: [tile({ id: 'k-9', boardId: 'b-9', columnId: 't-1', title: 'Ticket prüfen', assignees: [ME] })],
    ...over,
  };
}

interface Opts {
  boards?: TodoAssignedBoard[];
  poll?: () => Observable<TodoAssignedPoll>;
  move?: () => Observable<TodoCardTile>;
  phone?: boolean;
}

async function setup(opts: Opts = {}) {
  TestBed.resetTestingModule();
  const boards = opts.boards ?? [row(), team()];
  const api = {
    pollMineBoards: jest.fn(opts.poll ?? ((): Observable<TodoAssignedPoll> => of({ boards, etag: 'W/"r"' }))),
    moveCard: jest.fn(opts.move ?? (() => of(tile({ id: 'k-1', columnId: 'c-2', title: 'Raum buchen', assignees: [ME] })))),
  };
  const toast = { success: jest.fn(), error: jest.fn() };
  const on = { openCard: jest.fn(), matches: jest.fn() };
  const view = await render(TodoBoardRowsComponent, {
    inputs: { filter: NO_FILTER, today: TODAY, phone: opts.phone ?? false },
    on,
    providers: [
      provideRouter([]),
      { provide: TodosApiService, useValue: api },
      { provide: ToastService, useValue: toast },
    ],
  });
  const cmp = view.fixture.componentInstance;
  const settle = async () => {
    view.fixture.detectChanges();
    await view.fixture.whenStable();
  };
  await settle();
  const item = (title: string) => screen.getByRole('button', { name: title }).closest('.br__item') as HTMLElement;
  const key = async (title: string, k: string) => {
    fireEvent.keyDown(item(title), { key: k });
    await settle();
  };
  return { ...view, api, toast, on, cmp, settle, item, key };
}

function dropEvent(cardId: string, from: string, to: string, previousIndex: number, currentIndex: number) {
  return {
    item: { data: cardId },
    container: { data: to },
    previousContainer: { data: from },
    previousIndex,
    currentIndex,
  } as unknown as CdkDragDrop<string>;
}

describe('boardRows', () => {
  it('drops a row without a card that passes the filters and keeps the column order', () => {
    const shuffled = row({ columns: [...row().columns].reverse() });
    const all = boardRows([shuffled, team()], NO_FILTER, TODAY);
    expect(all.map((r) => r.count)).toEqual([3, 1]);
    expect(all[0].columns.map((c) => c.name)).toEqual(['Offen', 'In Arbeit', 'Wartet', 'Erledigt']);
    expect(boardRows([row()], { ...NO_FILTER, assignee: 'me' }, TODAY)[0].count).toBe(3);
    expect(boardRows([row()], { ...NO_FILTER, assignee: 'none' }, TODAY)).toEqual([]);
    expect(boardRows([row()], { ...NO_FILTER, due: 'overdue' }, TODAY)[0].count).toBe(1);
    expect(boardRows([row(), team()], { ...NO_FILTER, q: 'haushalt' }, TODAY).map((r) => r.board.id)).toEqual(['b-1']);
    const stray = row({ cards: [tile({ id: 'x', columnId: 'gone', assignees: [ME] })] });
    expect(boardRows([stray], NO_FILTER, TODAY)).toEqual([]);
  });
});

describe('TodoBoardRowsComponent', () => {
  beforeEach(() => {
    localStorage.setItem('ap.locale', 'de');
    localStorage.removeItem(COLLAPSED_KEY);
  });
  afterEach(() => jest.restoreAllMocks());

  it('shows one region per board with its heading, count, columns and my cards', async () => {
    const { on, api } = await setup();
    expect(api.pollMineBoards).toHaveBeenCalledWith(null);
    const region = screen.getByRole('region', { name: /Studierendenparlament/ });
    expect(within(region).getByRole('heading', { level: 2 })).toHaveTextContent('3');
    expect(within(region).getByRole('list', { name: 'Studierendenparlament · Offen' }).children).toHaveLength(2);
    expect(within(region).getByRole('list', { name: 'Studierendenparlament · In Arbeit' }).children).toHaveLength(0);
    expect(within(region).getByRole('link', { name: 'Board „Studierendenparlament“ öffnen' })).toHaveAttribute('href', '/todos/b-1');
    const readOnly = screen.getByRole('region', { name: /Plattform/ });
    expect(within(readOnly).getByText('Nur lesen')).toBeInTheDocument();
    expect(on.matches).toHaveBeenLastCalledWith(4);
    fireEvent.click(screen.getByRole('button', { name: 'Ticket prüfen' }));
    expect(on.openCard).toHaveBeenCalledWith('k-9');
  });

  it('shows nothing when no other board holds my cards, and keeps the rows on a failed read', async () => {
    const empty = await setup({ boards: [] });
    expect(screen.queryByRole('region')).toBeNull();
    expect(empty.on.matches).toHaveBeenLastCalledWith(0);
    empty.fixture.destroy();
    const failing = await setup({ poll: () => throwError(() => new Error('x')) });
    expect(failing.cmp.boards()).toEqual([]);
  });

  it('collapses a row and remembers it per browser', async () => {
    const { settle } = await setup();
    const toggle = screen.getByRole('button', { name: /Studierendenparlament/ });
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(toggle).toHaveAttribute('aria-controls', 'br-c-b-1');
    fireEvent.click(toggle);
    await settle();
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(toggle).not.toHaveAttribute('aria-controls');
    expect(screen.queryByRole('button', { name: 'Raum buchen' })).toBeNull();
    expect(JSON.parse(localStorage.getItem(COLLAPSED_KEY) ?? '[]')).toEqual(['b-1']);
    fireEvent.click(toggle);
    await settle();
    expect(screen.getByRole('button', { name: 'Raum buchen' })).toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem(COLLAPSED_KEY) ?? '[]')).toEqual([]);
  });

  it('reads the collapsed rows back and survives a broken or blocked storage', async () => {
    localStorage.setItem(COLLAPSED_KEY, JSON.stringify(['b-9', 7]));
    const first = await setup();
    expect(first.cmp.collapsed()).toEqual(new Set(['b-9']));
    first.fixture.destroy();
    localStorage.setItem(COLLAPSED_KEY, '{');
    const broken = await setup();
    expect(broken.cmp.collapsed().size).toBe(0);
    broken.fixture.destroy();
    localStorage.setItem(COLLAPSED_KEY, '{"a":1}');
    const odd = await setup();
    expect(odd.cmp.collapsed().size).toBe(0);
    jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('full');
    });
    fireEvent.click(screen.getByRole('button', { name: /Plattform/ }));
    expect(odd.cmp.collapsed()).toEqual(new Set(['b-9']));
  });

  it('shows the newest done cards and opens the rest', async () => {
    const done = Array.from({ length: DONE_PREVIEW + 1 }, (_, i) =>
      tile({ id: `d-${i}`, columnId: 'c-4', title: `Fertig ${i}`, assignees: [ME] }),
    );
    const { settle, cmp } = await setup({ boards: [row({ cards: done })] });
    const list = () => screen.getByRole('list', { name: 'Studierendenparlament · Erledigt' });
    expect(list().children).toHaveLength(DONE_PREVIEW);
    fireEvent.click(screen.getByRole('button', { name: '1 weitere' }));
    await settle();
    expect(list().children).toHaveLength(DONE_PREVIEW + 1);
    const r = cmp.rows()[0];
    expect(cmp.more(r, r.columns[3])).toBe(0);
  });

  it('moves a card by pointer inside its row through the move route', async () => {
    const { cmp, api, settle } = await setup();
    const r = cmp.rows()[0];
    cmp.drop(r, dropEvent('k-1', 'c-1', 'c-1', 0, 0));
    expect(api.moveCard).not.toHaveBeenCalled();
    cmp.drop(r, dropEvent('k-1', 'c-1', 'c-2', 0, 0));
    expect(api.moveCard).toHaveBeenCalledWith('k-1', { columnId: 'c-2' });
    await settle();
    expect(cmp.boards()[0].cards.find((c) => c.id === 'k-1')?.columnId).toBe('c-2');
    cmp.drop(r, dropEvent('k-2', 'c-1', 'c-9', 0, 0));
    cmp.drop(r, dropEvent('k-77', 'c-1', 'c-2', 0, 0));
    expect(api.moveCard).toHaveBeenCalledTimes(1);
  });

  it('moves the column counts with a pointer drag inside its row only', async () => {
    const { cmp } = await setup();
    const [r, other] = cmp.rows();
    const [open, doing] = r.columns;
    cmp.kb.set({ boardId: 'b-1', cardId: 'k-1', col: 0, index: 0, fromCol: 0, fromIndex: 0 });
    cmp.onEnter({ container: { data: doing.id } } as never);
    expect(cmp.ptr()).toBeNull();
    cmp.onDragStart(r, open);
    expect(cmp.kb()).toBeNull();
    expect(cmp.count(r, open)).toBe(2);
    cmp.onEnter({ container: { data: doing.id } } as never);
    expect([cmp.count(r, open), cmp.count(r, doing), cmp.count(r, r.columns[2])]).toEqual([1, 1, 0]);
    expect(cmp.count(other, other.columns[0])).toBe(1);
    cmp.ptr.set(null);
    expect(cmp.count(r, open)).toBe(2);
  });

  it('hides "n weitere" of the done column while a card of the row is held', async () => {
    const done = Array.from({ length: DONE_PREVIEW + 1 }, (_, i) =>
      tile({ id: `d-${i}`, columnId: 'c-4', title: `Fertig ${i}`, assignees: [ME] }),
    );
    const { cmp } = await setup({ boards: [row({ cards: [tile({ id: 'k-1', columnId: 'c-1', title: 'A', assignees: [ME] }), ...done] })] });
    const r = cmp.rows()[0];
    expect(cmp.more(r, r.columns[3])).toBe(1);
    expect(cmp.more(r, r.columns[0])).toBe(0);
    cmp.kb.set({ boardId: 'b-1', cardId: 'k-1', col: 1, index: 0, fromCol: 0, fromIndex: 0 });
    expect(cmp.more(r, r.columns[0])).toBe(0);
    expect(cmp.more(r, r.columns[3])).toBe(0);
  });

  it('rolls a refused move back, says so and reads the rows again', async () => {
    const { cmp, api, toast } = await setup({ move: () => throwError(() => new Error('409')) });
    const before = cmp.boards()[0];
    cmp.drop(cmp.rows()[0], dropEvent('k-2', 'c-1', 'c-1', 1, 0));
    expect(api.moveCard).toHaveBeenCalledWith('k-2', { columnId: 'c-1', beforeId: 'k-1' });
    expect(toast.error).toHaveBeenCalledWith('Die Karte konnte nicht verschoben werden.');
    expect(cmp.boards()[0]).toEqual(before);
    expect(api.pollMineBoards).toHaveBeenLastCalledWith(null);
  });

  it('keeps a newer row when a refused move answers late', async () => {
    const answer = new Subject<TodoCardTile>();
    const { cmp, api } = await setup({ move: () => answer });
    api.pollMineBoards.mockImplementation(() => new Subject<TodoAssignedPoll>());
    cmp.drop(cmp.rows()[0], dropEvent('k-2', 'c-1', 'c-1', 1, 0));
    cmp.commentsChanged({ id: 'k-1', commentCount: 4 });
    const newer = cmp.boards()[0];
    answer.error(new Error('x'));
    expect(cmp.boards()[0]).toBe(newer);
  });

  it('does not move a card of a read-only row or on a phone', async () => {
    const { cmp, api, key } = await setup();
    const ro = cmp.rows()[1];
    expect(cmp.canDrag(ro)).toBe(false);
    cmp.drop(ro, dropEvent('k-9', 't-1', 't-2', 0, 0));
    await key('Ticket prüfen', ' ');
    expect(cmp.kb()).toBeNull();
    expect(api.moveCard).not.toHaveBeenCalled();
    const phone = await setup({ phone: true });
    expect(phone.cmp.canDrag(phone.cmp.rows()[0])).toBe(false);
  });

  it('moves a card with the keyboard inside its row and names each step', async () => {
    const { cmp, api, key, item } = await setup();
    await key('Raum buchen', 'x');
    expect(cmp.kb()).toBeNull();
    await key('Raum buchen', ' ');
    expect(cmp.kb()).toMatchObject({ boardId: 'b-1', cardId: 'k-1', col: 0, index: 0 });
    expect(cmp.announce()).toContain('aufgenommen');
    await key('Raum buchen', 'ArrowDown');
    expect(cmp.kb()?.index).toBe(1);
    await key('Raum buchen', 'ArrowUp');
    await key('Raum buchen', 'ArrowUp');
    expect(cmp.kb()?.index).toBe(0);
    await key('Raum buchen', 'ArrowLeft');
    expect(cmp.kb()?.col).toBe(0);
    await key('Raum buchen', 'ArrowRight');
    await key('Raum buchen', 'ArrowLeft');
    expect(cmp.kb()?.col).toBe(0);
    await key('Raum buchen', 'ArrowRight');
    expect(cmp.kb()?.col).toBe(1);
    const r = cmp.rows()[0];
    expect(cmp.count(r, r.columns[0])).toBe(1);
    expect(cmp.count(r, r.columns[1])).toBe(1);
    expect(cmp.count(r, r.columns[2])).toBe(0);
    expect(cmp.count(cmp.rows()[1], cmp.rows()[1].columns[0])).toBe(1);
    await key('Raum buchen', 'a');
    fireEvent.keyDown(item('Haushalt Kapitel 3'), { key: 'ArrowDown' });
    await key('Raum buchen', 'Enter');
    expect(api.moveCard).toHaveBeenCalledWith('k-1', { columnId: 'c-2' });
    expect(cmp.announce()).toBe('„Raum buchen“ abgelegt in In Arbeit.');
  });

  it('puts a lifted card back with Escape, Tab, the same place or a click elsewhere', async () => {
    const { cmp, api, key, settle } = await setup();
    await key('Raum buchen', ' ');
    await key('Raum buchen', 'Escape');
    expect(cmp.kb()).toBeNull();
    expect(cmp.announce()).toContain('abgebrochen');
    await key('Raum buchen', ' ');
    await key('Raum buchen', 'Tab');
    expect(cmp.kb()).toBeNull();
    await key('Raum buchen', ' ');
    await key('Raum buchen', ' ');
    expect(api.moveCard).not.toHaveBeenCalled();
    await key('Raum buchen', ' ');
    fireEvent.pointerDown(screen.getByRole('button', { name: 'Raum buchen' }));
    expect(cmp.kb()).not.toBeNull();
    fireEvent.pointerDown(document.body);
    await settle();
    expect(cmp.kb()).toBeNull();
    cmp.leaveDrag(new Event('focusin'));
    await key('Raum buchen', ' ');
    fireEvent.click(screen.getByRole('button', { name: /Studierendenparlament/ }));
    expect(cmp.kb()).toBeNull();
    await key('Ticket prüfen', 'ArrowDown');
  });

  it('shows a row as it is when the held card or the column is not in it', async () => {
    const { cmp } = await setup();
    const r = cmp.rows()[0];
    cmp.kb.set({ boardId: 'b-1', cardId: 'k-0', col: 1, index: 0, fromCol: 1, fromIndex: 0 });
    expect(cmp.list(r, r.columns[0]).map((c) => c.id)).toEqual(['k-1', 'k-2']);
    expect(cmp.list(r, { id: 'c-x', name: 'X', position: 9, isDone: false, cardCount: 0 })).toEqual([]);
    expect(cmp.more(r, { id: 'c-x', name: 'X', position: 9, isDone: true, cardCount: 0 })).toBe(0);
    expect(cmp.count(r, { id: 'c-x', name: 'X', position: 9, isDone: true, cardCount: 0 })).toBe(0);
  });

  it('ends a keyboard drag on a row that left the rows without a word', async () => {
    const { cmp } = await setup();
    cmp.kb.set({ boardId: 'gone', cardId: 'k-0', col: 0, index: 0, fromCol: 0, fromIndex: 0 });
    cmp.announce.set('');
    cmp.leaveDrag(new Event('pointerdown'));
    expect(cmp.kb()).toBeNull();
    expect(cmp.announce()).toBe('');
  });

  it('polls with the ETag, keeps the rows on a 304 and drops a poll that a change overtook', async () => {
    const answers = new Subject<TodoAssignedPoll>();
    const { cmp, api } = await setup();
    api.pollMineBoards.mockImplementation(() => answers);
    cmp.poll();
    expect(api.pollMineBoards).toHaveBeenLastCalledWith('W/"r"');
    answers.next({ boards: null, etag: 'W/"r"' });
    expect(cmp.boards()).toHaveLength(2);
    cmp.poll();
    cmp.commentsChanged({ id: 'k-1', commentCount: 2 });
    answers.next({ boards: [], etag: 'W/"s"' });
    expect(cmp.boards()).toHaveLength(2);
  });

  it('follows the changes of the card drawer', async () => {
    const { cmp, api } = await setup();
    cmp.commentsChanged({ id: 'k-1', commentCount: 5 });
    expect(cmp.boards()[0].cards[0].commentCount).toBe(5);
    cmp.commentsChanged({ id: 'nope', commentCount: 1 });
    const calls = api.pollMineBoards.mock.calls.length;
    cmp.cardChanged(detail({ id: 'x', boardId: 'b-0' }));
    expect(api.pollMineBoards.mock.calls.length).toBe(calls);
    api.pollMineBoards.mockImplementation(() => new Subject<TodoAssignedPoll>());
    cmp.cardChanged(detail({ id: 'k-1', boardId: 'b-1', columnId: 'c-3', title: 'Raum buchen', assignees: [ME] }));
    expect(cmp.boards()[0].cards.find((c) => c.id === 'k-1')?.columnId).toBe('c-3');
    cmp.cardChanged(detail({ id: 'k-2', boardId: 'b-1', archivedAt: '2026-10-16T10:00:00Z' }));
    expect(cmp.boards()[0].cards.some((c) => c.id === 'k-2')).toBe(false);
    cmp.cardRemoved('k-9');
    expect(cmp.boards()[1].cards).toEqual([]);
    cmp.cardRemoved('nope');
    expect(api.pollMineBoards).toHaveBeenLastCalledWith(null);
  });
});
