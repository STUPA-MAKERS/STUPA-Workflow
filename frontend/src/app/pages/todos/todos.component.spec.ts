import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { fireEvent, screen } from '@testing-library/angular';
import { Subject, of, throwError, type Observable } from 'rxjs';
import {
  TodosApiService,
  type TodoBoard,
  type TodoBoardPoll,
  type TodoBoardSummary,
  type TodoMine,
} from '@core/api/todos.service';
import { AuthService } from '@core/auth/auth.service';
import { MEDIA, ToastService } from '@stupa-makers/ui-kit';
import { PageFrameService } from '../../layout/page-frame.service';
import { BOARDS, MEMBERS, asPhone, board, detail, tile } from '../../../testing/todo-fixtures';
import { BOARD_POLL_MS, TodosComponent } from './todos.component';

interface Opts {
  boards?: TodoBoardSummary[];
  boardsFail?: boolean;
  board?: TodoBoard;
  gremien?: string[];
}

async function start(url: string, opts: Opts = {}) {
  const b = opts.board ?? board({ archivedCount: 2, cards: [
    tile({ id: 'k-1', columnId: 'c-1', title: 'Raum buchen', assignees: [{ principalId: 'p-1', displayName: 'Selin Yıldız' }] }),
    tile({ id: 'k-2', columnId: 'c-1', title: 'Haushalt Kapitel 3', labelIds: ['l-1'], dueDate: '2026-10-01' }),
    tile({ id: 'k-3', columnId: 'c-4', title: 'Bus anfragen' }),
  ] });
  const api = {
    boards: jest.fn(() => (opts.boardsFail ? throwError(() => new Error('x')) : of(opts.boards ?? BOARDS))),
    pollBoard: jest.fn((): Observable<TodoBoardPoll> => of({ board: b, etag: 'W/"1"' })),
    members: jest.fn(() => of(MEMBERS)),
    mine: jest.fn((): Observable<TodoMine> => of({ items: [{ ...tile({ id: 'k-1' }), boardName: '', boardKind: 'gremium', columnName: '', labels: [] }], dueSoonCount: 0 })),
    moveCard: jest.fn(() => of(tile({ id: 'k-1', columnId: 'c-2', title: 'Raum buchen' }))),
    createCard: jest.fn(() => of(detail({ id: 'k-9', columnId: 'c-1', title: 'Neu' }))),
    card: jest.fn(() => of(detail())),
    board: jest.fn(() => of(b)),
    linkTargets: jest.fn(() => of([])),
    archive: jest.fn(() => of({ items: [], total: 0, limit: 50, offset: 0 })),
  };
  const toast = { success: jest.fn(), error: jest.fn() };
  TestBed.configureTestingModule({
    providers: [
      provideRouter([
        { path: 'todos', component: TodosComponent },
        { path: 'todos/:boardId', component: TodosComponent },
      ]),
      { provide: TodosApiService, useValue: api },
      { provide: ToastService, useValue: toast },
    ],
  });
  const auth = TestBed.inject(AuthService);
  (auth as unknown as { _principal: { set(v: unknown): void } })._principal.set({
    id: 'me',
    permissions: [],
    gremien: (opts.gremien ?? ['g-1', 'g-2']).map((id) => ({ id, name: id, slug: id })),
  });
  const harness = await RouterTestingHarness.create();
  const cmp = await harness.navigateByUrl(url, TodosComponent);
  harness.detectChanges();
  const router = TestBed.inject(Router);
  const settle = async () => {
    await harness.fixture.whenStable();
    harness.detectChanges();
  };
  await settle();
  return { harness, cmp, router, api, toast, settle, b };
}

describe('TodosComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => jest.restoreAllMocks());

  it('opens the first gremium board from /todos and keeps the query', async () => {
    const { router, api, settle } = await start('/todos?view=list');
    await settle();
    expect(router.url).toBe('/todos/b-1?view=list');
    expect(api.pollBoard).toHaveBeenCalledWith('b-1', null);
    expect(api.members).toHaveBeenCalledWith('b-1');
  });

  it('opens the personal board when the caller belongs to none of the listed gremien', async () => {
    const { router, settle } = await start('/todos', { gremien: ['g-9'] });
    await settle();
    expect(router.url).toBe('/todos/b-0');
  });

  it('opens the board of an own gremium before a foreign one', async () => {
    const { router, settle } = await start('/todos', { gremien: ['g-2'] });
    await settle();
    expect(router.url).toBe('/todos/b-2');
  });

  it('says so when there is no board or the boards fail', async () => {
    const none = await start('/todos', { boards: [] });
    expect(none.cmp.notFound()).toBe(true);
    expect(screen.getByText('Dieses Board gibt es nicht oder du hast keinen Zugriff.')).toBeInTheDocument();
    expect(none.cmp.labelsById().size).toBe(0);
    expect(none.cmp.openCount()).toBe(0);
    expect(none.cmp.visible().size).toBe(0);
    expect(none.cmp.labelOptions()).toEqual([]);
    none.cmp.setDue('week');
    expect(none.cmp.noMatch()).toBe(true);
    none.cmp.reload();
    expect(none.api.pollBoard).not.toHaveBeenCalled();
  });

  it('shows an error when the boards fail without a board in the route', async () => {
    const failing = await start('/todos', { boardsFail: true });
    expect(failing.cmp.error()).toBe(true);
    expect(screen.getByRole('alert')).toHaveTextContent('Das Board konnte nicht geladen werden.');
  });

  it('keeps a board in the route when the board list fails', async () => {
    const { cmp } = await start('/todos/b-1', { boardsFail: true });
    expect(cmp.error()).toBe(false);
    expect(cmp.board()?.id).toBe('b-1');
  });

  it('shows the board with header, picker, search and filters in one bar', async () => {
    const { cmp } = await start('/todos/b-1');
    expect(screen.getByRole('heading', { level: 1, name: 'To-Dos' })).toBeInTheDocument();
    expect(screen.queryByText('2 offen')).toBeNull();
    expect(screen.queryByTestId('td-filter-toggle')).toBeNull();
    expect(screen.getByRole('group', { name: 'Filter' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Board: Studierendenparlament' })).toBeInTheDocument();
    expect(screen.getByPlaceholderText('2 offene To-Dos durchsuchen')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Board-Einstellungen' })).toBeInTheDocument();
    expect(document.querySelector('app-todo-board-view')).not.toBeNull();
    expect(cmp.assigneeText()).toBe('Zuständig');
    expect(cmp.labelText()).toBe('Label');
    expect(cmp.dueText()).toBe('Fällig');
    expect(cmp.assigneeOptions().map((o) => o.label)).toEqual(['Alle', 'Ich', 'Niemand', 'Selin Yıldız', 'Jonas Weber', 'Gelöschte Person']);
    expect(TestBed.inject(PageFrameService).fill()).toBe(true);
  });

  it('filters in the browser and resets the filters', async () => {
    const { cmp, api, harness } = await start('/todos/b-1');
    cmp.setAssignee('me');
    cmp.setAssignee('me');
    expect(api.mine).toHaveBeenCalledTimes(1);
    expect(cmp.visible().get('c-1')?.map((c) => c.id)).toEqual(['k-1']);
    expect(cmp.assigneeText()).toBe('Ich');
    cmp.setAssignee('p-9');
    expect(cmp.assigneeText()).toBe('Zuständig');
    cmp.setAssignee('');
    cmp.setLabels(['l-1']);
    expect(cmp.labelText()).toBe('Haushalt');
    cmp.setLabels(['l-x']);
    expect(cmp.labelText()).toBe('Label');
    cmp.setLabels(['l-1', 'l-2']);
    expect(cmp.labelText()).toBe('2 Labels');
    cmp.setLabels([]);
    cmp.setDue('overdue');
    expect(cmp.dueText()).toBe('Überfällig');
    expect(cmp.visible().get('c-1')?.map((c) => c.id)).toEqual(['k-2']);
    cmp.setDue('odd');
    expect(cmp.filter().due).toBe('');
    cmp.setDue('week');
    expect(cmp.noMatch()).toBe(false);
    expect(cmp.dueText()).toBe('In 7 Tagen');
    cmp.search.set('nichts');
    cmp.search.flush();
    harness.detectChanges();
    expect(cmp.noMatch()).toBe(true);
    expect(screen.getByText('Keine To-Dos passen zu den Filtern.')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('td-reset'));
    harness.detectChanges();
    expect(cmp.filtered()).toBe(false);
    expect(cmp.noMatch()).toBe(false);
    cmp.search.set('Raum');
    cmp.search.flush();
    expect(cmp.filter().q).toBe('Raum');
  });

  it('loads "me" again after a failure', async () => {
    const { cmp, api } = await start('/todos/b-1');
    api.mine.mockReturnValueOnce(throwError(() => new Error('x')));
    cmp.setAssignee('me');
    cmp.setAssignee('me');
    expect(api.mine).toHaveBeenCalledTimes(2);
  });

  it('reads "me" again after a change of a card and keeps a done card of mine', async () => {
    const { cmp, api } = await start('/todos/b-1');
    const mineOf = (...ids: string[]): Observable<TodoMine> =>
      of({ items: ids.map((id) => ({ ...tile({ id }), boardName: '', boardKind: 'gremium' as const, columnName: '', labels: [] })), dueSoonCount: 0 });
    cmp.onCardChanged(detail({ id: 'k-2', title: 'Haushalt Kapitel 3' }));
    expect(api.mine).not.toHaveBeenCalled();
    cmp.setAssignee('me');
    expect(cmp.visible().get('c-1')?.map((c) => c.id)).toEqual(['k-1']);

    api.mine.mockReturnValueOnce(mineOf('k-1', 'k-2'));
    cmp.onCardChanged(detail({ id: 'k-2', title: 'Haushalt Kapitel 3', assignees: [{ principalId: 'p-1', displayName: 'Ich' }] }));
    expect(cmp.visible().get('c-1')?.map((c) => c.id)).toEqual(['k-1', 'k-2']);

    api.mine.mockReturnValueOnce(mineOf('k-2', 'k-9'));
    cmp.onCreated(detail({ id: 'k-9', columnId: 'c-2', title: 'Neu' }));
    expect(cmp.visible().get('c-2')?.map((c) => c.id)).toEqual(['k-9']);
    expect(cmp.visible().get('c-1')?.map((c) => c.id)).toEqual(['k-2']);

    api.mine.mockReturnValueOnce(mineOf('k-2'));
    cmp.onCardChanged(detail({ id: 'k-9', columnId: 'c-4', title: 'Neu', assignees: [{ principalId: 'p-1', displayName: 'Ich' }] }));
    expect(cmp.visible().get('c-4')?.map((c) => c.id)).toEqual(['k-9']);

    const late = new Subject<TodoMine>();
    api.mine.mockReturnValueOnce(late);
    api.mine.mockReturnValueOnce(mineOf('k-1'));
    cmp.poll();
    cmp.poll();
    late.next({ items: [], dueSoonCount: 0 });
    expect(cmp.mine().has('k-1')).toBe(true);
  });

  it('switches to the list and back, and picks another board', async () => {
    const { cmp, router, settle, api } = await start('/todos/b-1');
    cmp.setView('list');
    await settle();
    expect(router.url).toBe('/todos/b-1?view=list');
    expect(document.querySelector('app-todo-list-view')).not.toBeNull();
    cmp.pickBoard('b-2');
    await settle();
    expect(router.url).toBe('/todos/b-2?view=list');
    expect(api.pollBoard).toHaveBeenLastCalledWith('b-2', null);
    cmp.setView('board');
    await settle();
    cmp.pickBoard('b-1');
    await settle();
    expect(router.url).toBe('/todos/b-1');
  });

  it('shows a missing board and a failed one with retry', async () => {
    const { cmp, api, settle, harness } = await start('/todos/b-1');
    api.pollBoard.mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 404 })));
    cmp.reload();
    await settle();
    expect(cmp.notFound()).toBe(true);
    api.pollBoard.mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 500 })));
    cmp.reload();
    harness.detectChanges();
    expect(cmp.error()).toBe(true);
    fireEvent.click(screen.getByTestId('td-retry'));
    harness.detectChanges();
    expect(cmp.board()).not.toBeNull();
  });

  it('drops late answers of a board that is no longer shown', async () => {
    const { cmp, api } = await start('/todos/b-1');
    const late = new Subject<TodoBoardPoll>();
    const lateMembers = new Subject<typeof MEMBERS>();
    api.pollBoard.mockReturnValueOnce(late);
    api.members.mockReturnValueOnce(lateMembers);
    cmp.reload();
    cmp.reload();
    late.next({ board: board({ name: 'Alt' }), etag: null });
    late.error(new Error('x'));
    lateMembers.next([]);
    expect(cmp.board()?.name).toBe('Studierendenparlament');
    expect(cmp.members()).toEqual(MEMBERS);
    api.members.mockReturnValueOnce(throwError(() => new Error('x')));
    cmp.reload();
    expect(cmp.members()).toEqual([]);
  });

  it('polls with the ETag while visible and on focus; 304 keeps the board', async () => {
    jest.useFakeTimers({ advanceTimers: true });
    try {
      const { cmp, api } = await start('/todos/b-1');
      api.pollBoard.mockClear();
      api.pollBoard.mockReturnValueOnce(of({ board: null, etag: 'W/"1"' }));
      jest.advanceTimersByTime(BOARD_POLL_MS);
      expect(api.pollBoard).toHaveBeenLastCalledWith('b-1', 'W/"1"');
      expect(cmp.board()?.name).toBe('Studierendenparlament');
      api.pollBoard.mockReturnValueOnce(of({ board: board({ name: 'Neu' }), etag: 'W/"2"' }));
      window.dispatchEvent(new Event('focus'));
      expect(cmp.board()?.name).toBe('Neu');
      api.pollBoard.mockReturnValueOnce(throwError(() => new Error('x')));
      cmp.poll();
      expect(cmp.board()?.name).toBe('Neu');
      const hidden = jest.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');
      const calls = api.pollBoard.mock.calls.length;
      jest.advanceTimersByTime(BOARD_POLL_MS);
      expect(api.pollBoard).toHaveBeenCalledTimes(calls);
      hidden.mockRestore();
      // A late poll of another board is dropped.
      const late = new Subject<TodoBoardPoll>();
      api.pollBoard.mockReturnValueOnce(late);
      cmp.poll();
      cmp.reload();
      late.next({ board: board({ name: 'Spät' }), etag: null });
      expect(cmp.board()?.name).toBe('Studierendenparlament');
      cmp.board.set(null);
      cmp.poll();
    } finally {
      jest.useRealTimers();
    }
  });

  it('moves a card at once and replaces it with the answer, or reloads on a failure', async () => {
    const { cmp, api, toast } = await start('/todos/b-1');
    cmp.moveCard({ cardId: 'k-1', move: { columnId: 'c-2' } });
    expect(api.moveCard).toHaveBeenCalledWith('k-1', { columnId: 'c-2' });
    expect(cmp.board()?.cards.find((c) => c.id === 'k-1')?.columnId).toBe('c-2');
    api.moveCard.mockReturnValueOnce(throwError(() => new Error('x')));
    const polls = api.pollBoard.mock.calls.length;
    cmp.moveCard({ cardId: 'k-2', move: { columnId: 'c-3' } });
    expect(toast.error).toHaveBeenCalledWith('Die Karte konnte nicht verschoben werden.');
    expect(api.pollBoard).toHaveBeenCalledTimes(polls + 1);
    const answer = new Subject<ReturnType<typeof tile>>();
    api.moveCard.mockReturnValueOnce(answer);
    cmp.moveCard({ cardId: 'k-2', move: { columnId: 'c-3' } });
    cmp.board.set(null);
    answer.next(tile());
    cmp.moveCard({ cardId: 'k-2', move: { columnId: 'c-3' } });
  });

  it('drops a poll that left before a local change and keeps its ETag', async () => {
    const { cmp, api } = await start('/todos/b-1');
    const late = new Subject<TodoBoardPoll>();
    api.pollBoard.mockReturnValueOnce(late);
    cmp.poll();
    cmp.moveCard({ cardId: 'k-1', move: { columnId: 'c-2' } });
    late.next({ board: board({ name: 'Vorher' }), etag: 'W/"0"' });
    expect(cmp.board()?.name).toBe('Studierendenparlament');
    expect(cmp.board()?.cards.find((c) => c.id === 'k-1')?.columnId).toBe('c-2');
    cmp.poll();
    expect(api.pollBoard).toHaveBeenLastCalledWith('b-1', 'W/"1"');
    // The other local changes count the same.
    for (const change of [
      () => cmp.quickAdd({ columnId: 'c-1', title: 'Neu' }),
      () => cmp.onCardChanged(detail({ id: 'k-2', title: 'Neu benannt' })),
      () => cmp.onArchived('k-3'),
      () => cmp.onRestored(detail({ id: 'k-7' })),
      () => cmp.onSettingsChanged(board({ name: 'StuPa', cards: cmp.board()!.cards })),
    ]) {
      const pending = new Subject<TodoBoardPoll>();
      api.pollBoard.mockReturnValueOnce(pending);
      cmp.poll();
      change();
      pending.next({ board: board({ name: 'Alt' }), etag: 'W/"0"' });
      expect(cmp.board()?.name).not.toBe('Alt');
    }
  });

  it('rolls a failed move back without clearing the filters, then reads the board again', async () => {
    const { cmp, api, toast } = await start('/todos/b-1');
    cmp.setLabels(['l-1']);
    cmp.search.set('Haushalt');
    cmp.search.flush();
    const fresh = board({ name: 'Frisch', cards: cmp.board()!.cards });
    api.moveCard.mockReturnValueOnce(throwError(() => new Error('x')));
    api.pollBoard.mockReturnValueOnce(of({ board: fresh, etag: 'W/"5"' }));
    cmp.moveCard({ cardId: 'k-2', move: { columnId: 'c-3' } });
    expect(toast.error).toHaveBeenCalledWith('Die Karte konnte nicht verschoben werden.');
    expect(api.pollBoard).toHaveBeenLastCalledWith('b-1', null);
    expect(cmp.board()).toBe(fresh);
    expect(cmp.loading()).toBe(false);
    expect(cmp.filter().labels).toEqual(['l-1']);
    expect(cmp.filter().q).toBe('Haushalt');
    expect(cmp.board()?.cards.find((c) => c.id === 'k-2')?.columnId).toBe('c-1');
    cmp.poll();
    expect(api.pollBoard).toHaveBeenLastCalledWith('b-1', 'W/"5"');

    // A change after the move keeps the board until the read answers; a failed read keeps it.
    const failed = new Subject<ReturnType<typeof tile>>();
    api.moveCard.mockReturnValueOnce(failed);
    cmp.moveCard({ cardId: 'k-2', move: { columnId: 'c-3' } });
    cmp.onCardChanged(detail({ id: 'k-1', title: 'Neu benannt' }));
    const changed = cmp.board();
    api.pollBoard.mockReturnValueOnce(throwError(() => new Error('x')));
    failed.error(new Error('x'));
    expect(cmp.board()).toBe(changed);

    // A read without a board, or one of a board that is no longer shown, is dropped.
    api.moveCard.mockReturnValueOnce(throwError(() => new Error('x')));
    api.pollBoard.mockReturnValueOnce(of({ board: null, etag: null }));
    cmp.moveCard({ cardId: 'k-2', move: { columnId: 'c-3' } });
    expect(cmp.board()?.id).toBe('b-1');
    const late = new Subject<TodoBoardPoll>();
    api.moveCard.mockReturnValueOnce(throwError(() => new Error('x')));
    api.pollBoard.mockReturnValueOnce(late);
    cmp.moveCard({ cardId: 'k-2', move: { columnId: 'c-3' } });
    cmp.reload();
    late.next({ board: board({ name: 'Spät' }), etag: null });
    expect(cmp.board()?.name).not.toBe('Spät');
  });

  it('puts a card that the drawer moved to another column at its rank there', async () => {
    const b = board({ cards: [
      tile({ id: 'k-1', columnId: 'c-1', rank: 'a' }),
      tile({ id: 'k-5', columnId: 'c-4', rank: 'b' }),
      tile({ id: 'k-6', columnId: 'c-4', rank: 'd' }),
    ] });
    const { cmp } = await start('/todos/b-1', { board: b });
    cmp.onCardChanged(detail({ id: 'k-1', columnId: 'c-4', rank: 'z' }));
    expect(cmp.visible().get('c-4')?.map((c) => c.id)).toEqual(['k-5', 'k-6', 'k-1']);
    cmp.onCardChanged(detail({ id: 'k-1', columnId: 'c-1', rank: 'a' }));
    cmp.onCardChanged(detail({ id: 'k-1', columnId: 'c-4', rank: 'c' }));
    expect(cmp.visible().get('c-4')?.map((c) => c.id)).toEqual(['k-5', 'k-1', 'k-6']);
  });

  it('toggles a card done from the list and back', async () => {
    const { cmp, api } = await start('/todos/b-1');
    cmp.toggleDone(cmp.board()!.cards[0]);
    expect(api.moveCard).toHaveBeenLastCalledWith('k-1', { columnId: 'c-4' });
    cmp.toggleDone(tile({ id: 'k-3', columnId: 'c-4' }));
    expect(api.moveCard).toHaveBeenLastCalledWith('k-3', { columnId: 'c-1' });
    cmp.board.set(board({ columns: [{ id: 'c-1', name: 'Offen', position: 0, isDone: false, cardCount: 0 }] }));
    const calls = api.moveCard.mock.calls.length;
    cmp.toggleDone(tile());
    expect(api.moveCard).toHaveBeenCalledTimes(calls);
    cmp.board.set(null);
    cmp.toggleDone(tile());
  });

  it('adds a card quickly and from the dialog', async () => {
    const { cmp, api, toast } = await start('/todos/b-1');
    cmp.quickAdd({ columnId: 'c-1', title: 'Neu' });
    expect(api.createCard).toHaveBeenCalledWith({ boardId: 'b-1', columnId: 'c-1', title: 'Neu' });
    expect(cmp.board()?.cards.some((c) => c.id === 'k-9')).toBe(true);
    api.createCard.mockReturnValueOnce(throwError(() => new Error('x')));
    cmp.quickAdd({ columnId: 'c-1', title: 'Neu' });
    expect(toast.error).toHaveBeenCalledWith('Das To-Do konnte nicht angelegt werden.');
    // A card of another board does not join this one.
    const before = cmp.board()!.cards.length;
    cmp.onCreated(detail({ id: 'k-x', boardId: 'b-2' }));
    expect(cmp.board()!.cards).toHaveLength(before);
    fireEvent.click(screen.getByTestId('td-new'));
    expect(cmp.newOpen()).toBe(true);
    expect(cmp.newColumn()).toBeNull();
    cmp.newCard('c-2');
    expect(cmp.newColumn()).toBe('c-2');
    cmp.board.set(null);
    cmp.quickAdd({ columnId: 'c-1', title: 'x' });
    cmp.onCreated(detail());
  });

  it('opens a card in the drawer, traps the focus and closes with Escape', async () => {
    const { cmp, router, settle, harness } = await start('/todos/b-1');
    cmp.openCard('k-1');
    await settle();
    expect(router.url).toBe('/todos/b-1?card=k-1');
    const drawer = screen.getByRole('dialog', { name: 'Raum buchen' });
    expect(document.activeElement).toBe(drawer);
    const focusable = Array.from(drawer.querySelectorAll<HTMLElement>('button:not([disabled])'));
    for (const el of focusable) Object.defineProperty(el, 'offsetParent', { value: drawer, configurable: true });
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    last.focus();
    fireEvent.keyDown(drawer, { key: 'Tab' });
    expect(document.activeElement).toBe(first);
    fireEvent.keyDown(drawer, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(last);
    // In the middle the browser moves the focus itself.
    fireEvent.keyDown(drawer, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(last);
    first.focus();
    fireEvent.keyDown(drawer, { key: 'Tab', shiftKey: false });
    expect(document.activeElement).toBe(first);
    fireEvent.keyDown(drawer, { key: 'a' });
    fireEvent.keyDown(drawer, { key: 'Escape' });
    await settle();
    expect(router.url).toBe('/todos/b-1');
    harness.detectChanges();
    expect(screen.queryByRole('dialog', { name: 'Raum buchen' })).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Raum buchen' }));
  });

  it('wraps a Tab from the drawer itself into the drawer', async () => {
    const { cmp, settle } = await start('/todos/b-1');
    cmp.openCard('k-1');
    await settle();
    const drawer = screen.getByRole('dialog', { name: 'Raum buchen' });
    expect(document.activeElement).toBe(drawer);
    const focusable = Array.from(drawer.querySelectorAll<HTMLElement>('button:not([disabled])'));
    for (const el of focusable) Object.defineProperty(el, 'offsetParent', { value: drawer, configurable: true });
    const back = new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, cancelable: true, bubbles: true });
    drawer.dispatchEvent(back);
    expect(back.defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(focusable[focusable.length - 1]);
    drawer.focus();
    fireEvent.keyDown(drawer, { key: 'Tab' });
    expect(document.activeElement).toBe(focusable[0]);
  });

  it('keeps the focus in a drawer without focusable items and closes via the scrim', async () => {
    const { cmp, settle, router } = await start('/todos/b-1?card=k-1');
    const drawer = screen.getByRole('dialog', { name: 'Raum buchen' });
    drawer.querySelectorAll('button, a, input, textarea, [tabindex]').forEach((el) => el.remove());
    const tab = new KeyboardEvent('keydown', { key: 'Tab', cancelable: true, bubbles: true });
    drawer.dispatchEvent(tab);
    expect(tab.defaultPrevented).toBe(true);
    const prevented = new KeyboardEvent('keydown', { key: 'Escape', cancelable: true, bubbles: true });
    prevented.preventDefault();
    drawer.dispatchEvent(prevented);
    expect(router.url).toBe('/todos/b-1?card=k-1');
    fireEvent.click(document.querySelector('.td__scrim')!);
    await settle();
    expect(router.url).toBe('/todos/b-1');
    cmp.closeCard();
  });

  it('leaves Escape in a dialog inside the drawer to that dialog', async () => {
    const { settle, router } = await start('/todos/b-1?card=k-1');
    const drawer = screen.getByRole('dialog', { name: 'Raum buchen' });
    const inner = document.createElement('div');
    inner.setAttribute('role', 'dialog');
    const button = document.createElement('button');
    inner.appendChild(button);
    drawer.appendChild(inner);
    fireEvent.keyDown(button, { key: 'Escape' });
    fireEvent.keyDown(button, { key: 'Tab' });
    await settle();
    expect(router.url).toBe('/todos/b-1?card=k-1');
  });

  it('gives the view switch equal segments', async () => {
    await start('/todos/b-1');
    expect(document.querySelector('app-segmented')?.getAttribute('width')).toBe('equal');
  });

  it('applies the changes of the drawer to the board', async () => {
    const { cmp, settle, router } = await start('/todos/b-1?card=k-1');
    cmp.onCardChanged(detail({ id: 'k-1', title: 'Neu benannt' }));
    expect(cmp.board()?.cards.find((c) => c.id === 'k-1')?.title).toBe('Neu benannt');
    cmp.onCardChanged(detail({ id: 'k-1', archivedAt: '2026-10-16T10:00:00Z' }));
    expect(cmp.board()?.cards.some((c) => c.id === 'k-1')).toBe(false);
    cmp.onCardChanged(detail({ id: 'k-2', boardId: 'b-2' }));
    cmp.onArchived('k-2');
    expect(cmp.board()?.archivedCount).toBe(3);
    await settle();
    expect(router.url).toBe('/todos/b-1');
    cmp.onRestored(detail({ id: 'k-7' }));
    expect(cmp.board()?.archivedCount).toBe(2);
    cmp.onRestored(detail({ id: 'k-8', boardId: 'b-2' }));
    cmp.board.set({ ...cmp.board()!, archivedCount: 0 });
    cmp.onRestored(detail({ id: 'k-9' }));
    expect(cmp.board()?.archivedCount).toBe(0);
    cmp.onSettingsChanged(board({ name: 'StuPa' }));
    expect(cmp.boards().find((b) => b.id === 'b-1')?.name).toBe('StuPa');
    expect(cmp.boards().find((b) => b.id === 'b-2')?.name).toBe('Fachschaft Informatik');
    cmp.board.set(null);
    cmp.onCardChanged(detail());
    cmp.onArchived('k-1');
    cmp.onRestored(detail());
  });

  it('opens the settings and the archive and does nothing without a board id', async () => {
    const { cmp, harness } = await start('/todos/b-1');
    fireEvent.click(screen.getByTestId('td-settings'));
    harness.detectChanges();
    expect(cmp.settingsOpen()).toBe(true);
    expect(screen.getByRole('dialog', { name: 'Board-Einstellungen' })).toBeInTheDocument();
  });

  describe('phone', () => {
    beforeEach(() => asPhone(MEDIA.phone));

    it('has the search button, the menu, the chips row and the FAB', async () => {
      const { cmp, harness } = await start('/todos/b-1');
      expect(screen.queryByPlaceholderText(/durchsuchen/)).toBeNull();
      fireEvent.click(screen.getByTestId('td-search-toggle'));
      harness.detectChanges();
      expect(screen.getByPlaceholderText('2 offene To-Dos durchsuchen')).toBeInTheDocument();
      expect(screen.queryByRole('group', { name: 'Filter' })).toBeNull();
      const filter = screen.getByTestId('td-filter-toggle');
      expect(filter).toHaveAttribute('aria-expanded', 'false');
      fireEvent.click(filter);
      harness.detectChanges();
      expect(filter).toHaveAttribute('aria-expanded', 'true');
      expect(filter).toHaveClass('on');
      expect(screen.getByRole('group', { name: 'Filter' })).toBeInTheDocument();
      expect(cmp.phoneMenu()[0].items.map((i) => i.id)).toEqual(['list', 'settings', 'archive']);
      cmp.onPhoneMenu({ id: 'settings', label: '' });
      expect(cmp.settingsOpen()).toBe(true);
      cmp.onPhoneMenu({ id: 'archive', label: '' });
      expect(cmp.archiveOpen()).toBe(true);
      cmp.onPhoneMenu({ id: 'odd', label: '' });
      fireEvent.click(screen.getByTestId('td-fab'));
      expect(cmp.newOpen()).toBe(true);
      expect(TestBed.inject(PageFrameService).fill()).toBe(false);
    });

    it('offers the board view from the list and leaves out settings and archive without them', async () => {
      const { cmp, settle, router } = await start('/todos/b-1?view=list', {
        board: board({ canConfigure: false, archivedCount: 0 }),
      });
      expect(cmp.phoneMenu()[0].items.map((i) => i.id)).toEqual(['board']);
      cmp.onPhoneMenu({ id: 'board', label: '' });
      await settle();
      expect(router.url).toBe('/todos/b-1');
      cmp.onPhoneMenu({ id: 'list', label: '' });
      await settle();
      expect(router.url).toBe('/todos/b-1?view=list');
    });
  });
});
