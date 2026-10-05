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
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { ApplicationListItem, ApplicationType, IsoDateTime, Uuid } from '@core/api/models';
import { IconComponent } from '@stupa-makers/ui-kit';
// By path, not through the `@shared/ui` barrel, so this lazy chunk takes only the blocks
// it uses.
import { EmptyStateComponent } from '@shared/ui/empty-state/empty-state.component';
import { ListDetailLayoutComponent } from '@shared/ui/list-detail/list-detail-layout.component';
import { ListItemComponent } from '@shared/ui/list-item/list-item.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';
import { StatusTextComponent } from '@shared/ui/status-text/status-text.component';
import { flowColorKind, type StatusKind } from '@shared/status-kind.util';
import { ScrollFadeDirective } from '@shared/scroll-fade.directive';
import { PageFrameService } from '../../layout/page-frame.service';
import { ApplicationsPageService } from '../applications/applications-page.service';
import { groupByMonth, type MonthGroup } from '../applications/applications.util';

const DAY_MS = 86_400_000;

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
 */
@Component({
  selector: 'app-tasks',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterOutlet,
    TranslatePipe,
    IconComponent,
    EmptyStateComponent,
    ListDetailLayoutComponent,
    ListItemComponent,
    SkeletonComponent,
    StatusTextComponent,
    ScrollFadeDirective,
  ],
  providers: [ApplicationsPageService],
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

  readonly rows = computed<TaskRow[]>(() =>
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

  /** The rows by month of submission, like the applications list. */
  readonly groups = computed<MonthGroup<TaskRow>[]>(() =>
    groupByMonth(this.rows(), this.i18n.locale()),
  );

  constructor() {
    this.page.listPath.set(['/tasks']);
    this.api.applicationTypes({ quiet: true }).subscribe({
      next: (t) => this.types.set(t),
      error: () => this.types.set([]),
    });
    this.load();

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

  /** Application title (system title field) with fallback. */
  titleOf(item: ApplicationListItem): string {
    return item.title?.trim() || this.i18n.translate('applications.list.untitled');
  }

  /** The amount in the currency of the application, or null without an amount. */
  money(item: ApplicationListItem): string | null {
    if (item.amount === null || item.amount === undefined || item.amount === '') return null;
    const n = Number(item.amount);
    if (Number.isNaN(n)) return item.amount;
    return new Intl.NumberFormat(this.i18n.formatLocale(), {
      style: 'currency',
      currency: item.currency ?? 'EUR',
    }).format(n);
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
    if (!at) return '—';
    const then = new Date(at);
    if (Number.isNaN(then.getTime())) return '—';
    const now = new Date(Date.now());
    const day = (d: Date): number => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
    // Round, not floor: a day with a DST change has 23 or 25 hours.
    const days = Math.max(0, Math.round((day(now) - day(then)) / DAY_MS));
    if (days === 0) return this.i18n.translate('tasks.waiting.today');
    if (days === 1) return this.i18n.translate('tasks.waiting.one');
    return this.i18n.translate('tasks.waiting.other', { n: days });
  }

  /** The exact moment, for the tooltip of the waiting time. */
  sinceTitle(at: IsoDateTime | null | undefined): string | null {
    if (!at) return null;
    const d = new Date(at);
    if (Number.isNaN(d.getTime())) return null;
    const when = new Intl.DateTimeFormat(this.i18n.formatLocale(), {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(d);
    return this.i18n.translate('tasks.waiting.title', { date: when });
  }

  /** "Zur Liste" (narrow layout): close the detail. */
  closeDetail(): void {
    void this.router.navigate(['/tasks']);
  }

  private readSelection(): void {
    this.selectedId.set(this.route.snapshot.firstChild?.paramMap.get('id') ?? null);
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
