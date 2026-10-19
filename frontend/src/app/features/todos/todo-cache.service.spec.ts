import { TestBed } from '@angular/core/testing';
import { Subject, of, throwError, type Observable } from 'rxjs';
import {
  TodosApiService,
  type TodoAssignedPoll,
  type TodoBoardPoll,
  type TodoCardDetail,
} from '@core/api/todos.service';
import { MEMBERS, board, detail, tile } from '../../../testing/todo-fixtures';
import { TodoCacheService } from './todo-cache.service';

function setup(cardRead: (id: string) => Observable<TodoCardDetail> = (id) => of(detail({ id }))) {
  const boards = {
    'b-1': board({ id: 'b-1', cards: [tile({ id: 'k-1' }), tile({ id: 'k-2' })] }),
    'b-2': board({ id: 'b-2', cards: [tile({ id: 'k-3', boardId: 'b-2' })] }),
  } as Record<string, ReturnType<typeof board>>;
  const api = {
    pollBoard: jest.fn((id: string): Observable<TodoBoardPoll> => of({ board: boards[id], etag: `W/"${id}"` })),
    members: jest.fn(() => of(MEMBERS)),
    pollAllBoards: jest.fn((): Observable<TodoAssignedPoll> => of({ boards: [], etag: 'W/"a"' })),
    pollMineBoards: jest.fn((): Observable<TodoAssignedPoll> => of({ boards: [], etag: 'W/"m"' })),
    card: jest.fn(cardRead),
  };
  TestBed.configureTestingModule({ providers: [TodoCacheService, { provide: TodosApiService, useValue: api }] });
  return { cache: TestBed.inject(TodoCacheService), api, boards };
}

describe('TodoCacheService', () => {
  it('reads every other board, its people, the rows and the cards ahead once', () => {
    const { cache, api, boards } = setup();
    cache.prefetch(['b-1', 'b-2'], 'b-2');
    cache.prefetch(['b-1', 'b-2'], 'b-2');
    // The page reads the shown board itself.
    expect(api.pollBoard.mock.calls).toEqual([['b-1', null]]);
    expect(api.members.mock.calls).toEqual([['b-1']]);
    expect(api.pollAllBoards).toHaveBeenCalledWith(null);
    expect(api.pollMineBoards).toHaveBeenCalledWith(null);
    expect(cache.board('b-1')).toEqual({ board: boards['b-1'], etag: 'W/"b-1"' });
    expect(cache.board('b-2')).toBeNull();
    expect(cache.members('b-1')).toEqual(MEMBERS);
    expect(cache.rows('all')).toEqual({ boards: [], etag: 'W/"a"' });
    expect(api.card.mock.calls.map((c) => c[0])).toEqual(['k-1', 'k-2']);
    expect(cache.card('k-1')?.id).toBe('k-1');
  });

  it('reads at most four cards at once and goes on after a failure', () => {
    const reads = new Map<string, Subject<TodoCardDetail>>();
    const { cache, api } = setup((id) => {
      const s = new Subject<TodoCardDetail>();
      reads.set(id, s);
      return s;
    });
    cache.readCards(['a', 'b', 'c', 'd', 'e', 'f'].map((id) => tile({ id })));
    expect(api.card).toHaveBeenCalledTimes(4);
    reads.get('a')!.error(new Error('x'));
    reads.get('b')!.next(detail({ id: 'b' }));
    reads.get('b')!.complete();
    expect(api.card).toHaveBeenCalledTimes(6);
    expect(cache.card('a')).toBeNull();
    expect(cache.card('b')?.id).toBe('b');
    // The shown board goes first, and a card held or in flight is not read again.
    cache.readCards([tile({ id: 'b' }), tile({ id: 'c' })], true);
    expect(api.card).toHaveBeenCalledTimes(6);
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
    expect(api.card).not.toHaveBeenCalled();
  });

  it('leaves out a board whose read fails', () => {
    const { cache, api } = setup();
    api.pollBoard.mockReturnValueOnce(throwError(() => new Error('x')));
    api.members.mockReturnValueOnce(throwError(() => new Error('x')));
    cache.prefetch(['b-1'], null);
    expect(cache.board('b-1')).toBeNull();
    expect(cache.members('b-1')).toBeNull();
  });
});
