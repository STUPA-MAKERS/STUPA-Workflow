import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { AuthService } from '@core/auth/auth.service';
import { Subject, map, of, throwError, type Observable } from 'rxjs';
import {
  CARD_BATCH,
  TodosApiService,
  type TodoAssignedPoll,
  type TodoBoardPoll,
  type TodoCardDetail,
} from '@core/api/todos.service';
import { MEMBERS, board, detail, tile } from '../../../testing/todo-fixtures';
import { TodoCacheService } from './todo-cache.service';

function setup(cardsRead: (ids: string[]) => Observable<TodoCardDetail[]> = (ids) => of(ids.map((id) => detail({ id })))) {
  const boards = {
    'b-1': board({ id: 'b-1', cards: [tile({ id: 'k-1' }), tile({ id: 'k-2' })] }),
    'b-2': board({ id: 'b-2', cards: [tile({ id: 'k-3', boardId: 'b-2' })] }),
  } as Record<string, ReturnType<typeof board>>;
  const api = {
    pollBoard: jest.fn((id: string): Observable<TodoBoardPoll> => of({ board: boards[id], etag: `W/"${id}"` })),
    members: jest.fn(() => of(MEMBERS)),
    pollAllBoards: jest.fn((): Observable<TodoAssignedPoll> => of({ boards: [], etag: 'W/"a"' })),
    pollMineBoards: jest.fn((): Observable<TodoAssignedPoll> => of({ boards: [], etag: 'W/"m"' })),
    cards: jest.fn((ids: readonly string[]) => cardsRead([...ids])),
  };
  const userId = signal<string | null>('u-1');
  TestBed.configureTestingModule({
    providers: [
      { provide: TodosApiService, useValue: api },
      { provide: AuthService, useValue: { userId } },
    ],
  });
  return { cache: TestBed.inject(TodoCacheService), api, boards, userId };
}

describe('TodoCacheService', () => {
  /** The page reads the shown board itself. The cards come in one request. */
  it('reads every other board, its people, the rows and the cards ahead once', () => {
    const { cache, api, boards } = setup();
    cache.prefetch(['b-1', 'b-2'], 'b-2');
    cache.prefetch(['b-1', 'b-2'], 'b-2');
    expect(api.pollBoard.mock.calls).toEqual([['b-1', null]]);
    expect(api.members.mock.calls).toEqual([['b-1']]);
    expect(api.pollAllBoards).toHaveBeenCalledWith(null);
    expect(api.pollMineBoards).toHaveBeenCalledWith(null);
    expect(cache.board('b-1')).toEqual({ board: boards['b-1'], etag: 'W/"b-1"' });
    expect(cache.board('b-2')).toBeNull();
    expect(cache.members('b-1')).toEqual(MEMBERS);
    expect(cache.rows('all')).toEqual({ boards: [], etag: 'W/"a"' });
    expect(api.cards.mock.calls).toEqual([[['k-1', 'k-2']]]);
    expect(cache.card('k-1')?.id).toBe('k-1');
  });

  /**
   * The cards of the shown board come first, then the first board, and nothing else yet. A failed
   * read goes on with the next.
   */
  it('waits for the page, then runs two reads at once, the shown board first', () => {
    const reads: Pick<Subject<unknown>, 'next' | 'error' | 'complete'>[] = [];
    const { cache, api } = setup((ids) => {
      const s = new Subject<TodoCardDetail[]>();
      reads.push(s);
      return s.pipe(map(() => ids.map((id) => detail({ id }))));
    });
    api.pollBoard.mockImplementation(() => {
      const s = new Subject<TodoBoardPoll>();
      reads.push(s);
      return s;
    });
    cache.readCards([tile({ id: 'later' })]);
    cache.readCards([tile({ id: 'soon' })], true);
    expect(api.cards).not.toHaveBeenCalled();
    cache.prefetch(['b-1', 'b-2'], null);
    expect(api.cards.mock.calls).toEqual([[['soon']]]);
    expect(api.pollBoard.mock.calls).toEqual([['b-1', null]]);
    expect(api.members).not.toHaveBeenCalled();
    reads[0].next(null);
    reads[0].complete();
    expect(cache.card('soon')?.id).toBe('soon');
    expect(api.members.mock.calls).toEqual([['b-1']]);
    reads[1].error(new Error('x'));
    expect(api.pollBoard.mock.calls).toEqual([
      ['b-1', null],
      ['b-2', null],
    ]);
    expect(cache.board('b-1')).toBeNull();
  });

  /** A read that failed leaves its cards out; a later call reads them again. */
  it('reads at most CARD_BATCH cards per request and never a held card or one in flight', () => {
    const reads: Subject<TodoCardDetail[]>[] = [];
    const { cache, api } = setup(() => {
      const s = new Subject<TodoCardDetail[]>();
      reads.push(s);
      return s;
    });
    cache.putCard(detail({ id: 'held' }));
    cache.prefetch([], null);
    const ids = Array.from({ length: CARD_BATCH + 1 }, (_, i) => `c-${i}`);
    cache.readCards([...ids, 'held'].map((id) => tile({ id })));
    expect(api.cards.mock.calls.map((c) => c[0].length)).toEqual([CARD_BATCH, 1]);
    cache.readCards([tile({ id: 'c-0' }), tile({ id: 'held' })], true);
    expect(api.cards).toHaveBeenCalledTimes(2);
    reads[0].next([detail({ id: 'c-0' }), detail({ id: 'c-1' })]);
    reads[0].complete();
    expect(cache.card('c-1')?.id).toBe('c-1');
    reads[1].error(new Error('x'));
    expect(cache.card(`c-${CARD_BATCH}`)).toBeNull();
    cache.readCards([tile({ id: `c-${CARD_BATCH}` })]);
    expect(api.cards.mock.calls[2][0]).toEqual([`c-${CARD_BATCH}`]);
  });

  it('keeps rows that the page put before their read', () => {
    const { cache, api } = setup();
    cache.putRows('all', [], 'W/"p"');
    cache.prefetch([], null);
    expect(api.pollAllBoards).not.toHaveBeenCalled();
    expect(api.pollMineBoards).toHaveBeenCalled();
    expect(cache.rows('all')?.etag).toBe('W/"p"');
  });

  it('drops a detail that no longer matches its tile', () => {
    const { cache, api } = setup();
    cache.putCard(detail({ id: 'k-1', version: 1 }));
    cache.putCard(detail({ id: 'k-2', version: 1, commentCount: 0 }));
    cache.putBoard(board({ cards: [tile({ id: 'k-1', version: 1 }), tile({ id: 'k-2', version: 1, commentCount: 1 })] }), null);
    expect(cache.card('k-1')).not.toBeNull();
    expect(cache.card('k-2')).toBeNull();
    cache.putRows('mine', [{ ...board(), cards: [tile({ id: 'k-1', version: 2 })] }], 'W/"m"');
    expect(cache.card('k-1')).toBeNull();
    expect(api.cards).not.toHaveBeenCalled();
  });

  it('leaves out a board whose read fails', () => {
    const { cache, api } = setup();
    api.pollBoard.mockReturnValueOnce(throwError(() => new Error('x')));
    api.members.mockReturnValueOnce(throwError(() => new Error('x')));
    cache.prefetch(['b-1'], null);
    expect(cache.board('b-1')).toBeNull();
    expect(cache.members('b-1')).toBeNull();
  });

  /** Nothing more of the closed page is read. */
  it('stops the waiting reads when the page closes and starts them again on the next visit', () => {
    const reads: Subject<TodoBoardPoll>[] = [];
    const { cache, api } = setup();
    api.pollBoard.mockImplementation(() => {
      const s = new Subject<TodoBoardPoll>();
      reads.push(s);
      return s;
    });
    api.members.mockImplementation(() => new Subject<typeof MEMBERS>());
    cache.prefetch(['b-1', 'b-2'], null);
    expect(api.pollBoard).toHaveBeenCalledTimes(1);
    cache.leave();
    reads[0].complete();
    expect(api.pollBoard).toHaveBeenCalledTimes(1);
    expect(api.members).toHaveBeenCalledTimes(1);
    cache.prefetch(['b-1', 'b-2'], null);
    expect(api.pollBoard).toHaveBeenCalledTimes(2);
  });

  it('forgets every read when another person signs in', () => {
    const { cache, userId } = setup();
    cache.prefetch(['b-1'], null);
    cache.putCard(detail({ id: 'x' }));
    expect(cache.board('b-1')).not.toBeNull();
    userId.set('u-2');
    expect(cache.board('b-1')).toBeNull();
    expect(cache.members('b-1')).toBeNull();
    expect(cache.rows('all')).toBeNull();
    expect(cache.card('x')).toBeNull();
  });
});
