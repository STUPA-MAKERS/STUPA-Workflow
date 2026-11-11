import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, NavigationEnd, Router, RouterOutlet } from '@angular/router';
import { filter } from 'rxjs/operators';
import { ApiClient } from '@core/api/api-client.service';
import { I18nService } from '@core/i18n/i18n.service';
import { searchPlaceholder } from '@shared/util/search-placeholder';
import { formatMoment } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Translate, TranslationKey } from '@core/i18n/translations';
import type { ApplicationListItem, ApplicationType, IsoDateTime, Uuid } from '@core/api/models';
import { TodosApiService, type TodoMineItem } from '@core/api/todos.service';
import {
  EmptyStateComponent,
  FilterSelectComponent,
  type FilterSelectOption,
  filterChipText,
  IconComponent,
  ListDetailLayoutComponent,
  ListGroupComponent,
  ListItemComponent,
  liveSearch,
  ScrollFadeDirective,
  SearchPillComponent,
  SkeletonComponent,
  type StatusKind,
  StatusTextComponent,
  StickyBarComponent,
  PageHeaderComponent,
  RowMenuComponent,
  type RowMenuItem,
  type RowMenuSection,
  MEDIA,
  mediaQuery,
} from '@stupa-makers/ui-kit';
import { injectListDetailPage } from '@stupa-makers/ui-kit/shell';
import {
  flowColorKind,
} from '@shared/status-kind.util';
import { NO_FILTER, dueInfo, matchesFilter, type DueTone } from '../../features/todos/todos.util';
import { ApplicationsPageService } from '../applications/applications-page.service';
import { calendarDaysSince, isoDay } from '@shared/date-format';
import { groupByMonth, type MonthGroup } from '@shared/group-by-month';
import { formatMoney } from '@shared/format-money';
import { prefetchDetails } from '@core/cache/detail-prefetch';
import { applicationReads } from '../applications/application-reads';
import { PullRefreshDirective } from '@shared/ui/pull-refresh/pull-refresh.directive';
import { isRefreshItem, refreshMenuSection, reloadLikePull } from '@shared/ui/pull-refresh/refresh-menu';
import { LoadErrorComponent } from '@shared/ui/load-error/load-error.component';

/** "Anzeigen": both groups, or one of them. */
export type TasksShow = 'all' | 'applications' | 'todos';
/** "Fällig" over the To-Dos. */
export type TasksDue = '' | 'overdue' | 'week' | 'none';

const SHOW_TEXT: Record<TasksShow, TranslationKey> = {
  all: 'tasks.show.all',
  applications: 'tasks.show.applications',
  todos: 'tasks.show.todos',
};

const DUE_TEXT: Record<TasksDue, TranslationKey> = {
  '': 'todos.filter.due',
  overdue: 'todos.filter.overdue',
  week: 'todos.filter.week',
  none: 'todos.filter.noDate',
};

/** One To-Do as the template shows it. */
interface TodoRow {
  readonly item: TodoMineItem;
  readonly due: string | null;
  readonly tone: DueTone;
}

/** One row as the template shows it. */
interface TaskRow {
  readonly item: ApplicationListItem;
  readonly createdAt: string;
  readonly title: string;
  readonly typeLabel: string;
  readonly stateLabel: string | null;
  readonly stateKind: StatusKind;
  readonly amount: string | null;
  readonly since: IsoDateTime;
}

/**
 * Tasks: the applications that wait for an action of the user,
 * from GET /applications/tasks, in server order (newest first).
 *
 * The page has the same two panes as the applications page: the task list on the left
 * and the full detail of the open application on the right. The detail is the detail
 * component of the applications page, routed as the child `/tasks/:id`, so a reload and a
 * deep link open the same task. On a narrow screen the page shows one pane at a time,
 * with "Zur Liste" above the detail.
 *
 * A row shows the title, the status and the type, the amount, and how long the task
 * waits. The waiting time counts from the last status change (`stateSince`). An older
 * server that does not send it gives the time of the last change (`updatedAt`).
 *
 * When the detail changes the open application (a transition, for example), the list
 * loads again. The open application stays open, also when it is no longer a task and
 * leaves the list, so the user sees the result of the change. The page never opens
 * another task on its own.
 *
 * Below the applications the group "To-Dos" lists the open cards assigned to the user
 * over all boards (`GET /todos/mine`, by due date). A card opens as
 * `/tasks/todo/:cardId` with the card detail in the right pane. While To-Dos exist, the
 * groups carry headings (no counts, spec 000560) and the chips "Anzeigen" and "Fällig" filter
 * them; without To-Dos the page looks as before.
 */
@Component({
  selector: 'app-tasks',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RowMenuComponent,
    PullRefreshDirective,
    LoadErrorComponent,
    PageHeaderComponent,
    RouterOutlet,
    TranslatePipe,
    IconComponent,
    EmptyStateComponent,
    ListDetailLayoutComponent,
    ListGroupComponent,
    ListItemComponent,
    SkeletonComponent,
    StatusTextComponent,
    ScrollFadeDirective,
    FilterSelectComponent,
    SearchPillComponent,
    StickyBarComponent,
  ],
  providers: [ApplicationsPageService],
  host: { '[class.pane-page]': 'split()' },
  templateUrl: './tasks.component.html',
  styleUrl: './tasks.component.scss',
})
export class TasksComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  protected readonly phone = mediaQuery(MEDIA.phone);
  /** The ⋮ menu of the phone header: "Aktualisieren", the one-tap way to the pull (app spec 000514). */
  protected readonly phoneMenu = computed<RowMenuSection[]>(() => [
    refreshMenuSection((key) => this.i18n.translate(key)),
  ]);

  protected onPhoneMenu(item: RowMenuItem): void {
    if (isRefreshItem(item)) reloadLikePull(() => this.refreshAll());
  }
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly page = inject(ApplicationsPageService);
  private readonly todosApi = inject(TodosApiService);

  readonly tasks = signal<ApplicationListItem[]>([]);
  readonly loading = signal(true);
  /** The task request failed. The page then shows an error and no count, not "0 offen". */
  readonly error = signal(false);
  /** Fetch sequence number. The handler drops a late response of an older request. */
  private fetchSeq = 0;

  private readonly types = signal<ApplicationType[]>([]);
  private readonly typesById = computed(
    () => new Map(this.types().map((t) => [t.id, t.name])),
  );

  /** The list-detail layout, for its split state. */
  private readonly layout = viewChild(ListDetailLayoutComponent);
  private readonly listDetail = injectListDetailPage(this.layout);
  /** The list and the detail sit side by side. */
  readonly split = this.listDetail.split;

  /** The id of the application in the detail pane, from the child route. */
  readonly selectedId = this.listDetail.selectedId;
  /** The id of the To-Do in the detail pane (`/tasks/todo/:cardId`). */
  readonly selectedTodo = signal<Uuid | null>(null);
  readonly detailOpen = computed(() => this.selectedId() !== null || this.selectedTodo() !== null);

  /** The open cards assigned to me; a failed request leaves the group out. */
  readonly todos = signal<readonly TodoMineItem[]>([]);
  private todoSeq = 0;
  readonly show = signal<TasksShow>('all');
  readonly due = signal<TasksDue>('');
  readonly hasTodos = computed(() => this.todos().length > 0);
  /** Without open to-dos the filter is hidden, so it must not hide the applications. */
  readonly showApplications = computed(() => !this.hasTodos() || this.show() !== 'todos');
  readonly showTodos = computed(() => this.hasTodos() && this.show() !== 'applications');

  /** The applied search text, lower case; the rows filter in the browser. */
  readonly query = signal('');
  /** The search field: it filters while the user types, Escape and × clear it. */
  readonly search = liveSearch({
    run: (q) => this.query.set(q.toLocaleLowerCase()),
    minLength: 1,
  });

  readonly todoRows = computed<TodoRow[]>(() => {
    const today = isoDay(new Date(Date.now()));
    const f = { ...NO_FILTER, due: this.due() };
    const ctx = { today, mine: new Set<Uuid>(), labels: new Map() };
    const t: Translate = (key, params) => this.i18n.translate(key, params);
    const q = this.query();
    return this.todos()
      .filter((item) => matchesFilter(item, f, ctx))
      .filter((item) => !q || `${item.title} ${item.boardName}`.toLocaleLowerCase().includes(q))
      .map((item) => {
        if (!item.dueDate) return { item, due: null, tone: 'normal' as DueTone };
        const info = dueInfo(item.dueDate, today, this.i18n.formatLocale(), t);
        return { item, due: info.note ? `${info.date} · ${info.note}` : info.date, tone: info.tone };
      });
  });

  readonly showOptions = computed<FilterSelectOption[]>(() => [
    { value: 'all', label: this.i18n.translate('tasks.show.all') },
    { value: 'applications', label: this.i18n.translate('tasks.show.applications') },
    { value: 'todos', label: this.i18n.translate('tasks.show.todos') },
  ]);
  readonly showText = computed(
    () =>
      filterChipText(
        this.i18n.translate('tasks.show.label'),
        this.show() === 'all' ? null : this.i18n.translate(SHOW_TEXT[this.show()]),
      ),
  );
  readonly dueOptions = computed<FilterSelectOption[]>(() => [
    { value: '', label: this.i18n.translate('todos.filter.all') },
    { value: 'overdue', label: this.i18n.translate('todos.filter.overdue') },
    { value: 'week', label: this.i18n.translate('todos.filter.week') },
    { value: 'none', label: this.i18n.translate('todos.filter.noDate') },
  ]);
  readonly dueText = computed(() =>
    filterChipText(
      this.i18n.translate('todos.filter.due'),
      this.due() ? this.i18n.translate(DUE_TEXT[this.due()]) : null,
    ),
  );

  /** The search placeholder with the number of tasks (§ 000661). */
  readonly searchPlaceholder = computed(() =>
    searchPlaceholder(
      this.i18n,
      { plain: 'tasks.search', one: 'tasks.searchCountOne', many: 'tasks.searchCount' },
      this.tasks().length + this.todos().length,
      this.loading(),
    ),
  );

  readonly rows = computed<TaskRow[]>(() => {
    const q = this.query();
    return this.allRows().filter(
      (r) => !q || `${r.title} ${r.typeLabel} ${r.stateLabel ?? ''}`.toLocaleLowerCase().includes(q),
    );
  });
  private readonly allRows = computed<TaskRow[]>(() =>
    this.tasks().map((item) => ({
      item,
      createdAt: item.createdAt,
      title: this.titleOf(item),
      typeLabel: this.typesById().get(item.typeId) ?? '',
      stateLabel: item.state?.label ?? null,
      stateKind: flowColorKind(item.state?.color),
      amount: this.money(item),
      since: this.since(item),
    })),
  );

  /**
   * The rows by month of submission, like the applications list. Beside the to-dos the
   * group "Anträge" has no month headings, so its rows are one list: as one row group per
   * month, the groups met without the gap of the rows and with round corners between
   * them.
   */
  readonly groups = computed<MonthGroup<TaskRow>[]>(() =>
    this.hasTodos()
      ? [{ key: 'all', label: '', items: this.rows() }]
      : groupByMonth(this.rows(), (r) => r.createdAt, this.i18n.formatLocale()),
  );

  constructor() {
    prefetchDetails({
      items: this.rows,
      key: (r) => r.item.id,
      reads: (r) => applicationReads(r.item.id),
      when: this.showApplications,
    });
    const boards = new Set<Uuid>();
    prefetchDetails({
      items: this.todoRows,
      key: (r) => r.item.id,
      reads: (r) => {
        const board = r.item.boardId;
        const first = !boards.has(board);
        boards.add(board);
        return [
          this.todosApi.card(r.item.id, { detail: true }),
          ...(first ? [this.todosApi.members(board, { detail: true })] : []),
        ];
      },
      when: this.showTodos,
    });
    this.page.listPath.set(['/tasks']);
    this.api.applicationTypes({ quiet: true }).subscribe({
      next: (t) => this.types.set(t),
      error: () => this.types.set([]),
    });
    this.load();
    this.loadTodos();

    this.readSelection();
    this.router.events
      .pipe(
        filter((e) => e instanceof NavigationEnd),
        takeUntilDestroyed(),
      )
      .subscribe(() => this.readSelection());

    this.page.changes$.pipe(takeUntilDestroyed()).subscribe((change) => {
      if (change.source === 'list') return;
      if (change.kind === 'deleted') {
        this.tasks.update((cur) => cur.filter((t) => t.id !== change.id));
        return;
      }
      this.load(change.id);
    });

    effect(() => this.page.split.set(this.split()));
  }

  setShow(value: string): void {
    this.show.set(value === 'applications' || value === 'todos' ? value : 'all');
  }

  setDue(value: string): void {
    this.due.set((['overdue', 'week', 'none'] as const).find((d) => d === value) ?? '');
  }

  /** Read the To-Dos again (the pane changed or archived one). */
  loadTodos(): void {
    const seq = ++this.todoSeq;
    this.todosApi.mine().subscribe({
      next: (m) => {
        if (seq === this.todoSeq) this.todos.set(m.items);
      },
      error: () => {
        if (seq === this.todoSeq) this.todos.set([]);
      },
    });
  }

  /** Application title (system title field) with fallback. */
  titleOf(item: ApplicationListItem): string {
    return item.title?.trim() || this.i18n.translate('applications.list.untitled');
  }

  /** The amount in the currency of the application, or null without an amount. */
  money(item: ApplicationListItem): string | null {
    if (item.amount === null || item.amount === undefined || item.amount === '') return null;
    return formatMoney(item.amount, this.i18n.formatLocale(), { currency: item.currency }) || item.amount;
  }

  /** The moment the task started to wait: the last status change, else the last change. */
  since(item: ApplicationListItem): IsoDateTime {
    return item.stateSince ?? item.updatedAt;
  }

  /**
   * How long the task waits, in calendar days: "seit heute", "seit 1 Tag", "seit 5 Tagen"
   * (EN "today", "for 1 day", "for 5 days").
   * The days are local calendar days, not blocks of 24 hours: a change yesterday at 23:00
   * shows "seit 1 Tag" at 09:00 today. A missing or invalid time gives a dash.
   */
  waitingSince(at: IsoDateTime | null | undefined): string {
    const days = calendarDaysSince(at, new Date(Date.now()));
    if (days === null) return '—';
    if (days === 0) return this.i18n.translate('tasks.waiting.today');
    if (days === 1) return this.i18n.translate('tasks.waiting.one');
    return this.i18n.translate('tasks.waiting.other', { n: days });
  }

  /** The exact moment, for the tooltip of the waiting time. */
  sinceTitle(at: IsoDateTime | null | undefined): string | null {
    const when = formatMoment(at, this.i18n.formatLocale());
    return when ? this.i18n.translate('tasks.waiting.title', { date: when }) : null;
  }

  /** "Zur Liste" (narrow layout): close the detail. */
  closeDetail(): void {
    void this.router.navigate(['/tasks']);
  }

  private readSelection(): void {
    this.selectedTodo.set(this.route.snapshot.firstChild?.paramMap.get('cardId') ?? null);
  }

  /** Pull to refresh: the tasks and the to-dos load again. */
  refreshAll(): void {
    this.load();
    this.loadTodos();
  }

  /** Load the task list again after a failed first load. */
  retry(): void {
    this.error.set(false);
    this.loading.set(true);
    this.load();
  }

  /**
   * Load the task list. The loaded rows stay until the answer arrives, so a reload after
   * a change does not flash to placeholders.
   *
   * `changedId`: the application that the detail changed. A failed reload after a change
   * keeps the rows; the open application stays open either way.
   */
  private load(changedId?: Uuid): void {
    const seq = ++this.fetchSeq;
    this.api.listTasks().subscribe({
      next: (t) => {
        if (seq !== this.fetchSeq) return;
        this.tasks.set(t);
        this.error.set(false);
        this.loading.set(false);
      },
      error: () => {
        if (seq !== this.fetchSeq) return;
        if (!changedId) {
          this.tasks.set([]);
          this.error.set(true);
        }
        this.loading.set(false);
      },
    });
  }
}
