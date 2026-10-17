import { HttpErrorResponse } from '@angular/common/http';
import { provideRouter } from '@angular/router';
import { ApiClient } from '@core/api/api-client.service';
import { fireEvent, render, screen, within } from '@testing-library/angular';
import { Subject, of, throwError, type Observable } from 'rxjs';
import { TodosApiService, type TodoBoard, type TodoCardDetail, type TodoComment } from '@core/api/todos.service';
import { MEDIA, ToastService } from '@stupa-makers/ui-kit';
import { BOARDS, MEMBERS, asPhone, board, detail, link, tile } from '../../../../testing/todo-fixtures';
import { type FakeTodoLive, provideFakeTodoLive } from '../../../../testing/todo-live';
import { TodoLiveService } from '@core/ws/todo-live.service';
import { TestBed } from '@angular/core/testing';
import { DraftAttachmentsService } from '../../apply/draft-attachments.service';
import { TodoCardDetailComponent } from './todo-card-detail.component';

const COMMENT: TodoComment = {
  id: 'cm-1',
  author: { principalId: 'p-2', displayName: 'Jonas Weber' },
  body: 'Raum ist frei',
  mentions: [],
  at: '2026-10-15T09:00:00Z',
  editedAt: null,
  isOwn: true,
  attachments: [{ id: 'f1', filename: 'plan.pdf', mime: 'application/pdf', size: 20, scanState: 'quarantined' }],
};

const http = (status: number, code?: string) =>
  throwError(() => new HttpErrorResponse({ status, error: code ? { code } : null }));

function makeApi(card: TodoCardDetail) {
  const answer = (over: Partial<TodoCardDetail> = {}) => jest.fn((): Observable<TodoCardDetail> => of({ ...card, ...over }));
  return {
    card: jest.fn((): Observable<TodoCardDetail> => of(card)),
    members: jest.fn(() => of(MEMBERS)),
    board: jest.fn((): Observable<TodoBoard> => of(board())),
    moveCard: jest.fn(() => of(tile({ id: card.id, columnId: 'c-2', rank: 'b' }))),
    patchCard: answer({ version: card.version + 1 }),
    addAssignee: answer(),
    removeAssignee: answer(),
    addCardLabel: answer(),
    removeCardLabel: answer(),
    addCheckItem: answer(),
    patchCheckItem: answer(),
    deleteCheckItem: answer(),
    addLink: answer(),
    removeLink: answer(),
    archiveCard: jest.fn(() => of(undefined)),
    boards: jest.fn(() => of(BOARDS)),
    transferCard: jest.fn(
      (): Observable<TodoCardDetail> => of({ ...card, boardId: 'b-2', boardName: 'Fachschaft Informatik', columnId: 'c-1' }),
    ),
    restoreCard: answer({ archivedAt: null }),
    addComment: jest.fn(() => of({ ...COMMENT, id: 'cm-2', body: 'Neu' })),
    editComment: jest.fn(() => of({ ...COMMENT, body: 'Geändert', editedAt: '2026-10-15T10:00:00Z' })),
    deleteComment: jest.fn(() => of(undefined)),
    linkTargets: jest.fn(() => of([])),
  };
}

interface Opts {
  card?: TodoCardDetail;
  mode?: 'drawer' | 'pane';
  board?: TodoBoard | null;
}

async function setup(opts: Opts = {}) {
  const card = opts.card ?? detail({ comments: [COMMENT] });
  const api = makeApi(card);
  const toast = { success: jest.fn(), error: jest.fn() };
  const files = { deleteDraftAttachment: jest.fn(() => of(undefined)), uploadDraftAttachment: jest.fn() };
  const out = { closed: jest.fn(), changed: jest.fn(), commentsChanged: jest.fn(), archived: jest.fn() };
  const view = await render(TodoCardDetailComponent, {
    inputs: { cardId: card.id, mode: opts.mode ?? 'drawer', board: opts.board ?? null },
    on: out,
    providers: [
      provideRouter([]),
      { provide: TodosApiService, useValue: api },
      { provide: ApiClient, useValue: files },
      { provide: ToastService, useValue: toast },
      provideFakeTodoLive(),
    ],
  });
  const cmp = view.fixture.componentInstance;
  const detect = () => view.fixture.detectChanges();
  const live = TestBed.inject(TodoLiveService) as unknown as FakeTodoLive;
  return { ...view, api, toast, files, cmp, detect, live, ...out };
}

describe('TodoCardDetailComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));
  afterEach(() => jest.restoreAllMocks());

  it('shows the card side by side: activity, fields, links, description and checklist', async () => {
    const { api, container, closed, cmp, detect } = await setup();
    // The due line counts from today; pin today to the day the fixture dates were written for.
    cmp.today.set('2026-10-16');
    detect();
    expect(api.card).toHaveBeenCalledWith('k-1');
    expect(api.members).toHaveBeenCalledWith('b-1');
    expect(screen.getByRole('heading', { level: 2, name: 'Raum buchen' })).toBeInTheDocument();
    expect(document.querySelector('.cd__kicker')).toHaveTextContent('Studierendenparlament · To-Do');
    expect(screen.getByText(/^Angelegt von Selin Yıldız · /)).toBeInTheDocument();
    // The thread has no heading of its own; its column carries the name.
    expect(screen.queryByRole('heading', { name: 'Aktivität' })).toBeNull();
    expect(screen.getByRole('region', { name: 'Aktivität' })).toBeInTheDocument();
    expect(screen.getByText('Raum ist frei')).toBeInTheDocument();
    expect(screen.getByText('in 7 Tagen')).toBeInTheDocument();
    expect(screen.getByText('Haushalt')).toBeInTheDocument();
    const appLink = screen.getByRole('link', { name: 'Lerncafé' });
    expect(appLink).toHaveAttribute('href', '/applications/a-1');
    expect(screen.getByText('Raum')).toBeInTheDocument();
    // The checklist shows the open items; the done ones behind the toggle.
    expect(screen.getByRole('checkbox', { name: 'Raum anfragen' })).toHaveAttribute('aria-checked', 'false');
    expect(screen.queryByRole('checkbox', { name: 'Termin klären' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /1 erledigte Punkte zeigen/ }));
    expect(screen.getByRole('checkbox', { name: 'Termin klären' })).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByText('1/2')).toBeInTheDocument();
    expect(container.querySelector('.cd__bar-fill')).toHaveStyle({ width: '50%' });
    // The drawer closes with the ×; the pane-only link to the board is absent.
    expect(screen.queryByRole('link', { name: /Im Board öffnen/ })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Schließen' }));
    expect(closed).toHaveBeenCalled();
  });

  it('shows the board link in the pane and no close or copy button', async () => {
    const { container } = await setup({ mode: 'pane' });
    expect(screen.getByRole('link', { name: /Im Board öffnen/ })).toHaveAttribute('href', '/todos/b-1?card=k-1');
    expect(screen.queryByRole('button', { name: 'Schließen' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Link kopieren' })).toBeNull();
    expect(container.querySelector('app-sheet-bar')).not.toBeNull();
  });

  it('reads a card without write right and an archived one', async () => {
    const readOnly = await setup({
      card: detail({ canWrite: false, assignees: [], links: [link({ url: null, accessible: false, title: null })] }),
    });
    expect(screen.getByText('Offen')).toBeInTheDocument();
    expect(screen.getByText('Niemand')).toBeInTheDocument();
    expect(screen.getByText('Antrag (kein Zugriff)')).toHaveClass('cd__linkTitle--muted');
    expect(screen.queryByRole('button', { name: /Verknüpfen/ })).toBeNull();
    expect(screen.getByRole('checkbox', { name: 'Raum anfragen' })).toBeDisabled();
    expect(readOnly.cmp.menuSections()).toEqual([]);
  });

  it('offers no edit of an own comment on a board that the person only reads', async () => {
    const readOnly = await setup({ card: detail({ canWrite: false, comments: [COMMENT] }) });
    expect(readOnly.cmp.messages()[0]).toEqual(expect.objectContaining({ own: true, canEdit: false }));
    // An archived card of a writable board keeps the edit of an own comment.
    readOnly.cmp.card.set(detail({ archivedAt: '2026-10-12T10:00:00Z', comments: [COMMENT] }));
    expect(readOnly.cmp.messages()[0].canEdit).toBe(true);
  });

  it('names a write on a board that the person only reads', async () => {
    const { cmp, api, toast } = await setup();
    api.patchCard.mockReturnValueOnce(http(403, 'todo_write_required'));
    cmp.setDue('2026-10-30');
    expect(toast.error).toHaveBeenLastCalledWith('Dieses Board kannst du nur lesen.');
  });

  it('offers the restore for an archived card and shows when it was archived', async () => {
    const { cmp, api, changed } = await setup({ card: detail({ archivedAt: '2026-10-12T10:00:00Z' }) });
    expect(screen.getByText(/^Archiviert am /)).toBeInTheDocument();
    expect(cmp.canWrite()).toBe(false);
    expect(cmp.menuSections()[0].items[0].id).toBe('restore');
    cmp.onMenu({ id: 'restore', label: '' });
    expect(api.restoreCard).toHaveBeenCalledWith('k-1');
    expect(changed).toHaveBeenCalledWith(expect.objectContaining({ archivedAt: null }));
    expect(cmp.archivedLine()).toBeNull();
  });

  it('hides the empty fields and sections of an archived card', async () => {
    const empty = detail({
      archivedAt: '2026-10-12T10:00:00Z',
      dueDate: null,
      labels: [],
      links: [],
      descriptionMd: null,
      checklistItems: [],
    });
    const { container, cmp, detect } = await setup({ card: empty });
    cmp.today.set('2026-10-16');
    detect();
    const terms = () => [...container.querySelectorAll('.cd__field dt')].map((dt) => dt.textContent?.trim());
    const sections = () => screen.queryAllByRole('heading', { level: 3 }).map((h) => h.textContent?.trim());
    expect(terms()).toEqual(['Spalte', 'Zuständig']);
    expect(sections()).toEqual([]);
    expect(container.querySelector('.cd__col--chat')).toHaveClass('cd__col--readonly');
    // A writable card keeps every field and section, so that it can be filled.
    cmp.card.set({ ...empty, archivedAt: null });
    detect();
    expect(terms()).toEqual(['Spalte', 'Zuständig', 'Fällig', 'Label']);
    expect(sections()).toEqual(['Verknüpft', 'Beschreibung', 'Checkliste']);
    expect(container.querySelector('.cd__col--chat')).not.toHaveClass('cd__col--readonly');
  });

  it('reads the filled fields and sections of an archived card', async () => {
    const { container, cmp, detect } = await setup({ card: detail({ archivedAt: '2026-10-12T10:00:00Z' }) });
    cmp.today.set('2026-10-16');
    detect();
    expect(screen.getByText('Fällig')).toBeInTheDocument();
    expect(screen.getByText('in 7 Tagen')).toBeInTheDocument();
    expect(container.querySelector('.dc__chev')).toBeNull();
    const label = screen.getByText('Haushalt').closest('.cd__label');
    expect(label).toHaveAttribute('data-color', 'amber');
    expect(within(label as HTMLElement).queryByRole('button')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Label hinzufügen' })).toBeNull();
    expect(screen.getByRole('link', { name: 'Lerncafé' })).toHaveAttribute('href', '/applications/a-1');
    expect(screen.queryByRole('button', { name: /Verknüpfung mit .* entfernen/ })).toBeNull();
    expect(screen.getByText('A 101')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Beschreibung bearbeiten' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /1 erledigte Punkte zeigen/ }));
    expect(screen.getByRole('checkbox', { name: 'Termin klären' })).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByRole('checkbox', { name: 'Termin klären' })).toBeDisabled();
    expect(screen.getByRole('checkbox', { name: 'Raum anfragen' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: /Punkt hinzufügen/ })).toBeNull();
  });

  it('shows a missing card, an error with retry, and drops a late answer', async () => {
    const { cmp, api, detect, closed, fixture } = await setup();
    api.card.mockReturnValueOnce(http(404));
    fixture.componentRef.setInput('cardId', 'k-9');
    detect();
    expect(screen.getByText('Diese Karte gibt es nicht oder du hast keinen Zugriff.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Zum Board' }));
    expect(closed).toHaveBeenCalled();

    api.card.mockReturnValueOnce(http(500));
    cmp.reload();
    detect();
    expect(screen.getByRole('alert')).toHaveTextContent('Die Karte konnte nicht geladen werden.');
    fireEvent.click(screen.getByRole('button', { name: 'Erneut versuchen' }));
    detect();
    expect(cmp.card()?.id).toBe('k-1');

    const late = new Subject<TodoCardDetail>();
    api.card.mockReturnValueOnce(late);
    cmp.reload();
    cmp.reload();
    late.next(detail({ title: 'Alt' }));
    late.error(new Error('x'));
    expect(cmp.card()?.title).toBe('Raum buchen');
  });

  it('draws the sheet in its loaded shape while the card loads, with a working close button', async () => {
    const { cmp, api, detect, closed, fixture } = await setup({ board: board() });
    api.card.mockReturnValueOnce(new Subject<TodoCardDetail>());
    fixture.componentRef.setInput('cardId', 'k-2');
    detect();
    expect(cmp.loading()).toBe(true);
    expect(screen.getByRole('status')).toHaveTextContent('Karte wird geladen');
    // The kicker names the board, which the page already has.
    expect(cmp.loadingKicker()).toBe('Studierendenparlament · To-Do');
    expect(document.querySelectorAll('.cd__skelIcon')).toHaveLength(2);
    expect(document.querySelector('.cd__chat .sk__composer')).not.toBeNull();
    expect(document.querySelectorAll('.cd__fields dt').length).toBe(4);
    fireEvent.click(screen.getByRole('button', { name: 'Schließen' }));
    expect(closed).toHaveBeenCalled();
  });

  it('draws no composer while it loads for a board the person may not write to, and no kicker without a board', async () => {
    const { cmp, api, detect, fixture } = await setup({ board: board({ canWrite: false }) });
    api.card.mockReturnValueOnce(new Subject<TodoCardDetail>());
    fixture.componentRef.setInput('cardId', 'k-2');
    detect();
    expect(document.querySelector('.cd__chat .sk__composer')).toBeNull();
    fixture.componentRef.setInput('board', null);
    detect();
    expect(cmp.loadingKicker()).toBe('');
  });

  it('names no board while it loads a card of another board, and counts no foreign columns', async () => {
    const { cmp, api, detect, fixture } = await setup({ board: board({ id: 'b-0', name: 'Meine To-Dos' }) });
    const late = new Subject<TodoCardDetail>();
    api.card.mockReturnValueOnce(late);
    // A tile of a row of another board: the board of the page does not hold it.
    fixture.componentRef.setInput('cardId', 'k-9');
    detect();
    expect(cmp.loading()).toBe(true);
    expect(cmp.loadingKicker()).toBe('');
    expect(document.querySelector('.cd__chat .sk__composer')).toBeNull();
    late.next(detail({ id: 'k-9', boardId: 'b-7', boardName: 'AStA' }));
    detect();
    expect(cmp.kicker()).toBe('AStA · To-Do');
    // The board in the kicker links to the board.
    const boardLink = screen.getByTestId('cd-board');
    expect(boardLink).toHaveTextContent('AStA');
    expect(boardLink).toHaveAttribute('href', '/todos/b-7');
    expect(boardLink.closest('.sheet-bar__kicker')).not.toBeNull();
    expect(cmp.moveColumns().every((col) => col.count === null)).toBe(true);
  });

  it('reads only the comments again when the chat asks, for the scan state of their files', async () => {
    const { cmp, api, fixture, detect, commentsChanged } = await setup();
    const clean = { ...COMMENT, attachments: [{ ...COMMENT.attachments[0], scanState: 'clean' as const }] };
    const count = cmp.card()!.commentCount;
    api.card.mockReturnValueOnce(
      of(detail({ title: 'Anders', comments: [{ ...clean, body: 'Alt' }], commentCount: count + 5 })),
    );
    fixture.debugElement.query((d) => d.name === 'app-chat').triggerEventHandler('refresh');
    detect();
    expect(cmp.card()?.comments[0].attachments[0].scanState).toBe('clean');
    // The other fields stay as they are, the text and the count of the comments too.
    expect(cmp.card()?.title).toBe('Raum buchen');
    expect(cmp.card()?.comments[0].body).toBe('Raum ist frei');
    expect(commentsChanged).toHaveBeenLastCalledWith({ id: 'k-1', commentCount: count });

    // A read from before a send keeps the comment the send delivered.
    const stale = new Subject<TodoCardDetail>();
    api.card.mockReturnValueOnce(stale);
    cmp.refreshComments();
    cmp.sendComment({ body: 'Neu' });
    stale.next(detail({ comments: [clean] }));
    expect(cmp.card()?.comments.map((c) => c.id)).toEqual(['cm-1', 'cm-2']);

    // A failure changes nothing; an answer for a card the user left is dropped.
    api.card.mockReturnValueOnce(http(500));
    cmp.refreshComments();
    expect(cmp.error()).toBe(false);
    const late = new Subject<TodoCardDetail>();
    api.card.mockReturnValueOnce(late);
    cmp.refreshComments();
    fixture.componentRef.setInput('cardId', 'k-2');
    detect();
    late.next(detail({ comments: [] }));
    expect(cmp.card()?.comments).toHaveLength(1);
  });

  it('reads the people once per board and again after a failure', async () => {
    const { cmp, api } = await setup();
    cmp.reload();
    expect(api.members).toHaveBeenCalledTimes(1);
    api.members.mockReturnValueOnce(throwError(() => new Error('x')));
    api.card.mockReturnValueOnce(of(detail({ boardId: 'b-2' })));
    cmp.reload();
    expect(cmp.members()).toEqual([]);
    api.card.mockReturnValueOnce(of(detail({ boardId: 'b-2' })));
    cmp.reload();
    expect(api.members).toHaveBeenCalledTimes(3);
    expect(cmp.memberOptions().map((o) => o.label)).toEqual(['Selin Yıldız', 'Jonas Weber', 'Gelöschte Person']);
  });

  it('moves the card by column, done and reopen', async () => {
    const { cmp, api, changed } = await setup();
    cmp.setColumn('c-1');
    expect(api.moveCard).not.toHaveBeenCalled();
    cmp.setColumn('c-2');
    expect(api.moveCard).toHaveBeenLastCalledWith('k-1', { columnId: 'c-2' });
    expect(changed).toHaveBeenLastCalledWith(expect.objectContaining({ columnId: 'c-2', rank: 'b' }));
    expect(cmp.isDone()).toBe(false);
    cmp.toggleDone();
    expect(api.moveCard).toHaveBeenLastCalledWith('k-1', { columnId: 'c-4' });
    api.moveCard.mockReturnValueOnce(of(tile({ id: 'k-1', columnId: 'c-4' })));
    cmp.toggleDone();
    expect(cmp.isDone()).toBe(true);
    cmp.toggleDone();
    expect(api.moveCard).toHaveBeenLastCalledWith('k-1', { columnId: 'c-1' });
    // A card without a done column has nothing to toggle to.
    cmp.card.set(detail({ columns: [{ id: 'c-1', name: 'Offen', isDone: false }] }));
    const calls = api.moveCard.mock.calls.length;
    cmp.toggleDone();
    expect(api.moveCard).toHaveBeenCalledTimes(calls);
  });

  it('moves to the top of a column with the board of the page or a fresh read', async () => {
    const own = board({
      cards: [tile({ id: 'k-1', columnId: 'c-1' }), tile({ id: 'k-5', columnId: 'c-2' }), tile({ id: 'k-6', columnId: 'c-2' })],
    });
    const { cmp, api, fixture } = await setup({ board: own });
    expect(cmp.moveColumns()).toEqual([
      { id: 'c-1', name: 'Offen', count: 1 },
      { id: 'c-2', name: 'In Arbeit', count: 2 },
      { id: 'c-4', name: 'Erledigt', count: 0 },
    ]);
    cmp.moveTo({ columnId: 'c-2', position: 'top' });
    expect(api.moveCard).toHaveBeenLastCalledWith('k-1', { columnId: 'c-2', beforeId: 'k-5' });
    cmp.moveTo({ columnId: 'c-2', position: 'bottom' });
    expect(api.moveCard).toHaveBeenLastCalledWith('k-1', { columnId: 'c-2' });
    // Another board: read the card's own board; an empty column takes no neighbour.
    fixture.componentRef.setInput('board', board({ id: 'b-x' }));
    cmp.moveTo({ columnId: 'c-3', position: 'top' });
    expect(api.board).toHaveBeenCalledWith('b-1');
    expect(api.moveCard).toHaveBeenLastCalledWith('k-1', { columnId: 'c-3' });
    api.board.mockReturnValueOnce(http(500));
    cmp.moveTo({ columnId: 'c-3', position: 'top' });
    expect(cmp.card()).not.toBeNull();
  });

  it('changes the people, the due date and the labels', async () => {
    const { cmp, api } = await setup({
      card: detail({ assignees: [{ principalId: 'p-1', displayName: 'Selin Yıldız' }, { principalId: null, displayName: null }] }),
    });
    expect(cmp.memberOptions().map((o) => o.value)).toEqual(['p-2', 'p-3']);
    expect(screen.getAllByText('Gelöschte Person').length).toBeGreaterThan(0);
    cmp.addAssignee('');
    cmp.removeAssignee(null);
    expect(api.addAssignee).not.toHaveBeenCalled();
    expect(api.removeAssignee).not.toHaveBeenCalled();
    cmp.addAssignee('p-2');
    expect(api.addAssignee).toHaveBeenCalledWith('k-1', 'p-2');
    fireEvent.click(screen.getByRole('button', { name: 'Selin Yıldız entfernen' }));
    expect(api.removeAssignee).toHaveBeenCalledWith('k-1', 'p-1');
    cmp.setDue(null);
    expect(api.patchCard).toHaveBeenLastCalledWith('k-1', { version: 1, dueDate: null });
    expect(cmp.labelOptions()).toEqual([{ value: 'l-2', label: 'Sitzung' }]);
    cmp.addLabel('');
    expect(api.addCardLabel).not.toHaveBeenCalled();
    cmp.addLabel('l-2');
    expect(api.addCardLabel).toHaveBeenCalledWith('k-1', 'l-2');
    fireEvent.click(screen.getByRole('button', { name: 'Label Haushalt entfernen' }));
    expect(api.removeCardLabel).toHaveBeenCalledWith('k-1', 'l-1');
  });

  it('renames the card, keeps the same title and cancels', async () => {
    const { cmp, api, detect } = await setup();
    cmp.onMenu({ id: 'rename', label: '' });
    detect();
    expect(screen.getByRole('textbox', { name: 'Titel' })).toBeInTheDocument();
    expect(cmp.titleDraft()).toBe('Raum buchen');
    cmp.titleDraft.set('   ');
    cmp.saveTitle();
    expect(api.patchCard).not.toHaveBeenCalled();
    cmp.titleDraft.set('Raum buchen');
    cmp.saveTitle();
    expect(cmp.editingTitle()).toBe(false);
    expect(api.patchCard).not.toHaveBeenCalled();
    cmp.startTitle();
    cmp.titleDraft.set(' Raum A 101 buchen ');
    cmp.saveTitle();
    expect(api.patchCard).toHaveBeenCalledWith('k-1', { version: 1, title: 'Raum A 101 buchen' });
    expect(cmp.editingTitle()).toBe(false);
    expect(cmp.card()?.version).toBe(2);
  });

  it('edits the description and clears it', async () => {
    const { cmp, api, detect } = await setup({ card: detail({ descriptionMd: null }) });
    fireEvent.click(screen.getByRole('button', { name: 'Beschreibung bearbeiten' }));
    detect();
    expect(cmp.descDraft()).toBe('');
    // The image button opens the file dialog of the upload directive.
    const click = jest.spyOn(HTMLInputElement.prototype, 'click').mockImplementation(() => undefined);
    fireEvent.click(screen.getByRole('button', { name: 'Bild einfügen' }));
    expect(click).toHaveBeenCalled();
    click.mockRestore();
    cmp.descDraft.set('  Neu  ');
    cmp.saveDesc();
    expect(api.patchCard).toHaveBeenLastCalledWith('k-1', { version: 1, descriptionMd: 'Neu' });
    expect(cmp.editingDesc()).toBe(false);
    cmp.startDesc();
    cmp.descDraft.set('   ');
    cmp.saveDesc();
    expect(api.patchCard).toHaveBeenLastCalledWith('k-1', { version: 2, descriptionMd: null });
  });

  it('sends a second patch only after the first answered, with its version', async () => {
    const { cmp, api, toast, fixture } = await setup();
    const first = new Subject<TodoCardDetail>();
    api.patchCard.mockReturnValueOnce(first);
    cmp.startDesc();
    cmp.descDraft.set('Neu');
    cmp.saveDesc();
    cmp.setDue('2026-10-30');
    expect(api.patchCard).toHaveBeenCalledTimes(1);
    first.next(detail({ version: 3, descriptionMd: 'Neu' }));
    expect(api.patchCard).toHaveBeenCalledTimes(2);
    expect(api.patchCard).toHaveBeenLastCalledWith('k-1', { version: 3, dueDate: '2026-10-30' });
    expect(cmp.editingDesc()).toBe(false);
    expect(toast.error).not.toHaveBeenCalled();

    const refused = new Subject<TodoCardDetail>();
    api.patchCard.mockReturnValueOnce(refused);
    cmp.setDue(null);
    cmp.startTitle();
    cmp.titleDraft.set('Anders');
    cmp.saveTitle();
    refused.error(new HttpErrorResponse({ status: 409, error: { code: 'card_version_conflict' } }));
    expect(api.patchCard).toHaveBeenCalledTimes(3);
    cmp.setDue('2026-11-02');
    expect(api.patchCard).toHaveBeenCalledTimes(4);

    const stale = new Subject<TodoCardDetail>();
    api.patchCard.mockReturnValueOnce(stale);
    cmp.setDue(null);
    fixture.componentRef.setInput('cardId', 'k-2');
    fixture.detectChanges();
    stale.next(detail({ version: 9 }));
    cmp.setDue('2026-11-03');
    expect(api.patchCard).toHaveBeenCalledTimes(6);
  });

  it('works the checklist', async () => {
    const { cmp, api, detect } = await setup();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Raum anfragen' }));
    expect(api.patchCheckItem).toHaveBeenLastCalledWith('k-1', 'i-2', { done: true });
    fireEvent.click(screen.getByRole('button', { name: 'Punkt hinzufügen' }));
    detect();
    cmp.itemDraft.set('  ');
    cmp.addItem();
    expect(api.addCheckItem).not.toHaveBeenCalled();
    cmp.itemDraft.set('Schlüssel holen');
    cmp.addItem();
    expect(api.addCheckItem).toHaveBeenCalledWith('k-1', 'Schlüssel holen');
    expect(cmp.itemDraft()).toBe('');
    cmp.cancelItem();
    expect(cmp.addingItem()).toBe(false);

    fireEvent.click(screen.getByRole('button', { name: '„Raum anfragen“ umbenennen' }));
    detect();
    expect(screen.getByRole('textbox', { name: 'Text des Punkts' })).toBeInTheDocument();
    expect(cmp.itemEditDraft()).toBe('Raum anfragen');
    const item = cmp.items()[1];
    cmp.renameItem(item);
    expect(cmp.editingItem()).toBeNull();
    cmp.startItem(item);
    cmp.itemEditDraft.set('');
    cmp.renameItem(item);
    expect(api.patchCheckItem).toHaveBeenCalledTimes(1);
    cmp.startItem(item);
    cmp.itemEditDraft.set('Raum A anfragen');
    cmp.renameItem(item);
    expect(api.patchCheckItem).toHaveBeenLastCalledWith('k-1', 'i-2', { text: 'Raum A anfragen' });
    expect(cmp.editingItem()).toBeNull();
    detect();
    fireEvent.click(screen.getByRole('button', { name: '„Raum anfragen“ löschen' }));
    expect(api.deleteCheckItem).toHaveBeenCalledWith('k-1', 'i-2');
    // Hide the done items again.
    cmp.showDone.set(true);
    detect();
    fireEvent.click(screen.getByRole('button', { name: /Erledigte Punkte ausblenden/ }));
    expect(cmp.showDone()).toBe(false);
  });

  it('keeps the focus in the drawer when an inline editor opens, closes or a row goes', async () => {
    const items = [
      { id: 'i-1', text: 'Eins', done: false, position: 0 },
      { id: 'i-2', text: 'Zwei', done: false, position: 1 },
      { id: 'i-3', text: 'Drei', done: false, position: 2 },
    ];
    const { cmp, api, fixture } = await setup({ card: detail({ descriptionMd: 'Alt', checklistItems: items }) });
    const settle = async () => {
      fixture.detectChanges();
      await fixture.whenStable();
    };
    const active = () => document.activeElement as HTMLElement;

    const descEdit = screen.getByRole('button', { name: 'Beschreibung bearbeiten' });
    descEdit.focus();
    fireEvent.click(descEdit);
    await settle();
    expect(active().tagName).toBe('TEXTAREA');
    fireEvent.keyDown(active(), { key: 'Escape' });
    await settle();
    expect(active()).toBe(screen.getByRole('button', { name: 'Beschreibung bearbeiten' }));
    cmp.startDesc();
    await settle();
    cmp.saveDesc();
    await settle();
    expect(active()).toBe(screen.getByRole('button', { name: 'Beschreibung bearbeiten' }));

    fireEvent.click(screen.getByRole('button', { name: 'Punkt hinzufügen' }));
    await settle();
    expect(active()).toBe(screen.getByRole('textbox', { name: 'Neuer Punkt' }));
    fireEvent.keyDown(active(), { key: 'Escape' });
    await settle();
    expect(active()).toBe(screen.getByRole('button', { name: 'Punkt hinzufügen' }));

    fireEvent.click(screen.getByRole('button', { name: '„Zwei“ umbenennen' }));
    await settle();
    expect(active()).toBe(screen.getByRole('textbox', { name: 'Text des Punkts' }));
    fireEvent.keyDown(active(), { key: 'Escape' });
    await settle();
    expect(active()).toBe(screen.getByRole('button', { name: '„Zwei“ umbenennen' }));

    api.deleteCheckItem.mockReturnValueOnce(of(detail({ descriptionMd: 'Alt', checklistItems: [items[0], items[2]] })));
    fireEvent.click(screen.getByRole('button', { name: '„Zwei“ löschen' }));
    await settle();
    expect(active()).toBe(screen.getByRole('checkbox', { name: 'Drei' }));
    api.deleteCheckItem.mockReturnValueOnce(of(detail({ descriptionMd: 'Alt', checklistItems: [items[0]] })));
    fireEvent.click(screen.getByRole('button', { name: '„Drei“ löschen' }));
    await settle();
    expect(active()).toBe(screen.getByRole('checkbox', { name: 'Eins' }));
    api.deleteCheckItem.mockReturnValueOnce(of(detail({ descriptionMd: 'Alt', checklistItems: [] })));
    fireEvent.click(screen.getByRole('button', { name: '„Eins“ löschen' }));
    await settle();
    expect(active()).toBe(screen.getByRole('button', { name: 'Punkt hinzufügen' }));
  });

  it('shows no progress for an empty checklist and a read-only toggle does nothing', async () => {
    const { cmp, api, container } = await setup({ card: detail({ checklistItems: [], canWrite: false }) });
    expect(cmp.progress()).toBe(0);
    expect(container.querySelector('.cd__progress')).toBeNull();
    cmp.toggleItem({ id: 'i-1', text: 'x', done: false, position: 0 });
    expect(api.patchCheckItem).not.toHaveBeenCalled();
  });

  it('links a picked target and takes a linked one off', async () => {
    const { cmp, api } = await setup();
    expect(cmp.linkedKeys().has('application:a-1')).toBe(true);
    cmp.pickLink({ kind: 'application', targetId: 'a-1', title: 'Lerncafé', detail: null });
    expect(api.removeLink).toHaveBeenCalledWith('k-1', 'li-1');
    cmp.pickLink({ kind: 'ticket', targetId: 't-1', title: 'Login', detail: null });
    expect(api.addLink).toHaveBeenCalledWith('k-1', 'ticket', 't-1');
    fireEvent.click(screen.getByRole('button', { name: 'Verknüpfung mit Lerncafé entfernen' }));
    expect(api.removeLink).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByRole('button', { name: /Verknüpfen/ }));
    expect(cmp.pickerOpen()).toBe(true);
    expect(cmp.route('/meetings/m-1?item=t-1')).toEqual({ path: '/meetings/m-1', query: { item: 't-1' } });
  });

  it('archives the card', async () => {
    const { cmp, api, toast, archived } = await setup();
    cmp.onMenu({ id: 'archive', label: '' });
    expect(api.archiveCard).toHaveBeenCalledWith('k-1');
    expect(toast.success).toHaveBeenCalledWith('Diese Karte ist archiviert.');
    expect(archived).toHaveBeenCalledWith('k-1');
    cmp.onMenu({ id: 'other', label: '' });
    api.archiveCard.mockReturnValueOnce(http(500) as never);
    cmp.archive();
    expect(toast.error).toHaveBeenCalledWith('Die Änderung konnte nicht gespeichert werden.');
  });

  it('moves the card to another board from the menu', async () => {
    const { cmp, api, toast, changed, detect } = await setup();
    expect(cmp.menuSections()[0].items.map((i) => [i.id, i.icon])).toEqual([
      ['rename', 'edit'],
      ['transfer', 'arrow'],
    ]);
    expect(cmp.menuSections()[1].items[0].id).toBe('archive');
    cmp.onMenu({ id: 'transfer', label: '' });
    detect();
    expect(screen.getByRole('dialog', { name: 'In anderes Board verschieben' })).toBeInTheDocument();
    // Neither the current board nor, for a card of a gremium board, the personal board is a target.
    expect(api.boards).toHaveBeenCalled();
    expect(api.board).toHaveBeenCalledWith('b-2');
    expect(api.board).not.toHaveBeenCalledWith('b-0');
    const order: string[] = [];
    const transferred = jest.fn(() => order.push('transferred'));
    cmp.transferred.subscribe(transferred);
    changed.mockImplementation(() => order.push('changed'));
    const from = cmp.card()?.boardId;
    cmp.transfer({ boardId: 'b-2', columnId: 'c-1', boardName: 'Fachschaft Informatik' });
    expect(api.transferCard).toHaveBeenCalledWith('k-1', { boardId: 'b-2', columnId: 'c-1' });
    expect(changed).toHaveBeenLastCalledWith(expect.objectContaining({ boardId: 'b-2' }));
    // The page learns of the transfer first, with the board the card left.
    expect(transferred).toHaveBeenCalledWith({ card: expect.objectContaining({ boardId: 'b-2' }), fromBoardId: from });
    expect(order).toEqual(['transferred', 'changed']);
    expect(cmp.card()?.boardId).toBe('b-2');
    expect(api.members).toHaveBeenLastCalledWith('b-2');
    expect(toast.success).toHaveBeenCalledWith('Karte nach „Fachschaft Informatik“ verschoben');
    expect(cmp.transferOpen()).toBe(false);
    expect(cmp.transferring()).toBe(false);
    expect(cmp.busy()).toBe(false);
  });

  it('names a refused transfer and reads the card again', async () => {
    const { cmp, api, toast } = await setup();
    const target = { boardId: 'b-2', columnId: 'c-1', boardName: 'X' };
    for (const [err, text] of [
      [http(409, 'card_moved'), 'Die Karte konnte nicht verschoben werden.'],
      [http(409, 'card_archived'), 'Die Karte konnte nicht verschoben werden.'],
      [http(422, 'transfer_same_board'), 'Die Karte konnte nicht verschoben werden.'],
      [http(422, 'column_not_on_board'), 'Die Karte konnte nicht verschoben werden.'],
      [http(403, 'transfer_to_personal'), 'Karten aus geteilten Boards können nicht ins persönliche Board verschoben werden.'],
      [http(404), 'Die Karte konnte nicht verschoben werden.'],
      [http(500), 'Die Änderung konnte nicht gespeichert werden.'],
    ] as const) {
      const reads = api.card.mock.calls.length;
      cmp.transferOpen.set(true);
      api.transferCard.mockReturnValueOnce(err as never);
      cmp.transfer(target);
      expect(toast.error).toHaveBeenLastCalledWith(text);
      expect(api.card).toHaveBeenCalledTimes(reads + 1);
      expect(cmp.transferOpen()).toBe(false);
      expect(cmp.busy()).toBe(false);
    }
  });

  it('drops a transfer answer for a card that is no longer shown', async () => {
    const { cmp, api, toast, changed, fixture } = await setup();
    const answer = new Subject<TodoCardDetail>();
    api.transferCard.mockReturnValueOnce(answer);
    cmp.transfer({ boardId: 'b-2', columnId: 'c-1', boardName: 'X' });
    expect(cmp.transferring()).toBe(true);
    fixture.componentRef.setInput('cardId', 'k-9');
    fixture.detectChanges();
    answer.next(detail({ boardId: 'b-2' }));
    const failing = new Subject<TodoCardDetail>();
    api.transferCard.mockReturnValueOnce(failing);
    cmp.transfer({ boardId: 'b-2', columnId: 'c-1', boardName: 'X' });
    fixture.componentRef.setInput('cardId', 'k-1');
    fixture.detectChanges();
    failing.error(new HttpErrorResponse({ status: 500 }));
    expect(changed).not.toHaveBeenCalledWith(expect.objectContaining({ boardId: 'b-2' }));
    expect(toast.success).not.toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();
    cmp.card.set(null);
    api.transferCard.mockClear();
    cmp.transfer({ boardId: 'b-2', columnId: 'c-1', boardName: 'X' });
    expect(api.transferCard).not.toHaveBeenCalled();
  });

  it('names the refusal of the server and reads the card again', async () => {
    const { cmp, api, toast } = await setup();
    api.patchCard.mockReturnValueOnce(http(409, 'card_version_conflict'));
    cmp.setDue('2026-10-30');
    expect(toast.error).toHaveBeenLastCalledWith('Jemand hat die Karte inzwischen geändert. Sie wurde neu geladen.');
    expect(api.card).toHaveBeenCalledTimes(2);
    expect(cmp.busy()).toBe(false);
    api.addLink.mockReturnValueOnce(http(422, 'odd_code'));
    cmp.pickLink({ kind: 'ticket', targetId: 't-1', title: 'x', detail: null });
    expect(toast.error).toHaveBeenLastCalledWith('Die Änderung konnte nicht gespeichert werden.');
    api.addLink.mockReturnValueOnce(throwError(() => new Error('net')));
    cmp.pickLink({ kind: 'ticket', targetId: 't-1', title: 'x', detail: null });
    expect(toast.error).toHaveBeenLastCalledWith('Die Änderung konnte nicht gespeichert werden.');
    api.moveCard.mockReturnValueOnce(http(404) as never);
    cmp.setColumn('c-2');
    expect(cmp.notFound()).toBe(true);
    expect(cmp.card()).toBeNull();
  });

  it('reads the card again on a 404 of a checklist item or a link, and drops it only on a 404 of the card', async () => {
    const { cmp, api, toast } = await setup();
    const item = cmp.items()[0];
    for (const run of [
      () => {
        api.patchCheckItem.mockReturnValueOnce(http(404));
        cmp.toggleItem(item);
      },
      () => {
        api.deleteCheckItem.mockReturnValueOnce(http(404));
        cmp.deleteItem(item);
      },
      () => {
        api.removeLink.mockReturnValueOnce(http(404));
        cmp.removeLink(link());
      },
    ]) {
      const reads = api.card.mock.calls.length;
      run();
      expect(toast.error).toHaveBeenLastCalledWith('Die Änderung konnte nicht gespeichert werden.');
      expect(api.card).toHaveBeenCalledTimes(reads + 1);
      expect(cmp.notFound()).toBe(false);
      expect(cmp.card()?.id).toBe('k-1');
    }
    // The card route itself: the card is gone.
    for (const run of [
      () => {
        api.patchCard.mockReturnValueOnce(http(404));
        cmp.setDue('2026-10-30');
      },
      () => {
        api.restoreCard.mockReturnValueOnce(http(404));
        cmp.restore();
      },
      () => {
        api.archiveCard.mockReturnValueOnce(http(404) as never);
        cmp.archive();
      },
    ]) {
      run();
      expect(cmp.notFound()).toBe(true);
      expect(cmp.card()).toBeNull();
      cmp.reload();
    }
  });

  it('drops the answers of writes on a card that is no longer shown', async () => {
    const { cmp, api, toast, changed, archived, fixture } = await setup();
    const write = new Subject<TodoCardDetail>();
    const writeErr = new Subject<TodoCardDetail>();
    const move = new Subject<ReturnType<typeof tile>>();
    const moveErr = new Subject<ReturnType<typeof tile>>();
    const boardRead = new Subject<TodoBoard>();
    const boardErr = new Subject<TodoBoard>();
    const edit = new Subject<TodoComment>();
    const editErr = new Subject<TodoComment>();
    const del = new Subject<undefined>();
    const delErr = new Subject<undefined>();
    const arch = new Subject<undefined>();
    const archErr = new Subject<undefined>();
    api.addAssignee.mockReturnValueOnce(write).mockReturnValueOnce(writeErr);
    api.moveCard.mockReturnValueOnce(move as never).mockReturnValueOnce(moveErr as never);
    api.board.mockReturnValueOnce(boardRead).mockReturnValueOnce(boardErr);
    api.editComment.mockReturnValueOnce(edit as never).mockReturnValueOnce(editErr as never);
    api.deleteComment.mockReturnValueOnce(del as never).mockReturnValueOnce(delErr as never);
    api.archiveCard.mockReturnValueOnce(arch as never).mockReturnValueOnce(archErr as never);
    cmp.addAssignee('p-2');
    cmp.addAssignee('p-3');
    cmp.setColumn('c-2');
    cmp.setColumn('c-3');
    cmp.moveTo({ columnId: 'c-2', position: 'top' });
    cmp.moveTo({ columnId: 'c-3', position: 'top' });
    const staleRestore = jest.fn();
    cmp.editComment({ id: 'cm-1', body: 'x' });
    cmp.editComment({ id: 'cm-1', body: 'y', restore: staleRestore });
    cmp.deleteComment({ id: 'cm-1' });
    cmp.deleteComment({ id: 'cm-1' });
    cmp.archive();
    cmp.archive();

    const other = detail({ id: 'k-2', title: 'Andere Karte', comments: [] });
    api.card.mockReturnValueOnce(of(other));
    fixture.componentRef.setInput('cardId', 'k-2');
    fixture.detectChanges();
    expect(cmp.card()).toBe(other);
    // The writes of k-1 are still out; k-2 starts with its buttons free.
    expect(cmp.busy()).toBe(false);
    const moves = api.moveCard.mock.calls.length;

    write.next(detail({ id: 'k-1' }));
    writeErr.error(new HttpErrorResponse({ status: 404 }));
    move.next(tile({ id: 'k-1', columnId: 'c-2' }));
    moveErr.error(new HttpErrorResponse({ status: 500 }));
    boardRead.next(board());
    boardErr.error(new HttpErrorResponse({ status: 500 }));
    edit.next(COMMENT);
    editErr.error(new Error('x'));
    del.next(undefined);
    delErr.error(new Error('x'));
    arch.next(undefined);
    archErr.error(new HttpErrorResponse({ status: 404 }));

    expect(cmp.card()).toBe(other);
    expect(cmp.notFound()).toBe(false);
    expect(changed).not.toHaveBeenCalled();
    expect(archived).not.toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();
    expect(toast.success).not.toHaveBeenCalled();
    expect(api.moveCard).toHaveBeenCalledTimes(moves);
    // A refused edit of a card no longer shown opens nothing.
    expect(staleRestore).not.toHaveBeenCalled();
  });

  it('reports a failed read of the board for "top of the column"', async () => {
    const { cmp, api, toast } = await setup();
    api.board.mockReturnValueOnce(http(500) as never);
    cmp.moveTo({ columnId: 'c-2', position: 'top' });
    expect(toast.error).toHaveBeenLastCalledWith('Die Änderung konnte nicht gespeichert werden.');
  });

  it('keeps Escape of an edit inside the card and keeps the title heading for the drawer', async () => {
    const { cmp, detect, container } = await setup();
    cmp.startTitle();
    detect();
    expect(container.querySelector('#cd-title')).toHaveTextContent('Raum buchen');
    const box = screen.getByRole('textbox', { name: 'Titel' });
    const outer = jest.fn();
    container.addEventListener('keydown', outer);
    const esc = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
    box.dispatchEvent(esc);
    detect();
    expect(esc.defaultPrevented).toBe(true);
    expect(outer).not.toHaveBeenCalled();
    expect(cmp.editingTitle()).toBe(false);
    cmp.startDesc();
    detect();
    const desc = container.querySelector<HTMLTextAreaElement>('.cd__areaInput')!;
    const esc2 = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
    desc.dispatchEvent(esc2);
    detect();
    expect(esc2.defaultPrevented).toBe(true);
    expect(cmp.editingDesc()).toBe(false);
    expect(outer).not.toHaveBeenCalled();
  });

  it('does nothing without a card', async () => {
    const { cmp, api } = await setup();
    cmp.card.set(null);
    cmp.setColumn('c-2');
    cmp.moveTo({ columnId: 'c-2', position: 'top' });
    cmp.toggleDone();
    cmp.addAssignee('p-2');
    cmp.removeAssignee('p-1');
    cmp.setDue(null);
    cmp.addLabel('l-1');
    cmp.removeLabel('l-1');
    cmp.saveTitle();
    cmp.startTitle();
    cmp.saveDesc();
    cmp.startDesc();
    cmp.toggleItem({ id: 'i', text: 'x', done: false, position: 0 });
    cmp.itemDraft.set('x');
    cmp.addItem();
    cmp.renameItem({ id: 'i', text: 'x', done: false, position: 0 });
    cmp.deleteItem({ id: 'i', text: 'x', done: false, position: 0 });
    cmp.pickLink({ kind: 'ticket', targetId: 't', title: 'x', detail: null });
    cmp.removeLink(link());
    cmp.archive();
    cmp.restore();
    cmp.copyLink();
    cmp.editComment({ id: 'cm-1', body: 'x' });
    cmp.deleteComment({ id: 'cm-1' });
    for (const fn of [
      api.moveCard, api.addAssignee, api.removeAssignee, api.patchCard, api.addCardLabel, api.removeCardLabel,
      api.patchCheckItem, api.addCheckItem, api.deleteCheckItem, api.addLink, api.removeLink, api.archiveCard,
      api.restoreCard, api.editComment, api.deleteComment,
    ]) {
      expect(fn).not.toHaveBeenCalled();
    }
    expect(cmp.titleDraft()).toBe('');
    expect(cmp.descDraft()).toBe('');
    expect(cmp.kicker()).toBe('');
    expect(cmp.createdLine()).toBe('');
    expect(cmp.moveColumns()).toEqual([]);
    expect(cmp.boardLink()).toBeNull();
    expect(cmp.labelOptions()).toEqual([]);
    expect(cmp.columnName()).toBe('');
    expect(cmp.isDone()).toBe(false);
    expect(cmp.tabs()[1].count).toBe(0);
    expect(cmp.columnOptions()).toEqual([]);
    expect(cmp.memberOptions()).toHaveLength(3);
    expect(cmp.items()).toEqual([]);
    expect(cmp.linkedKeys().size).toBe(0);
    expect(cmp.messages()).toEqual([]);
    expect(cmp.events()).toEqual([]);
  });

  it('drops a late comment or move when the card is gone', async () => {
    const { cmp, api, changed } = await setup();
    const comment = new Subject<TodoComment>();
    api.addComment.mockReturnValueOnce(comment);
    cmp.sendComment({ body: 'x' });
    const boardRead = new Subject<TodoBoard>();
    api.board.mockReturnValueOnce(boardRead);
    cmp.moveTo({ columnId: 'c-2', position: 'top' });
    cmp.card.set(null);
    comment.next(COMMENT);
    boardRead.next(board());
    expect(changed).not.toHaveBeenCalled();
    expect(api.moveCard).not.toHaveBeenCalled();
  });

  it('copies the link of the card, or says it could not', async () => {
    const { cmp, toast } = await setup();
    const writeText = jest.fn(() => Promise.resolve());
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    fireEvent.click(screen.getByRole('button', { name: 'Link kopieren' }));
    await Promise.resolve();
    expect(writeText).toHaveBeenCalledWith(`${location.origin}/todos/b-1?card=k-1`);
    expect(toast.success).toHaveBeenCalledWith('Link kopiert');
    writeText.mockReturnValueOnce(Promise.reject(new Error('denied')));
    cmp.copyLink();
    await new Promise((r) => setTimeout(r));
    expect(toast.error).toHaveBeenCalledWith('Der Link konnte nicht kopiert werden.');
    Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true });
    cmp.copyLink();
    expect(toast.error).toHaveBeenCalledTimes(2);
  });

  it('shows the files of a comment and sends new ones; a discard deletes the drafts', async () => {
    const { cmp, api, files } = await setup();
    expect(cmp.messages()[0].attachments).toEqual([
      {
        id: 'f1',
        filename: 'plan.pdf',
        mime: 'application/pdf',
        size: 20,
        scanState: 'quarantined',
        url: '/api/attachments/f1/download',
      },
    ]);
    api.addComment.mockReturnValueOnce(throwError(() => new Error('x')));
    cmp.sendComment({ body: '', attachmentIds: ['d1'], draftToken: 'tok' });
    expect(api.addComment).toHaveBeenLastCalledWith(
      'k-1',
      '',
      [],
      expect.objectContaining({ attachmentIds: ['d1'], draftToken: 'tok' }),
    );
    cmp.discardComment({ id: cmp.messages().find((m) => m.state === 'failed')!.id });
    expect(files.deleteDraftAttachment).toHaveBeenCalledWith('d1', 'tok');
  });

  it('posts, retries, edits and deletes comments, with mentions of members', async () => {
    const { cmp, api, toast, changed, commentsChanged } = await setup();
    cmp.sendComment({ body: 'Hallo @Jonas Weber' });
    expect(api.addComment).toHaveBeenCalledWith('k-1', 'Hallo @Jonas Weber', ['p-2'], { body: 'Hallo @Jonas Weber' });
    expect(cmp.card()?.comments.map((c) => c.id)).toEqual(['cm-1', 'cm-2']);
    expect(cmp.card()?.commentCount).toBe(1);
    // A comment write gives the page only the count, never the drawer's copy of the card.
    expect(commentsChanged).toHaveBeenLastCalledWith({ id: 'k-1', commentCount: 1 });

    api.addComment.mockReturnValueOnce(throwError(() => new Error('x')));
    cmp.sendComment({ body: 'Fehlt' });
    const failed = cmp.messages().find((m) => m.state === 'failed');
    expect(failed).toBeDefined();
    expect(toast.error).toHaveBeenLastCalledWith('Der Kommentar konnte nicht gespeichert werden.');
    cmp.retryComment({ id: failed!.id });
    api.addComment.mockReturnValueOnce(throwError(() => ({ status: 422, error: { errors: [{ field: 'body.body', msg: 'String should have at most 10000 characters' }] } })));
    cmp.sendComment({ body: 'Zu lang' });
    expect(toast.error).toHaveBeenLastCalledWith('Die Nachricht ist zu lang.');
    cmp.discardComment({ id: cmp.messages().find((m) => m.state === 'failed')!.id });
    expect(cmp.messages().some((m) => m.state === 'failed')).toBe(false);

    const sent = commentsChanged.mock.calls.length;
    cmp.editComment({ id: 'cm-1', body: 'Geändert' });
    expect(commentsChanged).toHaveBeenCalledTimes(sent + 1);
    expect(api.editComment).toHaveBeenCalledWith('k-1', 'cm-1', 'Geändert', []);
    expect(cmp.card()?.comments[0].body).toBe('Geändert');
    api.editComment.mockReturnValueOnce(throwError(() => new Error('x')));
    const restore = jest.fn();
    cmp.editComment({ id: 'cm-1', body: 'x', restore });
    expect(restore).toHaveBeenCalledTimes(1);
    expect(toast.error).toHaveBeenLastCalledWith('Der Kommentar konnte nicht gespeichert werden.');

    cmp.deleteComment({ id: 'cm-1' });
    // The same answer twice (a mocked server) joins the thread once.
    expect(cmp.card()?.comments.map((c) => c.id)).toEqual(['cm-2']);
    cmp.card.set({ ...cmp.card()!, commentCount: 0 });
    cmp.deleteComment({ id: 'cm-2' });
    expect(cmp.card()?.commentCount).toBe(0);
    api.deleteComment.mockReturnValueOnce(throwError(() => new Error('x')));
    cmp.deleteComment({ id: 'cm-2' });
    expect(toast.error).toHaveBeenCalledTimes(4);
    expect(commentsChanged).toHaveBeenLastCalledWith({ id: 'k-1', commentCount: 0 });
    expect(changed).not.toHaveBeenCalled();
  });

  it('writes the events with their time', async () => {
    const { cmp } = await setup({
      card: detail({
        events: [
          { id: 'e-1', kind: 'created', actor: { principalId: 'p-1', displayName: 'Selin' }, at: '2026-10-15T08:25:00Z', payload: {} },
          { id: 'e-2', kind: 'restored', actor: null, at: '2026-10-15T09:25:00Z', payload: {} },
        ],
        createdAt: 'bad',
      }),
    });
    expect(cmp.events()[0].text).toBe('Selin hat die Karte angelegt');
    expect(cmp.events()[1].text).toBe('STUPA hat die Karte wiederhergestellt');
    expect(cmp.createdLine()).toBe('Angelegt von Selin Yıldız · ');
    expect(cmp.name(null)).toBe('Gelöschte Person');
  });

  it('shows no archive date for a bad time and no relative day without a date', async () => {
    const { cmp } = await setup({ card: detail({ archivedAt: 'bad', dueDate: null }) });
    expect(cmp.archivedLine()).toBeNull();
    expect(cmp.dueRelative()).toBe('');
  });

  it('keeps the composer files when a breakpoint change re-creates the chat', async () => {
    let phone = false;
    const listeners: ((e: MediaQueryListEvent) => void)[] = [];
    jest.spyOn(window, 'matchMedia').mockImplementation(
      (query: string) =>
        ({
          get matches() {
            return query === MEDIA.phone && phone;
          },
          media: query,
          addEventListener: (_: string, fn: (e: MediaQueryListEvent) => void) => {
            if (query === MEDIA.phone) listeners.push(fn);
          },
          removeEventListener: () => undefined,
        }) as unknown as MediaQueryList,
    );
    const { fixture, files } = await setup();
    const chat = () => fixture.debugElement.query((d) => d.name === 'app-chat');
    const drafts = chat().injector.get(DraftAttachmentsService);
    const old = chat().componentInstance;
    const file = { id: 'd1', filename: 'a.png', mime: 'image/png', size: 3, scanned: false, isComparisonOffer: false, scanState: 'scanning' as const };
    drafts.files.set([file]);
    phone = true;
    for (const fn of [...listeners]) fn({ matches: true } as MediaQueryListEvent);
    fixture.detectChanges();
    expect(fixture.nativeElement).toHaveClass('cd--phone');
    expect(chat().componentInstance).not.toBe(old);
    expect(chat().injector.get(DraftAttachmentsService)).toBe(drafts);
    expect(drafts.files()).toEqual([file]);
    expect(files.deleteDraftAttachment).not.toHaveBeenCalled();
  });

  describe('live', () => {
    const wait = (detect: () => void) => {
      jest.advanceTimersByTime(300);
      detect();
    };
    beforeEach(() => jest.useFakeTimers({ doNotFake: ['queueMicrotask', 'setImmediate', 'nextTick'] }));
    afterEach(() => jest.useRealTimers());

    it('a ping of this card or its board reads it in the background and emits nothing', async () => {
      const { cmp, api, live, detect, changed } = await setup();
      expect(live.boards()).toEqual(['b-1']);
      api.card.mockClear();
      live.emit({ type: 'card', boardId: 'b-1', cardId: 'k-other' });
      wait(detect);
      expect(api.card).not.toHaveBeenCalled();
      api.card.mockReturnValueOnce(of(detail({ title: 'Raum gebucht', comments: [] })));
      live.emit({ type: 'card', boardId: 'b-1', cardId: 'k-1' });
      wait(detect);
      expect(cmp.card()?.title).toBe('Raum gebucht');
      expect(screen.getByText('Raum gebucht')).toBeInTheDocument();
      live.emit({ type: 'board', boardId: 'b-1' });
      wait(detect);
      expect(api.card).toHaveBeenCalledTimes(2);
      expect(changed).not.toHaveBeenCalled();
    });

    it('waits while a field is in edit and reads when the edit ends', async () => {
      const { cmp, api, live, detect } = await setup();
      api.card.mockClear();
      cmp.startTitle();
      live.emit({ type: 'card', boardId: 'b-1', cardId: 'k-1' });
      wait(detect);
      expect(api.card).not.toHaveBeenCalled();
      api.card.mockReturnValueOnce(of(detail({ title: 'Von drüben' })));
      cmp.editingTitle.set(false);
      detect();
      expect(api.card).toHaveBeenCalledTimes(1);
      expect(cmp.card()?.title).toBe('Von drüben');
    });

    it('drops a read that a local change overtook, and waits when an edit began meanwhile', async () => {
      const { cmp, api, live, detect } = await setup();
      const read = new Subject<TodoCardDetail>();
      api.card.mockReturnValueOnce(read);
      live.emit({ type: 'card', boardId: 'b-1', cardId: 'k-1' });
      wait(detect);
      cmp.addAssignee('p-2');
      read.next(detail({ title: 'Alt' }));
      expect(cmp.card()?.title).not.toBe('Alt');
      const again = new Subject<TodoCardDetail>();
      api.card.mockReturnValueOnce(again);
      live.emit({ type: 'card', boardId: 'b-1', cardId: 'k-1' });
      wait(detect);
      cmp.startAddItem();
      again.next(detail({ title: 'Später' }));
      expect(cmp.card()?.title).not.toBe('Später');
      api.card.mockReturnValueOnce(of(detail({ title: 'Später' })));
      cmp.addingItem.set(false);
      detect();
      expect(cmp.card()?.title).toBe('Später');
    });

    it('a 404 says the card is gone; another failure or a stale one changes nothing', async () => {
      const { cmp, api, live, detect } = await setup();
      api.card.mockReturnValueOnce(http(500));
      live.emit({ type: 'card', boardId: 'b-1', cardId: 'k-1' });
      wait(detect);
      expect(cmp.notFound()).toBe(false);
      const late = new Subject<TodoCardDetail>();
      api.card.mockReturnValueOnce(late);
      live.emit({ type: 'card_removed', boardId: 'b-1', cardId: 'k-1' });
      wait(detect);
      cmp.addAssignee('p-2');
      late.error(new HttpErrorResponse({ status: 404 }));
      expect(cmp.notFound()).toBe(false);
      api.card.mockReturnValueOnce(http(404));
      live.emit({ type: 'card_removed', boardId: 'b-1', cardId: 'k-1' });
      wait(detect);
      expect(cmp.notFound()).toBe(true);
      expect(cmp.card()).toBeNull();
      expect(live.boards()).toEqual([]);
    });
  });

  describe('phone', () => {
    beforeEach(() => asPhone(MEDIA.phone));

    it('draws the tabs without a count and the details while the card loads, with a working back link', async () => {
      const { cmp, api, detect, closed, fixture } = await setup();
      api.card.mockReturnValueOnce(new Subject<TodoCardDetail>());
      fixture.componentRef.setInput('cardId', 'k-2');
      detect();
      expect(cmp.busyTabs().map((t) => t.count)).toEqual([undefined, undefined]);
      expect(document.querySelector('.cd__skelTitle--second')).not.toBeNull();
      expect(document.querySelectorAll('.cd__panel .cd__item').length).toBe(3);
      fireEvent.click(screen.getByRole('button', { name: /Zum Board/ }));
      expect(closed).toHaveBeenCalled();
    });

    it('has the tabs Details and Aktivität, the back link and the bar', async () => {
      const { cmp, detect, closed, fixture } = await setup();
      expect(fixture.nativeElement).toHaveClass('cd--phone');
      const tabs = screen.getByRole('tablist');
      expect(within(tabs).getAllByRole('tab').map((t) => t.textContent?.replace(/\s+/g, ' ').trim())).toEqual([
        'Details',
        'Aktivität1',
      ]);
      expect(screen.queryByRole('button', { name: 'Link kopieren' })).toBeNull();
      fireEvent.click(screen.getByRole('button', { name: /Verschieben/ }));
      expect(cmp.moveOpen()).toBe(true);
      cmp.moveOpen.set(false);
      fireEvent.click(screen.getByRole('button', { name: /Erledigt/ }));
      cmp.selectTab('activity');
      detect();
      expect(screen.queryByRole('button', { name: /Verschieben/ })).toBeNull();
      cmp.selectTab('details');
      cmp.selectTab('odd');
      expect(cmp.tab()).toBe('details');
      fireEvent.click(screen.getByRole('button', { name: /Zum Board/ }));
      expect(closed).toHaveBeenCalled();
    });

    it('shows "Wieder öffnen" on a done card', async () => {
      await setup({ card: detail({ columnId: 'c-4' }) });
      expect(screen.getByRole('button', { name: /Wieder öffnen/ })).toBeInTheDocument();
    });
  });
});
