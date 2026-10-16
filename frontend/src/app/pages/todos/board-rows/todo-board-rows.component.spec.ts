import { ScrollDispatcher } from '@angular/cdk/scrolling';
import { CdkDrag, CdkDropList, type CdkDragDrop } from '@angular/cdk/drag-drop';
import { By } from '@angular/platform-browser';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { fireEvent, render, screen, within } from '@testing-library/angular';
import { Subject, of, throwError, type Observable } from 'rxjs';
import {
  TodosApiService,
  type TodoAssignedBoard,
  type TodoAssignedPoll,
  type TodoCardDetail,
  type TodoCardTile,
} from '@core/api/todos.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { NO_FILTER } from '../../../features/todos/todos.util';
import { TODAY, board, detail, tile } from '../../../../testing/todo-fixtures';
import { DONE_PREVIEW } from '../board-view/todo-board-view.component';
import { COLLAPSED_KEY, TodoBoardRowsComponent, boardRows, rowDropId } from './todo-board-rows.component';

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
  transfer?: () => Observable<TodoCardDetail>;
  phone?: boolean;
  inputs?: Record<string, unknown>;
}

async function setup(opts: Opts = {}) {
  TestBed.resetTestingModule();
  const boards = opts.boards ?? [row(), team()];
  const api = {
    pollMineBoards: jest.fn(opts.poll ?? ((): Observable<TodoAssignedPoll> => of({ boards, etag: 'W/"r"' }))),
    pollAllBoards: jest.fn((): Observable<TodoAssignedPoll> => of({ boards, etag: 'W/"a"' })),
    moveCard: jest.fn(opts.move ?? (() => of(tile({ id: 'k-1', columnId: 'c-2', title: 'Raum buchen', assignees: [ME] })))),
    transferCard: jest.fn(
      opts.transfer ??
        (() => of(detail({ id: 'k-1', boardId: 'b-9', columnId: 't-1', rank: '0', title: 'Raum buchen', assignees: [ME] }))),
    ),
  };
  const toast = { success: jest.fn(), error: jest.fn() };
  const on = { openCard: jest.fn(), matches: jest.fn(), dropIn: jest.fn(), transferred: jest.fn() };
  const view = await render(TodoBoardRowsComponent, {
    inputs: { filter: NO_FILTER, today: TODAY, phone: opts.phone ?? false, ...opts.inputs },
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

/**
 * Space on a tile as Firefox does it: the keydown on the focused button, then the keyup,
 * and the keyup clicks the button unless a handler prevented it.
 */
function firefoxSpace(title: string): void {
  const button = screen.getByRole('button', { name: title });
  fireEvent.keyDown(button, { key: ' ' });
  const target = screen.getByRole('button', { name: title });
  const up = new KeyboardEvent('keyup', { key: ' ', bubbles: true, cancelable: true });
  target.dispatchEvent(up);
  if (!up.defaultPrevented) target.click();
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

describe('boardRows of "Alle"', () => {
  const other = { principalId: 'p-7', displayName: 'Olaf' };
  const all = (cards: TodoCardTile[]) => row({ cards });

  it('keeps every board as a row while no filter is on and some board has a card', () => {
    const empty = team({ cards: [] });
    expect(boardRows([all([tile({ id: 'k-1' })]), empty], NO_FILTER, TODAY, { all: true }).map((r) => r.count)).toEqual([1, 0]);
    expect(boardRows([all([]), empty], NO_FILTER, TODAY, { all: true })).toEqual([]);
    const filtered = boardRows([all([tile({ id: 'k-1', title: 'A' })]), empty], { ...NO_FILTER, q: 'a' }, TODAY, { all: true });
    expect(filtered.map((r) => r.board.id)).toEqual(['b-1']);
  });

  it('filters "Ich" by the assignee', () => {
    const cards = [tile({ id: 'k-1', assignees: [ME] }), tile({ id: 'k-2', assignees: [other] }), tile({ id: 'k-3' })];
    const mine = { ...NO_FILTER, assignee: 'me' };
    expect(boardRows([all(cards)], mine, TODAY, { all: true, me: 'me' })[0].count).toBe(1);
    expect(boardRows([all(cards)], mine, TODAY, { all: true, me: null })).toEqual([]);
    expect(boardRows([all(cards)], mine, TODAY)[0].count).toBe(3);
  });

  it('matches a label filter by the label name on every board', () => {
    const urgent = { id: 'l-1', name: 'Eilig', color: 'red' as const };
    const theirs = { id: 't-l', name: 'eilig', color: 'blue' as const };
    const a = row({ labels: [urgent], cards: [tile({ id: 'k-1', labelIds: ['l-1'] }), tile({ id: 'k-2' })] });
    const b = team({ labels: [theirs], cards: [tile({ id: 'k-9', boardId: 'b-9', columnId: 't-1', labelIds: ['t-l'] })] });
    const c = team({ id: 'b-8', labels: [], cards: [tile({ id: 'k-8', boardId: 'b-8', columnId: 't-1' })] });
    const f = { ...NO_FILTER, labels: ['l-1'] };
    const rows = boardRows([a, b, c], f, TODAY, { all: true, filterLabels: new Map([['l-1', urgent]]) });
    expect(rows.map((r) => [r.board.id, r.count])).toEqual([
      ['b-1', 1],
      ['b-9', 1],
    ]);
    // An id the filter does not know matches nothing; without the map the ids compare.
    expect(boardRows([a], { ...NO_FILTER, labels: ['x'] }, TODAY, { filterLabels: new Map() })).toEqual([]);
    expect(boardRows([a, b], f, TODAY).map((r) => r.board.id)).toEqual(['b-1']);
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

  it('registers the sideways scroller of each row with the CDK, so a drag scrolls it', async () => {
    const { container } = await setup();
    const scrollers = [...TestBed.inject(ScrollDispatcher).scrollContainers.keys()].map(
      (s) => s.getElementRef().nativeElement,
    );
    const rows = [...container.querySelectorAll('.br__cols')];
    expect(rows.length).toBeGreaterThan(0);
    for (const el of rows) expect(scrollers).toContain(el);
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

  it('moves the column counts with a pointer drag, also over another row', async () => {
    const { cmp } = await setup();
    const [r, other] = cmp.rows();
    const [open, doing] = r.columns;
    cmp.kb.set({ boardId: 'b-1', cardId: 'k-1', col: 0, index: 0, fromCol: 0, fromIndex: 0 });
    cmp.onEnter({ container: { data: doing.id } } as never);
    expect(cmp.ptr()).toBeNull();
    cmp.onDragStart(open);
    expect(cmp.kb()).toBeNull();
    expect(cmp.count(r, open)).toBe(2);
    cmp.onEnter({ container: { data: doing.id } } as never);
    expect([cmp.count(r, open), cmp.count(r, doing), cmp.count(r, r.columns[2])]).toEqual([1, 1, 0]);
    expect(cmp.count(other, other.columns[0])).toBe(1);
    // Over a column of another row, that row counts the card.
    cmp.onEnter({ container: { data: other.columns[0].id } } as never);
    expect([cmp.count(r, open), cmp.count(other, other.columns[0])]).toEqual([1, 2]);
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

  it('lifts and puts down a card with Space without opening it, as Firefox clicks on keyup', async () => {
    const { cmp, on, api, settle } = await setup();
    firefoxSpace('Raum buchen');
    await settle();
    expect(cmp.kb()).toMatchObject({ cardId: 'k-1' });
    expect(on.openCard).not.toHaveBeenCalled();
    fireEvent.keyDown(screen.getByRole('button', { name: 'Raum buchen' }), { key: 'ArrowRight' });
    await settle();
    firefoxSpace('Raum buchen');
    await settle();
    expect(cmp.kb()).toBeNull();
    expect(api.moveCard).toHaveBeenCalledWith('k-1', { columnId: 'c-2' });
    expect(on.openCard).not.toHaveBeenCalled();
    // Without a drag, Space still opens the card of a read-only row.
    firefoxSpace('Ticket prüfen');
    expect(on.openCard).toHaveBeenCalledWith('k-9');
  });

  it('lifts a card by touch only after a long press, so a swipe over the rows scrolls', async () => {
    const { fixture } = await setup();
    const drags = fixture.debugElement.queryAll(By.directive(CdkDrag));
    expect(drags.length).toBeGreaterThan(0);
    for (const d of drags) expect(d.injector.get(CdkDrag).dragStartDelay).toEqual({ touch: 400, mouse: 0 });
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
    // A card that went to another board leaves the row of its old board.
    cmp.cardChanged(detail({ id: 'k-1', boardId: 'b-elsewhere' }));
    expect(cmp.boards()[0].cards.some((c) => c.id === 'k-1')).toBe(false);
    expect(api.pollMineBoards).toHaveBeenLastCalledWith(null);
    cmp.cardRemoved('k-9');
    expect(cmp.boards()[1].cards).toEqual([]);
    cmp.cardRemoved('nope');
    expect(api.pollMineBoards).toHaveBeenLastCalledWith(null);
  });

  it('moves a card from the row of its old board into the row of its new one', async () => {
    const { cmp, api } = await setup();
    api.pollMineBoards.mockImplementation(() => new Subject<TodoAssignedPoll>());
    cmp.cardChanged(detail({ id: 'k-1', boardId: 'b-9', columnId: 't-1', assignees: [ME] }));
    expect(cmp.boards()[0].cards.some((c) => c.id === 'k-1')).toBe(false);
    expect(cmp.boards()[1].cards.map((c) => c.id)).toContain('k-1');
  });
  it('reads every board for "Alle" and filters "Ich" by my id', async () => {
    const mixed = row({ cards: [tile({ id: 'k-1', title: 'Meins', assignees: [ME] }), tile({ id: 'k-2', title: 'Fremd' })] });
    const { api, cmp, fixture, settle } = await setup({ boards: [mixed], inputs: { source: 'all', me: 'me' } });
    expect(api.pollAllBoards).toHaveBeenCalledWith(null);
    expect(api.pollMineBoards).not.toHaveBeenCalled();
    expect(cmp.rows()[0].count).toBe(2);
    expect(cmp.openCount()).toBe(2);
    fixture.componentRef.setInput('filter', { ...NO_FILTER, assignee: 'me' });
    await settle();
    expect(cmp.rows()[0].count).toBe(1);
    cmp.poll();
    expect(api.pollAllBoards).toHaveBeenLastCalledWith('W/"a"');
  });

  it('connects the columns of every writable open row and the personal board', async () => {
    const { cmp, fixture, settle } = await setup({ inputs: { extraDrops: ['bv-list-p-1'] } });
    const own = row().columns.map((c) => rowDropId(c.id));
    expect(cmp.dropIds()).toEqual(own);
    expect(cmp.connected()).toEqual([...own, 'bv-list-p-1']);
    const lists = fixture.debugElement.queryAll(By.directive(CdkDropList)).map((d) => d.injector.get(CdkDropList));
    const byId = new Map(lists.map((l) => [l.id, l]));
    expect(byId.get(rowDropId('c-1'))?.connectedTo).toEqual([...own, 'bv-list-p-1']);
    // The read-only row is neither source nor target.
    expect(byId.get(rowDropId('t-1'))?.connectedTo).toEqual([]);
    fireEvent.click(screen.getByRole('button', { name: /Studierendenparlament/ }));
    await settle();
    expect(cmp.dropIds()).toEqual([]);
    fixture.componentRef.setInput('phone', true);
    expect(cmp.dropIds()).toEqual([]);
  });

  it('transfers a card dropped on another row at once and takes the answer', async () => {
    const answer = new Subject<TodoCardDetail>();
    const third = team({ id: 'b-8', name: 'Dritte', columns: [{ id: 'z-1', name: 'Neu', position: 0, isDone: false, cardCount: 1 }], cards: [tile({ id: 'k-8', boardId: 'b-8', columnId: 'z-1', assignees: [ME] })] });
    const { cmp, api, on } = await setup({ boards: [row(), team({ canWrite: true }), third], transfer: () => answer });
    const [, other] = cmp.rows();
    cmp.drop(other, dropEvent('k-1', 'c-1', 't-1', 0, 0));
    expect(api.transferCard).toHaveBeenCalledWith('k-1', { boardId: 'b-9', columnId: 't-1', beforeId: 'k-9' });
    expect(cmp.boards()[0].cards.some((c) => c.id === 'k-1')).toBe(false);
    expect(cmp.boards()[1].cards.map((c) => c.id)).toEqual(['k-1', 'k-9']);
    expect(cmp.boards()[1].cards[0].boardId).toBe('b-9');
    answer.next(detail({ id: 'k-1', boardId: 'b-9', columnId: 't-1', title: 'Raum buchen', labelIds: [] }));
    expect(cmp.boards()[1].cards[0].title).toBe('Raum buchen');
    expect(on.transferred).toHaveBeenCalledWith(expect.objectContaining({ id: 'k-1', boardId: 'b-9' }));
    expect(api.moveCard).not.toHaveBeenCalled();
    expect(cmp.boards()[2]).toBe(third);
  });

  it('reports no count before the first read answers', async () => {
    const { on } = await setup({ poll: () => new Subject<TodoAssignedPoll>() });
    expect(on.matches).not.toHaveBeenCalled();
  });

  it('puts a refused transfer back with a toast and reads the rows again', async () => {
    const { cmp, api, toast } = await setup({
      boards: [row(), team({ canWrite: true })],
      transfer: () => throwError(() => new Error('x')),
    });
    const before = cmp.boards();
    const [, other] = cmp.rows();
    api.pollMineBoards.mockImplementation(() => new Subject<TodoAssignedPoll>());
    cmp.drop(other, dropEvent('k-2', 'c-1', 't-1', 1, 1));
    expect(api.transferCard).toHaveBeenCalledWith('k-2', { boardId: 'b-9', columnId: 't-1', afterId: 'k-9' });
    expect(toast.error).toHaveBeenCalledWith('Die Karte konnte nicht verschoben werden.');
    expect(cmp.boards()).toBe(before);
    expect(api.pollMineBoards).toHaveBeenLastCalledWith(null);
  });

  it('keeps a newer change when a transfer is refused late', async () => {
    const answer = new Subject<TodoCardDetail>();
    const { cmp, api } = await setup({ boards: [row(), team({ canWrite: true })], transfer: () => answer });
    api.pollMineBoards.mockImplementation(() => new Subject<TodoAssignedPoll>());
    cmp.drop(cmp.rows()[1], dropEvent('k-1', 'c-1', 't-1', 0, 0));
    cmp.commentsChanged({ id: 'k-9', commentCount: 3 });
    const changed = cmp.boards();
    answer.error(new Error('x'));
    expect(cmp.boards()).toBe(changed);
  });

  it('drops nothing on a read-only row and hands a card of the personal board to the page', async () => {
    const { cmp, api, on } = await setup();
    const [r, readOnly] = cmp.rows();
    cmp.drop(readOnly, dropEvent('k-1', 'c-1', 't-1', 0, 0));
    expect(api.transferCard).not.toHaveBeenCalled();
    cmp.drop(r, dropEvent('p-card', 'p-col', 'c-1', 0, 1));
    expect(on.dropIn).toHaveBeenCalledWith({ boardId: 'b-1', cardId: 'p-card', move: { columnId: 'c-1', afterId: 'k-1' } });
  });

  it('takes, receives and accepts a card that the page moves', async () => {
    const { cmp } = await setup();
    expect(cmp.take('nope')).toBeNull();
    const taken = cmp.take('k-9');
    expect(taken?.id).toBe('k-9');
    expect(cmp.boards()[1].cards).toEqual([]);
    const visitor = tile({ id: 'p-1', boardId: 'b-0', columnId: 'p-c', title: 'Privat' });
    cmp.receive(visitor, 'b-1', { columnId: 'c-2' });
    expect(cmp.boards()[0].cards.find((c) => c.id === 'p-1')).toMatchObject({ boardId: 'b-1', columnId: 'c-2' });
    cmp.accept(tile({ id: 'p-1', boardId: 'b-1', columnId: 'c-2', title: 'Privat (neu)' }));
    expect(cmp.boards()[0].cards.find((c) => c.id === 'p-1')?.title).toBe('Privat (neu)');
  });
});
