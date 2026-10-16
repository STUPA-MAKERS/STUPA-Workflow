import { CdkScrollable } from '@angular/cdk/scrolling';
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
import { AuthService } from '@core/auth/auth.service';
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
  insertTile,
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
import { TodoBoardRowsComponent, type RowDrop } from './board-rows/todo-board-rows.component';
import { TodoBoardSettingsComponent } from './board-settings/todo-board-settings.component';
import { TodoBoardSkeletonComponent } from './board-skeleton/todo-board-skeleton.component';
import { TodoBoardViewComponent, boardDropId, type BoardMove } from './board-view/todo-board-view.component';
import { TodoListViewComponent } from './list-view/todo-list-view.component';

/** The board reads itself again this often while the tab is visible. */
export const BOARD_POLL_MS = 30_000;

/** The route segment of the meta-board "Alle" (`/todos/alle`): every readable board at once. */
export const ALL_BOARDS = 'alle';

type View = 'board' | 'list';

/** The text of the chip "Fällig" for each value. */
const DUE_TEXT: Record<BoardFilter['due'], TranslationKey> = {
  '': 'todos.filter.due',
  overdue: 'todos.filter.overdue',
  week: 'todos.filter.week',
  none: 'todos.filter.noDate',
};

/**
 * "Boards" (`/todos`, `/todos/:boardId`): one board of the person (frames 0–9, 11–14, 34).
 *
 * `/todos` opens the personal board "Meine To-Dos", else the board of the first own Gremium;
 * a board in the URL wins. The header holds "Board | Liste" and, at its end, the board
 * settings (`todo.configure`); "+ To-Do" is the floating button at the bottom right on
 * every width. The bar below holds the board picker, the search and the chips Zuständig,
 * Label, Fällig. Filters run in the browser over the cards of the board.
 *
 * `/todos/alle` is the meta-board "Alle": no board of its own, but the rows of every
 * readable board with all their cards (`app-todo-board-rows`, `source="all"`), the same
 * filters and search, no view switch, no settings and no archive; "+ To-Do" starts on the
 * personal board. Under "Meine To-Dos" and in "Alle" a pointer drag moves a card between
 * boards (`transferCard`); the page carries the drags between the personal board and the
 * rows below it.
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
    CdkScrollable,
    TranslatePipe,
    ButtonComponent,
    EmptyStateComponent,
    FilterSelectComponent,
    IconComponent,
    PageHeaderComponent,
    RowMenuComponent,
    SearchPillComponent,
    SegmentedComponent,
    StickyBarComponent,
    ScrollFadeDirective,
    TodoArchiveSheetComponent,
    TodoBoardPickerComponent,
    TodoBoardRowsComponent,
    TodoBoardSkeletonComponent,
    TodoBoardSettingsComponent,
    TodoBoardViewComponent,
    TodoCardDetailComponent,
    TodoListViewComponent,
    TodoNewDialogComponent,
  ],
  // On a phone the board fills the free height too, so its column pages scroll inside;
  // the list scrolls as a page.
  host: { '[class.pane-page]': "!phone() || view() === 'board'", class: 'todos-host' },
  templateUrl: './todos.component.html',
  styleUrl: './todos.component.scss',
})
export class TodosComponent implements OnDestroy {
  private readonly api = inject(TodosApiService);
  private readonly auth = inject(AuthService);
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

  readonly allId = ALL_BOARDS;
  readonly boardId = computed(() => this.params());
  /** The meta-board "Alle" is shown. */
  readonly all = computed(() => this.boardId() === ALL_BOARDS);
  readonly cardId = computed(() => this.query().get('card'));
  /** "Alle" has rows only, so it is always the board view. */
  readonly view = computed<View>(() => (!this.all() && this.query().get('view') === 'list' ? 'list' : 'board'));

  readonly boards = signal<TodoBoardSummary[]>([]);
  readonly board = signal<TodoBoard | null>(null);
  readonly loading = signal(true);
  readonly notFound = signal(false);
  readonly error = signal(false);
  readonly members = signal<TodoMember[]>([]);
  /** The ids of the open cards assigned to me (`GET /todos/mine`), for "Zuständig: Ich". */
  readonly mine = signal<ReadonlySet<Uuid>>(new Set());
  /** "Alle": my principal id (the one member of my personal board), for "Zuständig: Ich". */
  readonly meId = signal<Uuid | null>(null);
  private etag: string | null = null;
  private loadSeq = 0;
  /** Counts the local changes of the board: a poll that left before one is dropped. */
  private mutations = 0;
  private mineLoaded = false;
  private mineSeq = 0;

  readonly filter = signal<BoardFilter>(NO_FILTER);
  readonly search = liveSearch<void>({
    minLength: 1,
    run: (q) => this.filter.update((f) => ({ ...f, q })),
    reset: () => this.filter.update((f) => ({ ...f, q: '' })),
  });
  /** Phone: the search field shows after the search button. */
  readonly searchOpen = signal(false);
  /** Phone: the filter chips show after the filter chip. */
  readonly filtersOpen = signal(false);

  readonly newOpen = signal(false);
  readonly newColumn = signal<Uuid | null>(null);
  readonly settingsOpen = signal(false);
  readonly archiveOpen = signal(false);
  readonly today = signal(isoDay(new Date()));

  private readonly drawer = viewChild<ElementRef<HTMLElement>>('drawer');
  /** The rows of the other boards under "Meine To-Dos" (board view only). */
  private readonly rowsView = viewChild(TodoBoardRowsComponent);
  /** The cards the rows show after the filters; null until the rows of this board answered. */
  readonly rowMatches = signal<number | null>(null);
  readonly withRows = computed(() => this.board()?.kind === 'personal' && this.view() === 'board');
  /**
   * The rows held cards at their last answer. Until the rows answer, the board and its
   * skeleton keep that shape, so the board does not resize when the rows land.
   */
  private readonly rowsExpected = signal(true);
  /** Rows of other boards follow under the board: the board takes its natural height. */
  readonly rowsBelow = computed(() => {
    if (!this.withRows()) return false;
    const n = this.rowMatches();
    return n === null ? this.rowsExpected() : n > 0;
  });
  /** The shape of each board the page has shown: the skeleton draws it on a return. */
  private readonly shapes = signal<ReadonlyMap<Uuid, { columns: number; labels: boolean }>>(new Map());
  /** The shape of the loading board: known from an earlier visit, else a new board. */
  readonly skeleton = computed(() => {
    const id = this.boardId();
    const known = id ? this.shapes().get(id) : undefined;
    const personal = this.summary()?.kind === 'personal';
    return {
      columns: known?.columns ?? 4,
      // A new personal board has no labels, so its chip row has no label chip.
      labels: known?.labels ?? !personal,
      natural: personal && this.view() === 'board' && this.rowsExpected(),
    };
  });
  private focusedFor: Uuid | null = null;

  readonly viewOptions = computed<SegmentedOption[]>(() => [
    { value: 'board', label: this.i18n.translate('todos.view.board') },
    { value: 'list', label: this.i18n.translate('todos.view.list') },
  ]);

  /**
   * The labels of the label filter by id. "Alle": the labels of every row, one per name
   * (labels are per board; the rows match them by name), by name.
   */
  readonly labelsById = computed<ReadonlyMap<Uuid, TodoLabel>>(() => {
    if (!this.all()) return new Map((this.board()?.labels ?? []).map((l) => [l.id, l]));
    const byName = new Map<string, TodoLabel>();
    for (const b of this.rowsView()?.boards() ?? []) {
      for (const l of b.labels) if (!byName.has(l.name.toLowerCase())) byName.set(l.name.toLowerCase(), l);
    }
    const sorted = [...byName.values()].sort((a, b) => a.name.localeCompare(b.name, 'de', { sensitivity: 'base' }));
    return new Map(sorted.map((l) => [l.id, l]));
  });

  /** The personal board in the board list ("+ To-Do" of "Alle" starts there). */
  readonly personalId = computed(() => this.boards().find((b) => b.kind === 'personal')?.id ?? null);
  /** "+ To-Do" shows: a writable board, or "Alle". */
  readonly canAdd = computed(() => this.all() || !!this.board()?.canWrite);
  /** The drop lists of the personal board that the rows below it connect to. */
  readonly boardDrops = computed(() => {
    const b = this.board();
    if (!b?.canWrite || !this.withRows() || this.phone()) return [];
    return sortedColumns(b.columns).map((c) => boardDropId(c.id));
  });
  /** The drop lists of the rows below the personal board (their `drops` output). */
  readonly rowDrops = signal<string[]>([]);

  private readonly doneColumns = computed(
    () => new Set((this.board()?.columns ?? []).filter((c) => c.isDone).map((c) => c.id)),
  );

  /** The entry of the shown board in the board list: known before the board loads. */
  readonly summary = computed(() => this.boards().find((b) => b.id === this.boardId()) ?? null);

  readonly openCount = computed(() => {
    if (this.all()) return this.rowsView()?.openCount() ?? 0;
    const board = this.board();
    // While the board loads, the list already knows its count, so the search does not
    // say "0 offene To-Dos".
    if (!board) return this.summary()?.openCount ?? 0;
    const done = this.doneColumns();
    return board.cards.filter((c) => !done.has(c.columnId)).length;
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
    if (this.all()) return this.rowMatches() === 0;
    if (this.withRows() && (this.rowMatches() ?? 0) > 0) return false;
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
  /** "Alle" without a single card: the empty state instead of the rows. */
  readonly allEmpty = computed(() => this.all() && !this.filtered() && this.rowMatches() === 0);
  readonly labelOptions = computed<FilterSelectOption[]>(() =>
    [...this.labelsById().values()].map((l) => ({ value: l.id, label: l.name })),
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

    // A board in the route: read it (and its people) when it changes. "Alle" has no
    // board: its rows read themselves.
    effect(() => {
      const id = this.boardId();
      if (!id) return;
      untracked(() => (id === ALL_BOARDS ? this.enterAll() : this.loadBoard(id)));
    });

    // "Alle": my principal id is the one member of my personal board.
    effect(() => {
      const id = this.all() ? this.personalId() : null;
      if (!id) return;
      untracked(() => this.loadMe(id));
    });

    // Remember the shape of each shown board for its skeleton on a return.
    effect(() => {
      const b = this.board();
      if (!b) return;
      const shape = { columns: b.columns.length, labels: b.labels.length > 0 };
      untracked(() => {
        const known = this.shapes().get(b.id);
        if (known?.columns === shape.columns && known.labels === shape.labels) return;
        this.shapes.update((m) => new Map(m).set(b.id, shape));
      });
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

  /** The rows answered with the number of cards they show. */
  onRowMatches(n: number): void {
    this.rowMatches.set(n);
    this.rowsExpected.set(n > 0);
  }

  private openDefault(boards: readonly TodoBoardSummary[]): void {
    const pick = defaultBoard(
      boards,
      this.auth.gremien().map((g) => g.id),
    );
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
    this.rowMatches.set(null);
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

  /** "Alle": no board, the rows (and their first read) start from a clean state. */
  private enterAll(): void {
    this.loadSeq++;
    this.loading.set(false);
    this.notFound.set(false);
    this.error.set(false);
    this.board.set(null);
    this.etag = null;
    this.rowMatches.set(null);
    this.filter.set(NO_FILTER);
    this.search.sync('');
    this.members.set([]);
  }

  private loadMe(personalId: Uuid): void {
    if (this.meId()) return;
    this.api.members(personalId).subscribe({
      next: (list) => this.meId.set(list[0]?.principalId ?? null),
      error: () => undefined,
    });
  }

  /** Read the board again; a 304 keeps it. */
  poll(): void {
    if (this.all()) {
      this.today.set(isoDay(new Date()));
      this.rowsView()?.poll();
      return;
    }
    const board = this.board();
    if (!board) return;
    this.rowsView()?.poll();
    const seq = this.loadSeq;
    const muts = this.mutations;
    this.today.set(isoDay(new Date()));
    this.api.pollBoard(board.id, this.etag).subscribe({
      next: (res) => {
        if (seq !== this.loadSeq || muts !== this.mutations || !res.board) return;
        this.board.set(res.board);
        this.etag = res.etag;
        this.refreshMine();
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
        this.refreshMine();
      },
      error: () => undefined,
    });
  }

  private loadMine(): void {
    if (this.mineLoaded) return;
    this.mineLoaded = true;
    const seq = ++this.mineSeq;
    this.api.mine().subscribe({
      next: (m) => {
        if (seq !== this.mineSeq) return;
        // `/todos/mine` lists open cards only: a card of mine in a done column stays mine.
        const done = this.doneColumns();
        const prev = this.mine();
        const kept = (this.board()?.cards ?? [])
          .filter((c) => prev.has(c.id) && done.has(c.columnId) && c.assignees.length)
          .map((c) => c.id);
        this.mine.set(new Set([...m.items.map((i) => i.id), ...kept]));
      },
      error: () => {
        if (seq === this.mineSeq) this.mineLoaded = false;
      },
    });
  }

  /** The assignees of a card changed or may have: read "mine" again, now or at the next pick of "Ich". */
  /** Read the board summaries again (the open counts of the picker). */
  private refreshBoards(): void {
    this.api.boards().subscribe({
      next: (boards) => this.boards.set(boards),
      error: () => undefined,
    });
  }

  private refreshMine(): void {
    this.mineLoaded = false;
    if (this.filter().assignee === 'me') this.loadMine();
  }

  // ------------------------------------------------------------------ header

  pickBoard(id: Uuid): void {
    const list = id !== ALL_BOARDS && this.view() === 'list';
    void this.router.navigate(['/todos', id], { queryParams: { view: list ? 'list' : null } });
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
    // "Alle" knows the assignees of every card: "Ich" needs no `/todos/mine`.
    if (value === 'me' && !this.all()) this.loadMine();
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
    if (!items.length) {
      event.preventDefault();
      return;
    }
    const first = items[0];
    const last = items[items.length - 1];
    // The drawer itself holds the focus after the open and is not in `items`: a Tab from
    // there (or from any element outside the list) wraps like one from an edge.
    const active = document.activeElement as HTMLElement | null;
    const outside = !active || !items.includes(active);
    if (event.shiftKey && (outside || active === first)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && (outside || active === last)) {
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
    if (this.all()) {
      this.rowsView()?.cardChanged(card);
      return;
    }
    const board = this.board();
    if (!board || card.boardId !== board.id) return;
    this.mutations++;
    this.board.set(replaceTile(board, card));
    this.refreshMine();
  }

  /**
   * The drawer moved the card to another board (it says so before `changed`): the tile
   * leaves the shown board when the card came from it, and joins it when the card came
   * over to it. The drawer stays on the card.
   */
  onTransferred(event: { card: TodoCardDetail; fromBoardId: Uuid }): void {
    const board = this.board();
    if (!board) return;
    const { card } = event;
    const held = board.cards.some((c) => c.id === card.id);
    if (event.fromBoardId === board.id && held) {
      this.mutations++;
      this.board.set(removeTile(board, card.id));
      this.refreshMine();
      this.refreshBoards();
    } else if (card.boardId === board.id && !held) {
      this.mutations++;
      this.board.set(placeTile(board, card));
      this.refreshBoards();
    }
  }

  onCardChanged(card: TodoCardDetail): void {
    this.rowsView()?.cardChanged(card);
    const board = this.board();
    // A card of another board (a row, or one that left with a transfer) is not on this board.
    if (!board || card.boardId !== board.id) return;
    const held = board.cards.some((c) => c.id === card.id);
    this.mutations++;
    if (card.archivedAt) {
      this.board.set(removeTile(board, card.id));
    } else if (held) {
      this.board.set(placeTile(board, card));
    } else {
      // A card the board does not hold came back from the archive (the drawer's restore).
      this.board.set({ ...placeTile(board, card), archivedCount: Math.max(0, board.archivedCount - 1) });
    }
    this.refreshMine();
  }

  /** Merge only the comment count: the drawer's copy of the rest of the card can be stale. */
  onCommentsChanged(event: { id: Uuid; commentCount: number }): void {
    this.rowsView()?.commentsChanged(event);
    const board = this.board();
    if (!board?.cards.some((c) => c.id === event.id)) return;
    this.mutations++;
    this.board.set({
      ...board,
      cards: board.cards.map((c) => (c.id === event.id ? { ...c, commentCount: event.commentCount } : c)),
    });
  }

  onArchived(id: Uuid): void {
    this.rowsView()?.cardRemoved(id);
    const board = this.board();
    this.mutations++;
    // A card of a row lives on another board: the archive count of this one stays.
    if (board?.cards.some((c) => c.id === id)) {
      this.board.set({ ...removeTile(board, id), archivedCount: board.archivedCount + 1 });
    }
    this.closeCard();
  }

  onRestored(card: TodoCardDetail): void {
    const board = this.board();
    if (!board || card.boardId !== board.id) return;
    this.mutations++;
    this.board.set({ ...placeTile(board, card), archivedCount: Math.max(0, board.archivedCount - 1) });
  }

  /** A drag in the rows moved a card between two of their boards: the open counts change. */
  onRowTransferred(): void {
    this.refreshBoards();
  }

  /**
   * A card of the personal board landed in a row below it: it moves at once, and back with
   * a toast when the server refuses. It stays in that row (it is still mine) until the
   * rows read themselves again.
   */
  onDropIntoRow(event: RowDrop): void {
    const board = this.board();
    const rows = this.rowsView();
    const tile = board?.cards.find((c) => c.id === event.cardId);
    if (!board || !rows || !tile) return;
    const optimistic = removeTile(board, tile.id);
    this.mutations++;
    this.board.set(optimistic);
    rows.receive(tile, event.boardId, event.move);
    this.api.transferCard(tile.id, { boardId: event.boardId, ...event.move }).subscribe({
      next: (card) => {
        this.rowsView()?.accept(card);
        this.refreshBoards();
        this.refreshMine();
      },
      error: () => this.transferFailed(board, optimistic),
    });
  }

  /** A card of a row landed on the personal board above: it moves at once, as above. */
  onDropFromRow(event: BoardMove): void {
    const board = this.board();
    const tile = board?.canWrite ? this.rowsView()?.take(event.cardId) : null;
    if (!board || !tile) return;
    const optimistic = insertTile(board, tile, event.move);
    this.mutations++;
    this.board.set(optimistic);
    this.api.transferCard(tile.id, { boardId: board.id, ...event.move }).subscribe({
      next: (card) => {
        const now = this.board();
        if (now?.id === board.id) {
          this.mutations++;
          this.board.set(replaceTile(now, card));
        }
        this.refreshBoards();
        this.refreshMine();
      },
      error: () => this.transferFailed(board, optimistic),
    });
  }

  /** Roll a refused drag between the board and the rows back, then read both again. */
  private transferFailed(board: TodoBoard, optimistic: TodoBoard): void {
    this.toast.error(this.i18n.translate('todos.error.transfer'));
    if (this.board() === optimistic) this.board.set(board);
    this.resync(board.id);
    this.rowsView()?.refresh();
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
