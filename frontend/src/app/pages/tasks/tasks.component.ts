import {
  ChangeDetectionStrategy,
  Component,
  type OnDestroy,
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
import { formatMoment } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Translate, TranslationKey } from '@core/i18n/translations';
import type { ApplicationListItem, ApplicationType, IsoDateTime, Uuid } from '@core/api/models';
import { TodosApiService, type TodoMineItem } from '@core/api/todos.service';
import {
  EmptyStateComponent,
  FilterSelectComponent,
  type FilterSelectOption,
  IconComponent,
  ListDetailLayoutComponent,
  ListItemComponent,
  liveSearch,
  NoteComponent,
  ScrollFadeDirective,
  SearchPillComponent,
  SkeletonComponent,
  type StatusKind,
  StatusTextComponent,
  StickyBarComponent,
} from '@stupa-makers/ui-kit';
// By path, not through the `@shared/ui` barrel, so this lazy chunk takes only the blocks
// it uses.
import {
  flowColorKind,
} from '@shared/status-kind.util';
import { NO_FILTER, dueInfo, matchesFilter, type DueTone } from '../../features/todos/todos.util';
import { PageFrameService } from '../../layout/page-frame.service';
import { ApplicationsPageService } from '../applications/applications-page.service';
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';
import { calendarDaysSince, isoDay } from '@shared/date-format';
import { groupByMonth, type MonthGroup } from '@shared/group-by-month';
import { formatMoney } from '@shared/format-money';
import { prefetchDetails } from '@core/cache/detail-prefetch';
import { applicationReads } from '../applications/application-reads';
import { PullRefreshDirective } from '@shared/ui/pull-refresh/pull-refresh.directive';

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
  item: TodoMineItem;
  due: string | null;
  tone: DueTone;
}

/** One row as the template shows it. */
interface TaskRow {
  item: ApplicationListItem;
  createdAt: string;
  title: string;
  typeLabel: string;
  stateLabel: string | null;
  stateKind: StatusKind;
  amount: string | null;
  since: IsoDateTime;
}

/**
 * Tasks (board Arbeit-Aufgaben): the applications that wait for an action of the user,
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
 * loads again. If the application is no longer a task, the page opens the next task, or
 * the empty state when no task is left.
 *
 * Below the applications the group "To-Dos" lists the open cards assigned to the user
 * over all boards (`GET /todos/mine`, by due date, frames 10 and 15). A card opens as
 * `/tasks/todo/:cardId` with the card detail in the right pane. While To-Dos exist, the
 * groups carry headings with their counts and the chips "Anzeigen" and "Fällig" filter
 * them; without To-Dos the page looks as before.
 */
@Component({
  selector: 'app-tasks',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    PullRefreshDirective,
    NoteComponent,
    PageHeaderComponent,
    RouterOutlet,
    TranslatePipe,
    IconComponent,
    EmptyStateComponent,
    ListDetailLayoutComponent,
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
export class TasksComponent implements OnDestroy {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly page = inject(ApplicationsPageService);
  private readonly frame = inject(PageFrameService);
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
  /** The list and the detail sit side by side. */
  readonly split = computed(() => this.layout()?.collapsed() === false);

  /** The id of the application in the detail pane, from the child route. */
  readonly selectedId = signal<Uuid | null>(null);
  /** The id of the To-Do in the detail pane (`/tasks/todo/:cardId`). */
  readonly selectedTodo = signal<Uuid | null>(null);
  readonly detailOpen = computed(() => this.selectedId() !== null || this.selectedTodo() !== null);

  /** The open cards assigned to me; a failed request leaves the group out. */
  readonly todos = signal<TodoMineItem[]>([]);
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
    () => `${this.i18n.translate('tasks.show.label')}: ${this.i18n.translate(SHOW_TEXT[this.show()])}`,
  );
  readonly dueOptions = computed<FilterSelectOption[]>(() => [
    { value: '', label: this.i18n.translate('todos.filter.all') },
    { value: 'overdue', label: this.i18n.translate('todos.filter.overdue') },
    { value: 'week', label: this.i18n.translate('todos.filter.week') },
    { value: 'none', label: this.i18n.translate('todos.filter.noDate') },
  ]);
  readonly dueText = computed(() => this.i18n.translate(DUE_TEXT[this.due()]));

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
    // The shown rows read their detail ahead, so a click shows it at once.
    prefetchDetails({
      items: this.rows,
      key: (r) => r.item.id,
      reads: (r) => applicationReads(r.item.id),
      when: this.showApplications,
    });
    // The people of a board are read once for all its cards.
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

    // The open application comes from the child route (`/tasks/:id`).
    this.readSelection();
    this.router.events
      .pipe(
        filter((e) => e instanceof NavigationEnd),
        takeUntilDestroyed(),
      )
      .subscribe(() => this.readSelection());

    // The detail pane changed an application: load the list again. A deleted application
    // leaves the list at once; the detail goes back to `/tasks` itself.
    this.page.changes$.pipe(takeUntilDestroyed()).subscribe((change) => {
      if (change.source === 'list') return;
      if (change.kind === 'deleted') {
        this.tasks.update((cur) => cur.filter((t) => t.id !== change.id));
        return;
      }
      this.load(change.id);
    });

    effect(() => this.page.split.set(this.split()));
    // Side by side the page fills the viewport: the frame drops the footer below it, so
    // only the panes scroll.
    effect(() => this.frame.fill.set(this.split()));
  }

  ngOnDestroy(): void {
    this.frame.fill.set(false);
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
    const child = this.route.snapshot.firstChild?.paramMap;
    this.selectedId.set(child?.get('id') ?? null);
    this.selectedTodo.set(child?.get('cardId') ?? null);
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
   * `changedId`: the application that the detail changed. When it was the open task and
   * it left the list, the page opens the next task.
   */
  private load(changedId?: Uuid): void {
    const seq = ++this.fetchSeq;
    const before = this.tasks().map((t) => t.id);
    this.api.listTasks().subscribe({
      next: (t) => {
        if (seq !== this.fetchSeq) return;
        this.tasks.set(t);
        this.error.set(false);
        this.loading.set(false);
        if (changedId) this.advance(changedId, before);
      },
      error: () => {
        if (seq !== this.fetchSeq) return;
        // A failed reload keeps the rows; only a failed first load shows the error.
        if (!changedId) {
          this.tasks.set([]);
          this.error.set(true);
        }
        this.loading.set(false);
      },
    });
  }

  /**
   * The open task left the list: open the task that followed it, else the one before it,
   * else no task (the empty state). An open application that was never a task (a deep
   * link) stays open.
   */
  private advance(changedId: Uuid, before: readonly Uuid[]): void {
    const open = this.selectedId();
    if (!open || open !== changedId) return;
    const now = new Set(this.tasks().map((t) => t.id));
    if (now.has(open)) return;
    const at = before.indexOf(open);
    if (at < 0) return;
    const next =
      before.slice(at + 1).find((id) => now.has(id)) ??
      before
        .slice(0, at)
        .reverse()
        .find((id) => now.has(id)) ??
      this.tasks()[0]?.id ??
      null;
    void this.router.navigate(next ? ['/tasks', next] : ['/tasks'], { replaceUrl: true });
  }
}
