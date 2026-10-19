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
import { Subject, filter, finalize, interval, map, merge, type Observable } from 'rxjs';
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
import { TodoLiveService, batchPings } from '@core/ws/todo-live.service';
import type { TodoPing } from '@core/ws/ws-messages';
import { FabComponent } from '@shared/ui/fab/fab.component';
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';
import {
  ButtonComponent,
  EmptyStateComponent,
  FilterSelectComponent,
  type FilterSelectOption,
  focusableIn,
  IconComponent,
  liveSearch,
  MEDIA,
  mediaQuery,
  NoteComponent,
  RowMenuComponent,
  type RowMenuItem,
  type RowMenuSection,
  ScrollFadeDirective,
  SearchPillComponent,
  SegmentedComponent,
  type SegmentedOption,
  StickyBarComponent,
  ToastService,
  trapTab,
} from '@stupa-makers/ui-kit';
import { TodoCardDetailComponent } from '../../features/todos/card-detail/todo-card-detail.component';
import { TodoNewDialogComponent } from '../../features/todos/new-dialog/todo-new-dialog.component';
import { TodoCacheService } from '../../features/todos/todo-cache.service';
import { TodoTileMenuComponent, type TileMenuRequest } from '../../features/todos/tile-menu/todo-tile-menu.component';
import {
  TodoTransferDialogComponent,
  type TodoTransferTarget,
} from '../../features/todos/transfer-dialog/todo-transfer-dialog.component';
import {
  NO_FILTER,
  applyMove,
  defaultBoard,
  filterActive,
  insertTile,
  matchesFilter,
  moveErrorText,
  placeTile,
  removeTile,
  replaceTile,
  sortedColumns,
  type BoardFilter,
} from '../../features/todos/todos.util';
import { PageFrameService } from '../../layout/page-frame.service';
import { TodoArchiveSheetComponent } from './archive-sheet/todo-archive-sheet.component';
import { TodoBoardPickerComponent } from './board-picker/todo-board-picker.component';
import { TodoBoardRowsComponent, type RowDrop, type RowLead } from './board-rows/todo-board-rows.component';
import { TodoBoardSettingsComponent } from './board-settings/todo-board-settings.component';
import { TodoBoardSkeletonComponent } from './board-skeleton/todo-board-skeleton.component';
import { TodoBoardViewComponent, boardDropId, type BoardMove } from './board-view/todo-board-view.component';
import { TodoListViewComponent } from './list-view/todo-list-view.component';
import { isoDay } from '@shared/date-format';

/** The board reads itself again this often while the tab is visible. */
export const BOARD_POLL_MS = 30_000;
/** While the live socket holds the boards, only every this many poll ticks reads (120 s). */
export const LIVE_POLL_EVERY = 4;

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
 * Phone: "Meine To-Dos" (board view) and "Alle" are one list of board sections
 * (`app-todo-board-rows`); the personal board is the first section (`lead`), not the tab
 * board. Nothing drags there. A long press on a tile of a writable board, on these lists
 * and on the tab board, opens the "Verschieben" sheet (`app-todo-tile-menu`): a column
 * moves the card to its end as a drag does, "In anderes Board verschieben" opens the
 * transfer dialog.
 *
 * `?card=<id>` opens the card in a drawer over the board (a deep link works the same).
 * A shared link names the card only (`/todos?card=<id>`): the page reads the card and opens
 * its board, so the link stays valid when the card moves to another board. An older link
 * with a board (`/todos/<board>?card=<id>`) whose card is on another board now opens the
 * card's board too; only the personal board and "Alle" keep a card of another board, because
 * their rows show it.
 * `?view=list` shows the table. The board reads itself again every 30 seconds while the
 * tab is visible and when the window gets the focus; the ETag makes an unchanged board
 * a 304.
 *
 * Live (`TodoLiveService`): the shown board takes the pings of other people's changes. A
 * `card` ping reads that tile (`GET /todos/cards/{id}/tile`) and puts it in place, or takes
 * it out when it is on another board now or answers 404; `card_removed` takes the tile out;
 * `board` is the ETag read of the board. The rows below the board and "Alle" take their
 * own pings. While a card is held or a move of the page is in flight, the pings wait.
 * While the socket is up, the poll reads every 120 seconds instead of 30.
 */
@Component({
  selector: 'app-todos',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    NoteComponent,
    CdkScrollable,
    TranslatePipe,
    ButtonComponent,
    EmptyStateComponent,
    FabComponent,
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
    TodoTileMenuComponent,
    TodoTransferDialogComponent,
  ],
  // On a phone the board fills the free height too, so its column pages scroll inside;
  // the list scrolls as a page.
  host: { '[class.pane-page]': "!phone() || view() === 'board'", class: 'todos-host' },
  providers: [TodoCacheService],
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
  private readonly live = inject(TodoLiveService);
  private readonly cache = inject(TodoCacheService);

  readonly phone = mediaQuery(MEDIA.phone);

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
  private readonly boardsRead = signal(false);
  /** The card of the entry URL whose board is still to check; null once checked. */
  private readonly entryCard = signal<Uuid | null>(this.boardId() ? this.cardId() : null);
  /** A card-only link (`/todos?card=`) whose card did not read: open the default board. */
  private readonly cardUnresolved = signal(false);
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
  /** Counts every change of the board, live tiles too: a poll that left before one is dropped. */
  private mutations = 0;
  /**
   * Counts my own writes and the tiles taken off: a tile read that left before one is
   * dropped. A live tile does not count, else a burst of k pings reads ~k² tiles.
   */
  private localWrites = 0;
  private mineLoaded = false;
  private mineSeq = 0;
  /** The poll ticks; while the socket is up only every `LIVE_POLL_EVERY`-th reads. */
  private ticks = 0;
  /** Moves and transfers of the page in flight: a live change waits for them. */
  private readonly pending = signal(0);
  /** Pings that came while a card was held go round once more. */
  private readonly liveRetry = new Subject<TodoPing>();

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
  private readonly boardView = viewChild(TodoBoardViewComponent);
  /** A card of the board is held or a write of the page is in flight: the rows wait too. */
  readonly hold = computed(() => !!this.boardView()?.dragging() || this.pending() > 0);
  /** The board whose pings the page takes ("Alle" has none: its rows take theirs). */
  private readonly liveBoard = computed(() => (this.all() ? null : (this.board()?.id ?? null)));
  /**
   * My principal id: known in "Alle", else the one member of my personal board. The rows
   * of "Meine To-Dos" keep only the cards assigned to it.
   */
  readonly me = computed(() => {
    if (this.meId()) return this.meId();
    return this.board()?.kind === 'personal' ? (this.members()[0]?.principalId ?? null) : null;
  });
  /** The boards whose pings the rows take besides their own: a card can join a row there. */
  readonly liveRowIds = computed(() =>
    this.boards()
      .filter((b) => this.all() || b.kind !== 'personal')
      .map((b) => b.id),
  );
  /** The cards the rows show after the filters; null until the rows of this board answered. */
  readonly rowMatches = signal<number | null>(null);
  readonly withRows = computed(() => this.board()?.kind === 'personal' && this.view() === 'board');
  /**
   * Phone, "Alle" or "Meine To-Dos" in the board view (known from the board list while
   * the board loads): every board is one section of a list, the personal board too.
   */
  readonly phoneList = computed(() => {
    if (!this.phone()) return false;
    if (this.all()) return true;
    return this.view() === 'board' && (this.board() ?? this.summary())?.kind === 'personal';
  });
  /** The personal board as the first section of the phone list. */
  readonly lead = computed<RowLead | null>(() => {
    const b = this.board();
    return b && this.phoneList() && !this.noMatch() ? { board: b, cards: this.visible() } : null;
  });
  /** The "Verschieben" sheet of the phone: the tile it is for. */
  readonly tileMenu = signal<TileMenuRequest | null>(null);
  readonly tileMenuOpen = signal(false);
  readonly tileTransferOpen = signal(false);
  readonly tileTransferring = signal(false);
  /** The live region of the sheet: the move of a column pick, as the keyboard drag says it. */
  readonly tileSaid = signal('');
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
  /**
   * The shape of a board that loads, the shape of a new board. A board shown or read ahead
   * before shows at once, without a skeleton.
   */
  readonly skeleton = computed(() => {
    const personal = this.summary()?.kind === 'personal';
    return {
      columns: 4,
      // A new personal board has no labels, so its chip row has no label chip.
      labels: !personal,
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

  readonly assigneeOptions = computed<FilterSelectOption[]>(() => {
    const all = this.i18n.translate('todos.filter.all');
    const nobody = this.i18n.translate('todos.filter.nobody');
    return [
      { value: '', label: all, person: { name: all, icon: 'users' } },
      {
        value: 'me',
        label: this.i18n.translate('todos.filter.me'),
        person: { name: this.auth.displayName(), principalId: 'me' },
      },
      { value: 'none', label: nobody, person: { name: nobody, icon: 'user' } },
      ...this.members().map((m) => {
        const label = m.displayName ?? this.i18n.translate('chat.deletedPerson');
        return { value: m.principalId, label, person: { name: label, principalId: m.principalId } };
      }),
    ];
  });
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
    if (this.board()) {
      items.push({ id: 'archive', label: this.i18n.translate('todos.archive.title'), icon: 'archive' });
    }
    return [{ items }];
  });

  constructor() {
    this.api.boards().subscribe({
      next: (boards) => {
        this.boards.set(boards);
        this.boardsRead.set(true);
        if (!this.boardId() && (!this.cardId() || this.cardUnresolved())) this.openDefault(boards);
        // Read every board and its cards ahead, so a board change and an opened card
        // show at once; the shown board first.
        const shown = this.boardId();
        this.cache.prefetch(
          boards.map((b) => b.id),
          shown && shown !== ALL_BOARDS ? shown : null,
        );
      },
      error: () => {
        if (!this.boardId()) {
          this.loading.set(false);
          this.error.set(true);
        }
      },
    });

    // A card-only link: open the board the card is on now.
    const linked = this.boardId() ? null : this.cardId();
    if (linked) this.openCardBoard(linked);

    // An entry URL with a board and a card: the card may have moved to another board.
    effect(() => {
      const id = this.entryCard();
      if (!id || !this.boardsRead()) return;
      untracked(() => {
        this.entryCard.set(null);
        this.checkCardBoard(id);
      });
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

    // Keep the shown board and its people for a return.
    effect(() => {
      const b = this.board();
      if (b) untracked(() => this.cache.putBoard(b, this.etag));
    });
    effect(() => {
      const list = this.members();
      const b = this.board();
      if (b && list.length) untracked(() => this.cache.putMembers(b.id, list));
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

    // The sheet and its transfer dialog live on the phone only: a wider window closes
    // them and forgets the tile, so they do not open again on the way back.
    effect(() => {
      if (this.phone()) return;
      untracked(() => {
        this.tileMenuOpen.set(false);
        this.tileTransferOpen.set(false);
        this.tileMenu.set(null);
      });
    });

    // Side by side the page fills the viewport and only the columns scroll.
    effect(() => this.frame.fill.set(!this.phone()));

    // The pings of the shown board.
    effect((onCleanup) => {
      const id = this.liveBoard();
      if (!id) return;
      const sub = untracked(() =>
        merge(this.live.changes$([id]), this.liveRetry)
          .pipe(batchPings())
          .subscribe((pings) => this.onPings(pings)),
      );
      onCleanup(() => sub.unsubscribe());
    });

    // Poll every 30 s while the tab is visible (120 s while the socket is up), and on the
    // focus of the window.
    interval(BOARD_POLL_MS)
      .pipe(
        filter(() => typeof document === 'undefined' || document.visibilityState !== 'hidden'),
        filter(() => !this.live.connected() || ++this.ticks % LIVE_POLL_EVERY === 0),
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

  /** Open the board of a card-only link; a card that does not read falls back to the default board. */
  private openCardBoard(cardId: Uuid): void {
    this.api.card(cardId, { detail: true }).subscribe({
      next: (card) => {
        if (this.boardId() || this.cardId() !== cardId) return;
        void this.router.navigate(['/todos', card.boardId], { replaceUrl: true, queryParamsHandling: 'preserve' });
      },
      error: () => {
        if (this.boardId()) return;
        this.cardUnresolved.set(true);
        if (this.boardsRead()) this.openDefault(this.boards());
      },
    });
  }

  /**
   * Move an older link (`/todos/<board>?card=<id>`) to the board the card is on now. The
   * personal board and "Alle" stay: their rows show cards of other boards.
   */
  private checkCardBoard(cardId: Uuid): void {
    const boardId = this.boardId();
    if (!boardId || boardId === ALL_BOARDS) return;
    if (this.boards().find((b) => b.id === boardId)?.kind === 'personal') return;
    this.api.card(cardId, { detail: true }).subscribe({
      next: (card) => {
        if (card.boardId === boardId || this.boardId() !== boardId || this.cardId() !== cardId) return;
        void this.router.navigate(['/todos', card.boardId], { replaceUrl: true, queryParamsHandling: 'preserve' });
      },
      error: () => undefined,
    });
  }

  /** Show a board; `held` takes it from the reads made before, else it waits for its read. */
  private loadBoard(id: Uuid, held = this.cache.board(id)): void {
    const seq = ++this.loadSeq;
    this.loading.set(true);
    this.notFound.set(false);
    this.error.set(false);
    this.board.set(null);
    this.etag = null;
    this.rowMatches.set(null);
    this.filter.set(NO_FILTER);
    this.search.sync('');
    // A board read ahead shows at once; the read behind it keeps it on a 304.
    if (held) {
      this.board.set(held.board);
      this.etag = held.etag;
      this.loading.set(false);
      this.cache.readCards(held.board.cards, true);
    }
    const muts = this.mutations;
    this.api.pollBoard(id, held?.etag ?? null).subscribe({
      next: ({ board, etag }) => {
        if (seq !== this.loadSeq) return;
        if (board && !(held && muts !== this.mutations)) {
          this.board.set(board);
          this.etag = etag;
          if (!held) this.cache.readCards(board.cards, true);
        }
        this.loading.set(false);
      },
      error: (err: unknown) => {
        if (seq !== this.loadSeq) return;
        this.loading.set(false);
        if (err instanceof HttpErrorResponse && err.status === 404) {
          this.board.set(null);
          this.notFound.set(true);
        } else if (!held) this.error.set(true);
      },
    });
    this.members.set((held && this.cache.members(id)) || []);
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
    this.today.set(isoDay(new Date()));
    this.pollBoard(board);
  }

  /** The ETag read of the shown board alone (the poll, and a `board` ping). */
  private pollBoard(board: TodoBoard): void {
    const seq = this.loadSeq;
    const muts = this.mutations;
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

  // ------------------------------------------------------------------ live

  /** A card is held anywhere on the page or a write is in flight: a live change waits. */
  private busy(): boolean {
    return this.hold() || !!this.rowsView()?.dragging();
  }

  private onPings(pings: readonly TodoPing[]): void {
    const board = this.board();
    if (!board) return;
    if (this.busy()) {
      for (const p of pings) this.liveRetry.next(p);
      return;
    }
    for (const p of pings) {
      if (p.boardId !== board.id) continue;
      if (p.type === 'board') this.pollBoard(board);
      else if (p.type === 'card_removed') this.dropTile(p.cardId);
      else this.readTile(p);
    }
  }

  /**
   * Read the tile of a `card` ping and put it in place; a 404 or another board takes it out.
   * A write of mine or a tile taken off while the read was out makes the answer stale: it
   * is dropped and the card is read again. Another live tile does not, because it changes
   * only its own card.
   */
  private readTile(ping: TodoPing & { type: 'card' }): void {
    const seq = this.loadSeq;
    const writes = this.localWrites;
    this.api.cardTile(ping.cardId).subscribe({
      next: (tile) => {
        if (seq !== this.loadSeq) return;
        // The same load: the board answered before its first ping, and only a new load clears it.
        const board = this.board() as TodoBoard;
        if (this.busy() || writes !== this.localWrites) {
          this.liveRetry.next(ping);
          return;
        }
        if (tile.boardId !== board.id) {
          this.dropTile(tile.id);
          return;
        }
        this.mutations++;
        this.board.set(placeTile(board, tile));
        this.refreshMine();
      },
      error: (err: unknown) => {
        if (seq === this.loadSeq && err instanceof HttpErrorResponse && err.status === 404) this.dropTile(ping.cardId);
      },
    });
  }

  /** Take a tile off the shown board when it holds it. */
  private dropTile(cardId: Uuid): void {
    const board = this.board();
    if (!board?.cards.some((c) => c.id === cardId)) return;
    // A tile read that left before the drop would put the card back: it counts as a write.
    this.wrote();
    this.board.set(removeTile(board, cardId));
  }

  /** Count a change of mine: it makes a poll and a tile read that are out stale. */
  private wrote(): void {
    this.mutations++;
    this.localWrites++;
  }

  /** Count a write of the page in flight until `req` ends. */
  private track<T>(req: Observable<T>): Observable<T> {
    this.pending.update((n) => n + 1);
    return req.pipe(finalize(() => this.pending.update((n) => n - 1)));
  }

  /**
   * Read the board again without an ETag after a refused change. Unlike `loadBoard` it
   * keeps the board on screen, the filters and the search.
   */
  private resync(id: Uuid): void {
    const seq = this.loadSeq;
    this.wrote();
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

  /** Read the board summaries again (the open counts of the picker). */
  private refreshBoards(): void {
    this.api.boards().subscribe({
      next: (boards) => this.boards.set(boards),
      error: () => undefined,
    });
  }

  /** The assignees of a card changed or may have: read "mine" again, now or at the next pick of "Ich". */
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
    const root = event.currentTarget as HTMLElement;
    // Only the shown elements. The drawer itself holds the focus after the open and is not
    // in `items`: a Tab from there (or from any element outside the list) wraps like one
    // from an edge.
    const items = focusableIn(
      root,
      'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ).filter((el) => el.offsetParent !== null || el === document.activeElement);
    trapTab(event, root, { items, outsideWraps: true, focusRootWhenEmpty: false });
  }

  moveCard(event: BoardMove): void {
    const board = this.board();
    if (!board) return;
    const optimistic = applyMove(board, event.cardId, event.move);
    this.wrote();
    this.board.set(optimistic);
    this.track(this.api.moveCard(event.cardId, event.move)).subscribe({
      next: (tile) => {
        this.wrote();
        const now = this.board();
        if (now) this.board.set(replaceTile(now, tile));
      },
      error: (err: unknown) => {
        this.toast.error(this.i18n.translate(moveErrorText(err, 'todos.error.move')));
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
    this.wrote();
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
    this.wrote();
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
      this.wrote();
      this.board.set(removeTile(board, card.id));
      this.refreshMine();
      this.refreshBoards();
    } else if (card.boardId === board.id && !held) {
      this.wrote();
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
    this.wrote();
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
    this.wrote();
    this.board.set({
      ...board,
      cards: board.cards.map((c) => (c.id === event.id ? { ...c, commentCount: event.commentCount } : c)),
    });
  }

  onArchived(id: Uuid): void {
    this.rowsView()?.cardRemoved(id);
    const board = this.board();
    this.wrote();
    // A card of a row lives on another board: the archive count of this one stays.
    if (board?.cards.some((c) => c.id === id)) {
      this.board.set({ ...removeTile(board, id), archivedCount: board.archivedCount + 1 });
    }
    this.closeCard();
  }

  onRestored(card: TodoCardDetail): void {
    const board = this.board();
    if (!board || card.boardId !== board.id) return;
    this.wrote();
    this.board.set({ ...placeTile(board, card), archivedCount: Math.max(0, board.archivedCount - 1) });
  }

  // ------------------------------------------------------------------ sheet

  /** A long press on a tile (phone): the "Verschieben" sheet for it. */
  onTileMenu(request: TileMenuRequest): void {
    this.tileMenu.set(request);
    this.tileMenuOpen.set(true);
  }

  /**
   * The sheet picked a column: the card goes to its end, as with a drag. The live region
   * says so, the sheet forgets the tile, and the focus goes back to the moved tile.
   */
  onTileColumn(columnId: Uuid): void {
    const req = this.tileMenu();
    if (!req) return;
    const cardId = req.card.id;
    if (this.board()?.cards.some((c) => c.id === cardId)) this.moveCard({ cardId, move: { columnId } });
    else this.rowsView()?.moveTo(cardId, columnId);
    const column = req.columns.find((c) => c.id === columnId)?.name ?? '';
    this.tileSaid.set(this.i18n.translate('todos.drag.dropped', { title: req.card.title, column }));
    this.tileMenu.set(null);
    afterNextRender(
      () => this.host.nativeElement.querySelector<HTMLElement>(`[data-card-id="${cardId}"]`)?.focus(),
      { injector: this.injector },
    );
  }

  /** The transfer dialog of the sheet opened or closed; closed, it forgets the tile. */
  onTileTransferOpen(open: boolean): void {
    this.tileTransferOpen.set(open);
    if (!open) this.tileMenu.set(null);
  }

  /**
   * The transfer dialog of the sheet picked a board: the card goes there. The page takes
   * the answer as the drawer's transfer, then as its change, so the board and the rows
   * follow; a refusal reads both again.
   */
  transferTile(target: TodoTransferTarget): void {
    const req = this.tileMenu();
    if (!req) return;
    this.tileTransferring.set(true);
    this.track(this.api.transferCard(req.card.id, { boardId: target.boardId, columnId: target.columnId })).subscribe({
      next: (card) => {
        this.tileTransferring.set(false);
        this.tileTransferOpen.set(false);
        this.onTransferred({ card, fromBoardId: req.boardId });
        this.onCardChanged(card);
        if (!this.board()) this.refreshBoards();
        this.toast.success(this.i18n.translate('todos.card.transferred', { board: target.boardName }));
        this.tileMenu.set(null);
      },
      error: (err: unknown) => {
        this.tileTransferring.set(false);
        this.tileTransferOpen.set(false);
        this.toast.error(this.i18n.translate(moveErrorText(err, 'todos.error.transfer')));
        const board = this.board();
        if (board) this.resync(board.id);
        this.rowsView()?.refresh();
        this.tileMenu.set(null);
      },
    });
  }

  /** A drag in the rows moved a card between two of their boards: the open counts change. */
  onRowTransferred(): void {
    this.refreshBoards();
  }

  /**
   * A card of the personal board landed in a row below it: it moves at once, and back with
   * a toast when the server refuses. After the answer it stays in that row only when it is
   * assigned to me (`accept`).
   */
  onDropIntoRow(event: RowDrop): void {
    const board = this.board();
    const rows = this.rowsView();
    const tile = board?.cards.find((c) => c.id === event.cardId);
    if (!board || !rows || !tile) return;
    const optimistic = removeTile(board, tile.id);
    this.wrote();
    this.board.set(optimistic);
    rows.receive(tile, event.boardId, event.move);
    this.track(this.api.transferCard(tile.id, { boardId: event.boardId, ...event.move })).subscribe({
      next: (card) => {
        // A card of mine stays in its row (the server makes me its assignee when I am a
        // member there); one that leaves the rows gets a toast from `accept`.
        this.rowsView()?.accept(card);
        this.refreshBoards();
        this.refreshMine();
      },
      error: (err: unknown) => this.transferFailed(board, optimistic, err),
    });
  }

  /** A card of a row landed on the personal board above: it moves at once, as above. */
  onDropFromRow(event: BoardMove): void {
    const board = this.board();
    const tile = board?.canWrite ? this.rowsView()?.take(event.cardId) : null;
    if (!board || !tile) return;
    const optimistic = insertTile(board, tile, event.move);
    this.wrote();
    this.board.set(optimistic);
    this.track(this.api.transferCard(tile.id, { boardId: board.id, ...event.move })).subscribe({
      next: (card) => {
        const now = this.board();
        if (now?.id === board.id) {
          this.wrote();
          this.board.set(replaceTile(now, card));
        }
        this.refreshBoards();
        this.refreshMine();
      },
      error: (err: unknown) => this.transferFailed(board, optimistic, err),
    });
  }

  /** Roll a refused drag between the board and the rows back, then read both again. */
  private transferFailed(board: TodoBoard, optimistic: TodoBoard, err: unknown): void {
    this.toast.error(this.i18n.translate(moveErrorText(err, 'todos.error.transfer')));
    if (this.board() === optimistic) this.board.set(board);
    this.resync(board.id);
    this.rowsView()?.refresh();
  }

  onSettingsChanged(board: TodoBoard): void {
    this.wrote();
    this.board.set(board);
    this.boards.update((list) => list.map((b) => (b.id === board.id ? { ...b, name: board.name } : b)));
  }

  /** Read the board again, not from the reads made before (the retry after an error). */
  reload(): void {
    const id = this.boardId();
    if (id) this.loadBoard(id, null);
  }
}
