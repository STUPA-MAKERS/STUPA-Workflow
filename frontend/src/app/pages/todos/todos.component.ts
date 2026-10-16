import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  Injector,
  type OnDestroy,
  afterNextRender,
  computed,
  effect,
  inject,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';
import { filter, interval, map } from 'rxjs';
import type { Uuid } from '@core/api/models';
import {
  TodosApiService,
  type TodoBoard,
  type TodoBoardSummary,
  type TodoCardDetail,
  type TodoCardTile,
  type TodoLabel,
  type TodoMember,
} from '@core/api/todos.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { liveSearch } from '@shared/live-search';
import { EmptyStateComponent } from '@shared/ui/empty-state/empty-state.component';
import {
  FilterSelectComponent,
  type FilterSelectOption,
} from '@shared/ui/filter-select/filter-select.component';
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';
import { RowMenuComponent, type RowMenuItem, type RowMenuSection } from '@shared/ui/row-menu/row-menu.component';
import { SearchPillComponent } from '@shared/ui/search-pill/search-pill.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';
import { StickyBarComponent } from '@shared/ui/sticky-bar/sticky-bar.component';
import { ScrollFadeDirective } from '@shared/scroll-fade.directive';
import {
  ButtonComponent,
  IconComponent,
  MEDIA,
  SegmentedComponent,
  ToastService,
  type SegmentedOption,
} from '@stupa-makers/ui-kit';
import { TodoCardDetailComponent } from '../../features/todos/card-detail/todo-card-detail.component';
import { TodoNewDialogComponent } from '../../features/todos/new-dialog/todo-new-dialog.component';
import {
  NO_FILTER,
  applyMove,
  defaultBoard,
  filterActive,
  isoDay,
  matchesFilter,
  placeTile,
  removeTile,
  replaceTile,
  sortedColumns,
  type BoardFilter,
} from '../../features/todos/todos.util';
import { mediaQuerySignal } from '../../layout/media-query';
import { PageFrameService } from '../../layout/page-frame.service';
import { TodoArchiveSheetComponent } from './archive-sheet/todo-archive-sheet.component';
import { TodoBoardPickerComponent } from './board-picker/todo-board-picker.component';
import { TodoBoardSettingsComponent } from './board-settings/todo-board-settings.component';
import { TodoBoardViewComponent, type BoardMove } from './board-view/todo-board-view.component';
import { TodoListViewComponent } from './list-view/todo-list-view.component';

/** The board reads itself again this often while the tab is visible. */
export const BOARD_POLL_MS = 30_000;

type View = 'board' | 'list';

/** The text of the chip "Fällig" for each value. */
const DUE_TEXT: Record<BoardFilter['due'], TranslationKey> = {
  '': 'todos.filter.due',
  overdue: 'todos.filter.overdue',
  week: 'todos.filter.week',
  none: 'todos.filter.noDate',
};

/**
 * "To-Dos" (`/todos`, `/todos/:boardId`): one board of the person (frames 0–9, 11–14, 34).
 *
 * `/todos` opens the board of the first own Gremium, else the personal board. The header
 * holds "Board | Liste", the board settings (`todo.configure`) and "+ To-Do"; the bar
 * below the board picker, the search and the chips Zuständig, Label, Fällig. Filters run
 * in the browser over the cards of the board.
 *
 * `?card=<id>` opens the card in a drawer over the board (a deep link works the same).
 * `?view=list` shows the table. The board reads itself again every 30 seconds while the
 * tab is visible and when the window gets the focus; the ETag makes an unchanged board
 * a 304.
 */
@Component({
  selector: 'app-todos',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    TranslatePipe,
    ButtonComponent,
    EmptyStateComponent,
    FilterSelectComponent,
    IconComponent,
    PageHeaderComponent,
    RowMenuComponent,
    SearchPillComponent,
    SegmentedComponent,
    SkeletonComponent,
    StickyBarComponent,
    ScrollFadeDirective,
    TodoArchiveSheetComponent,
    TodoBoardPickerComponent,
    TodoBoardSettingsComponent,
    TodoBoardViewComponent,
    TodoCardDetailComponent,
    TodoListViewComponent,
    TodoNewDialogComponent,
  ],
  host: { '[class.pane-page]': '!phone()', class: 'todos-host' },
  templateUrl: './todos.component.html',
  styleUrl: './todos.component.scss',
})
export class TodosComponent implements OnDestroy {
  private readonly api = inject(TodosApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly frame = inject(PageFrameService);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly injector = inject(Injector);

  readonly phone = mediaQuerySignal(MEDIA.phone);

  private readonly params = toSignal(this.route.paramMap.pipe(map((p) => p.get('boardId'))), {
    initialValue: this.route.snapshot.paramMap.get('boardId'),
  });
  private readonly query = toSignal(this.route.queryParamMap, { initialValue: this.route.snapshot.queryParamMap });

  readonly boardId = computed(() => this.params());
  readonly cardId = computed(() => this.query().get('card'));
  readonly view = computed<View>(() => (this.query().get('view') === 'list' ? 'list' : 'board'));

  readonly boards = signal<TodoBoardSummary[]>([]);
  readonly board = signal<TodoBoard | null>(null);
  readonly loading = signal(true);
  readonly notFound = signal(false);
  readonly error = signal(false);
  readonly members = signal<TodoMember[]>([]);
  /** The ids of the open cards assigned to me (`GET /todos/mine`), for "Zuständig: Ich". */
  readonly mine = signal<ReadonlySet<Uuid>>(new Set());
  private etag: string | null = null;
  private loadSeq = 0;
  /** Counts the local changes of the board: a poll that left before one is dropped. */
  private mutations = 0;
  private mineLoaded = false;

  readonly filter = signal<BoardFilter>(NO_FILTER);
  readonly search = liveSearch<void>({
    minLength: 1,
    run: (q) => this.filter.update((f) => ({ ...f, q })),
    reset: () => this.filter.update((f) => ({ ...f, q: '' })),
  });
  /** Phone: the search field shows after the search button. */
  readonly searchOpen = signal(false);

  readonly newOpen = signal(false);
  readonly newColumn = signal<Uuid | null>(null);
  readonly settingsOpen = signal(false);
  readonly archiveOpen = signal(false);
  readonly today = signal(isoDay(new Date()));

  private readonly drawer = viewChild<ElementRef<HTMLElement>>('drawer');
  private focusedFor: Uuid | null = null;

  readonly viewOptions = computed<SegmentedOption[]>(() => [
    { value: 'board', label: this.i18n.translate('todos.view.board') },
    { value: 'list', label: this.i18n.translate('todos.view.list') },
  ]);

  readonly labelsById = computed<ReadonlyMap<Uuid, TodoLabel>>(
    () => new Map((this.board()?.labels ?? []).map((l) => [l.id, l])),
  );

  private readonly doneColumns = computed(
    () => new Set((this.board()?.columns ?? []).filter((c) => c.isDone).map((c) => c.id)),
  );

  readonly openCount = computed(() => {
    const done = this.doneColumns();
    return (this.board()?.cards ?? []).filter((c) => !done.has(c.columnId)).length;
  });

  /** The cards that pass the filters, by column. */
  readonly visible = computed<ReadonlyMap<Uuid, readonly TodoCardTile[]>>(() => {
    const board = this.board();
    const out = new Map<Uuid, TodoCardTile[]>();
    if (!board) return out;
    const f = this.filter();
    const ctx = { today: this.today(), mine: this.mine(), labels: this.labelsById() };
    for (const col of board.columns) out.set(col.id, []);
    for (const card of board.cards) {
      if (matchesFilter(card, f, ctx)) out.get(card.columnId)?.push(card);
    }
    return out;
  });

  readonly filtered = computed(() => filterActive(this.filter()));
  readonly noMatch = computed(() => {
    if (!this.filtered()) return false;
    for (const list of this.visible().values()) if (list.length) return false;
    return true;
  });

  readonly assigneeOptions = computed<FilterSelectOption[]>(() => [
    { value: '', label: this.i18n.translate('todos.filter.all') },
    { value: 'me', label: this.i18n.translate('todos.filter.me') },
    { value: 'none', label: this.i18n.translate('todos.filter.nobody') },
    ...this.members().map((m) => ({
      value: m.principalId,
      label: m.displayName ?? this.i18n.translate('chat.deletedPerson'),
    })),
  ]);
  readonly labelOptions = computed<FilterSelectOption[]>(() =>
    (this.board()?.labels ?? []).map((l) => ({ value: l.id, label: l.name })),
  );
  readonly dueOptions = computed<FilterSelectOption[]>(() => [
    { value: '', label: this.i18n.translate('todos.filter.all') },
    { value: 'overdue', label: this.i18n.translate('todos.filter.overdue') },
    { value: 'week', label: this.i18n.translate('todos.filter.week') },
    { value: 'none', label: this.i18n.translate('todos.filter.noDate') },
  ]);

  readonly assigneeText = computed(() => {
    const v = this.filter().assignee;
    if (!v) return this.i18n.translate('todos.filter.assignee');
    return this.assigneeOptions().find((o) => o.value === v)?.label ?? this.i18n.translate('todos.filter.assignee');
  });
  readonly labelText = computed(() => {
    const ids = this.filter().labels;
    if (!ids.length) return this.i18n.translate('todos.filter.label');
    if (ids.length === 1) return this.labelsById().get(ids[0])?.name ?? this.i18n.translate('todos.filter.label');
    return this.i18n.translate('todos.filter.labels', { n: ids.length });
  });
  readonly dueText = computed(() => this.i18n.translate(DUE_TEXT[this.filter().due]));

  readonly phoneMenu = computed<RowMenuSection[]>(() => {
    const items: RowMenuItem[] = [
      this.view() === 'board'
        ? { id: 'list', label: this.i18n.translate('todos.view.showList'), icon: 'list' }
        : { id: 'board', label: this.i18n.translate('todos.view.showBoard'), icon: 'kanban' },
    ];
    if (this.board()?.canConfigure) {
      items.push({ id: 'settings', label: this.i18n.translate('todos.settings.title'), icon: 'tune' });
    }
    if (this.board()?.archivedCount) {
      items.push({ id: 'archive', label: this.i18n.translate('todos.archive.title'), icon: 'archive' });
    }
    return [{ items }];
  });

  constructor() {
    this.api.boards().subscribe({
      next: (boards) => {
        this.boards.set(boards);
        if (!this.boardId()) this.openDefault(boards);
      },
      error: () => {
        if (!this.boardId()) {
          this.loading.set(false);
          this.error.set(true);
        }
      },
    });

    // A board in the route: read it (and its people) when it changes.
    effect(() => {
      const id = this.boardId();
      if (!id) return;
      untracked(() => this.loadBoard(id));
    });

    // The drawer takes the focus once when it opens for a card.
    effect(() => {
      const id = this.cardId();
      const el = this.drawer();
      if (!id) {
        this.focusedFor = null;
        return;
      }
      if (el && this.focusedFor !== id) {
        this.focusedFor = id;
        el.nativeElement.focus();
      }
    });

    // Side by side the page fills the viewport and only the columns scroll.
    effect(() => this.frame.fill.set(!this.phone()));

    // Poll every 30 s while the tab is visible, and on the focus of the window.
    interval(BOARD_POLL_MS)
      .pipe(
        filter(() => typeof document === 'undefined' || document.visibilityState !== 'hidden'),
        takeUntilDestroyed(),
      )
      .subscribe(() => this.poll());
    const onFocus = () => this.poll();
    window.addEventListener('focus', onFocus);
    inject(DestroyRef).onDestroy(() => window.removeEventListener('focus', onFocus));
  }

  ngOnDestroy(): void {
    this.frame.fill.set(false);
  }

  private openDefault(boards: readonly TodoBoardSummary[]): void {
    const pick = defaultBoard(boards);
    if (!pick) {
      this.loading.set(false);
      this.notFound.set(true);
      return;
    }
    void this.router.navigate(['/todos', pick.id], {
      replaceUrl: true,
      queryParamsHandling: 'preserve',
    });
  }

  private loadBoard(id: Uuid): void {
    const seq = ++this.loadSeq;
    this.loading.set(true);
    this.notFound.set(false);
    this.error.set(false);
    this.board.set(null);
    this.etag = null;
    this.filter.set(NO_FILTER);
    this.search.sync('');
    this.api.pollBoard(id, null).subscribe({
      next: ({ board, etag }) => {
        if (seq !== this.loadSeq) return;
        this.board.set(board);
        this.etag = etag;
        this.loading.set(false);
      },
      error: (err: unknown) => {
        if (seq !== this.loadSeq) return;
        this.loading.set(false);
        if (err instanceof HttpErrorResponse && err.status === 404) this.notFound.set(true);
        else this.error.set(true);
      },
    });
    this.members.set([]);
    this.api.members(id).subscribe({
      next: (list) => {
        if (seq === this.loadSeq) this.members.set(list);
      },
      error: () => undefined,
    });
  }

  /** Read the board again; a 304 keeps it. */
  poll(): void {
    const board = this.board();
    if (!board) return;
    const seq = this.loadSeq;
    const muts = this.mutations;
    this.today.set(isoDay(new Date()));
    this.api.pollBoard(board.id, this.etag).subscribe({
      next: (res) => {
        if (seq !== this.loadSeq || muts !== this.mutations || !res.board) return;
        this.board.set(res.board);
        this.etag = res.etag;
      },
      error: () => undefined,
    });
  }

  /**
   * Read the board again without an ETag after a refused change. Unlike `loadBoard` it
   * keeps the board on screen, the filters and the search.
   */
  private resync(id: Uuid): void {
    const seq = this.loadSeq;
    this.mutations++;
    this.api.pollBoard(id, null).subscribe({
      next: ({ board, etag }) => {
        if (seq !== this.loadSeq || !board) return;
        this.board.set(board);
        this.etag = etag;
      },
      error: () => undefined,
    });
  }

  private loadMine(): void {
    if (this.mineLoaded) return;
    this.mineLoaded = true;
    this.api.mine().subscribe({
      next: (m) => this.mine.set(new Set(m.items.map((i) => i.id))),
      error: () => {
        this.mineLoaded = false;
      },
    });
  }

  // ------------------------------------------------------------------ header

  pickBoard(id: Uuid): void {
    void this.router.navigate(['/todos', id], { queryParams: { view: this.view() === 'list' ? 'list' : null } });
  }

  setView(value: string | null): void {
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { view: value === 'list' ? 'list' : null },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }

  onPhoneMenu(item: RowMenuItem): void {
    if (item.id === 'list' || item.id === 'board') this.setView(item.id);
    else if (item.id === 'settings') this.settingsOpen.set(true);
    else if (item.id === 'archive') this.archiveOpen.set(true);
  }

  newCard(columnId: Uuid | null = null): void {
    this.newColumn.set(columnId);
    this.newOpen.set(true);
  }

  // ------------------------------------------------------------------ filters

  setAssignee(value: string): void {
    if (value === 'me') this.loadMine();
    this.filter.update((f) => ({ ...f, assignee: value }));
  }

  setLabels(values: readonly string[]): void {
    this.filter.update((f) => ({ ...f, labels: values }));
  }

  setDue(value: string): void {
    const due = (['overdue', 'week', 'none'] as const).find((d) => d === value) ?? '';
    this.filter.update((f) => ({ ...f, due }));
  }

  resetFilters(): void {
    this.search.clear();
    this.filter.set(NO_FILTER);
  }

  // ------------------------------------------------------------------ cards

  openCard(id: Uuid): void {
    void this.router.navigate([], { relativeTo: this.route, queryParams: { card: id }, queryParamsHandling: 'merge' });
  }

  closeCard(): void {
    const id = this.cardId();
    void this.router.navigate([], { relativeTo: this.route, queryParams: { card: null }, queryParamsHandling: 'merge' });
    if (id) {
      afterNextRender(
        () => this.host.nativeElement.querySelector<HTMLElement>(`[data-card-id="${id}"]`)?.focus(),
        { injector: this.injector },
      );
    }
  }

  onDrawerKey(event: KeyboardEvent): void {
    // A dialog or sheet inside the drawer (the delete question of the chat) handles its own keys.
    if ((event.target as Element).closest('[role="dialog"]') !== event.currentTarget) return;
    if (event.key === 'Escape' && !event.defaultPrevented) {
      event.preventDefault();
      this.closeCard();
      return;
    }
    if (event.key !== 'Tab') return;
    const root = event.currentTarget as HTMLElement;
    const items = Array.from(
      root.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'),
    ).filter((el) => el.offsetParent !== null || el === document.activeElement);
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  moveCard(event: BoardMove): void {
    const board = this.board();
    if (!board) return;
    const optimistic = applyMove(board, event.cardId, event.move);
    this.mutations++;
    this.board.set(optimistic);
    this.api.moveCard(event.cardId, event.move).subscribe({
      next: (tile) => {
        this.mutations++;
        const now = this.board();
        if (now) this.board.set(replaceTile(now, tile));
      },
      error: () => {
        this.toast.error(this.i18n.translate('todos.error.move'));
        // Roll back when nothing else changed the board meanwhile, then read it again.
        if (this.board() === optimistic) this.board.set(board);
        this.resync(board.id);
      },
    });
  }

  /** The list view: the circle moves a card to the done column, or back to the first. */
  toggleDone(card: TodoCardTile): void {
    const board = this.board();
    if (!board) return;
    const cols = sortedColumns(board.columns);
    const done = this.doneColumns().has(card.columnId);
    const target = done ? cols.find((c) => !c.isDone) : cols.find((c) => c.isDone);
    if (target) this.moveCard({ cardId: card.id, move: { columnId: target.id } });
  }

  quickAdd(event: { columnId: Uuid; title: string }): void {
    const board = this.board();
    if (!board) return;
    this.mutations++;
    this.api.createCard({ boardId: board.id, columnId: event.columnId, title: event.title }).subscribe({
      next: (card) => this.onCreated(card),
      error: () => this.toast.error(this.i18n.translate('todos.error.create')),
    });
  }

  onCreated(card: TodoCardDetail): void {
    const board = this.board();
    if (!board || card.boardId !== board.id) return;
    this.mutations++;
    this.board.set(replaceTile(board, card));
  }

  onCardChanged(card: TodoCardDetail): void {
    const board = this.board();
    if (!board || card.boardId !== board.id) return;
    this.mutations++;
    this.board.set(card.archivedAt ? removeTile(board, card.id) : placeTile(board, card));
  }

  onArchived(id: Uuid): void {
    const board = this.board();
    this.mutations++;
    if (board) this.board.set({ ...removeTile(board, id), archivedCount: board.archivedCount + 1 });
    this.closeCard();
  }

  onRestored(card: TodoCardDetail): void {
    const board = this.board();
    if (!board || card.boardId !== board.id) return;
    this.mutations++;
    this.board.set({ ...replaceTile(board, card), archivedCount: Math.max(0, board.archivedCount - 1) });
  }

  onSettingsChanged(board: TodoBoard): void {
    this.mutations++;
    this.board.set(board);
    this.boards.update((list) => list.map((b) => (b.id === board.id ? { ...b, name: board.name } : b)));
  }

  reload(): void {
    const id = this.boardId();
    if (id) this.loadBoard(id);
  }
}
