import {
  ChangeDetectionStrategy,
  Component,
  type ElementRef,
  type OnDestroy,
  computed,
  effect,
  inject,
  signal,
  type WritableSignal,
  viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import {
  ActivatedRoute,
  NavigationEnd,
  Router,
  RouterLink,
  RouterOutlet,
  type ParamMap,
} from '@angular/router';
import { filter } from 'rxjs/operators';
import { ApiClient } from '@core/api/api-client.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type {
  ApplicationListItem,
  ApplicationListQuery,
  ApplicationType,
  Transition,
  Uuid,
} from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import {
  ButtonComponent,
  CurrencyInputComponent,
  DatepickerComponent,
  DialogComponent,
  IconComponent,
  MEDIA,
  ToastService,
} from '@stupa-makers/ui-kit';
import {
  FilterSelectComponent,
  ListDetailLayoutComponent,
  ListItemComponent,
  RowMenuComponent,
  SearchPillComponent,
  StickyBarComponent,
  SideSheetComponent,
  SkeletonComponent,
  StatusTextComponent,
  flowColorKind,
  type RowMenuItem,
  type RowMenuSection,
  type StatusKind,
} from '@shared/ui';
import { ScrollFadeDirective } from '@shared/scroll-fade.directive';
import { downloadBlob } from '@shared/download.util';
import { mediaQuerySignal } from '../../layout/media-query';
import { PageFrameService } from '../../layout/page-frame.service';
import { RailStatusService } from '../../layout/rail-status.service';
import { BudgetTreeApi, type BudgetTreeNode } from '../budget/budget-tree.api';
import { CostCentreTreeComponent } from '../budget/cost-centre-tree.component';
import { ApplicationsPageService } from './applications-page.service';
import { groupByMonth, type MonthGroup } from './applications.util';
import { ForceStatusDialogComponent } from './force-status-dialog/force-status-dialog.component';
import { AgendaDialogComponent } from './agenda-dialog/agenda-dialog.component';
import {
  RowTransitionsMenuComponent,
  type RowAction,
} from './row-transitions-menu/row-transitions-menu.component';
import { ShareLinksDialogComponent } from './share-links-dialog/share-links-dialog.component';

/**
 * One filter of the list.
 *
 * `empty` is the value that means "not filtering". It travels as no query parameter and
 * as no request field, so a shared URL and a request carry only what was actually chosen,
 * and a reset is simply every filter back to `empty`.
 */
interface FilterDef {
  /** Query-parameter name. Also the request field. */
  readonly param: string;
  readonly signal: WritableSignal<string>;
  readonly empty: string;
  /** Narrow a raw parameter to an allowed value. A hand-edited URL reaches this. */
  readonly parse?: (raw: string) => string;
  readonly numeric?: boolean;
  readonly trim?: boolean;
}

/** The sort orders the sort menu offers. */
type SortKey = 'createdAt:desc' | 'createdAt:asc' | 'amount:desc' | 'amount:asc';

/** The largest page the list endpoint answers (`MAX_LIMIT` of the backend paging). */
const MAX_PAGE = 200;

const SORTS: readonly { key: SortKey; label: TranslationKey }[] = [
  { key: 'createdAt:desc', label: 'applications.list.sort.newest' },
  { key: 'createdAt:asc', label: 'applications.list.sort.oldest' },
  { key: 'amount:desc', label: 'applications.list.sort.amountDesc' },
  { key: 'amount:asc', label: 'applications.list.sort.amountAsc' },
];

/** One row as the template shows it. */
interface ListRow {
  item: ApplicationListItem;
  createdAt: string;
  title: string;
  typeLabel: string;
  stateLabel: string | null;
  stateKind: StatusKind;
  amount: string | null;
}

/** Which filter sheet is open. */
type FilterSheet = 'budget' | 'more' | null;

/**
 * The applications page: the list pane with search and filters, and the detail of the
 * open application beside it (board Anträge).
 *
 * The routes `/applications` and `/applications/:id` share this page. The detail is the
 * child route in the outlet of the detail pane, so the list keeps its rows and its scroll
 * position while the reader opens one application after the other. On a narrow screen the
 * page shows one pane at a time (`app-list-detail`), with "Zur Liste" above the detail.
 *
 * Every filter and the sort live in the query params, so a filtered list is shareable as
 * a link and the back button works. Opening a row keeps them.
 */
@Component({
  selector: 'app-applications-list',
  // A pane page (styles.scss): the panes fill the free height and scroll by themselves.
  host: { '[class.pane-page]': 'split()' },
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    RouterLink,
    RouterOutlet,
    TranslatePipe,
    ButtonComponent,
    CurrencyInputComponent,
    DatepickerComponent,
    DialogComponent,
    FilterSelectComponent,
    IconComponent,
    ListDetailLayoutComponent,
    ListItemComponent,
    RowMenuComponent,
    SearchPillComponent,
    StickyBarComponent,
    SideSheetComponent,
    SkeletonComponent,
    StatusTextComponent,
    ScrollFadeDirective,
    CostCentreTreeComponent,
    RowTransitionsMenuComponent,
    ShareLinksDialogComponent,
    ForceStatusDialogComponent,
    AgendaDialogComponent,
  ],
  providers: [ApplicationsPageService],
  templateUrl: './applications-list.component.html',
  styleUrl: './applications-list.component.scss',
})
export class ApplicationsListComponent implements OnDestroy {
  private readonly api = inject(ApiClient);
  private readonly budgetApi = inject(BudgetTreeApi);
  private readonly i18n = inject(I18nService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly auth = inject(AuthService);
  private readonly toast = inject(ToastService);
  private readonly railStatus = inject(RailStatusService);
  private readonly page = inject(ApplicationsPageService);
  private readonly frame = inject(PageFrameService);

  readonly canExport = computed(() => this.auth.can('application.export'));
  readonly exporting = signal(false);

  readonly limit = 20;

  /** Phone width: one "more" menu in the header, filter sheets from the bottom. */
  readonly phone = mediaQuerySignal(MEDIA.phone);

  /** The list-detail layout, for its split state. */
  private readonly layout = viewChild(ListDetailLayoutComponent);
  /** The list and the detail sit side by side. */
  readonly split = computed(() => this.layout()?.collapsed() === false);

  /** The id of the application in the detail pane, from the child route. */
  readonly selectedId = signal<Uuid | null>(null);

  /** Initial load after a filter or sort change. It hides the whole list. */
  readonly loading = signal(true);
  /** Load of more pages while scrolling. It is incremental and the list stays visible. */
  readonly loadingMore = signal(false);
  readonly error = signal(false);
  /** Accumulated applications across all loaded pages so far (infinite scroll). */
  readonly items = signal<ApplicationListItem[]>([]);
  readonly total = signal(0);
  private nextOffset = 0;
  /** Fetch sequence number. The fetch handler drops late responses from old filters. */
  private fetchSeq = 0;

  readonly types = signal<ApplicationType[]>([]);

  /** `gremium` has no visible control. It still mirrors the URL. */
  readonly gremium = signal('');
  /**
   * `mine=true`: only the own applications ("Alle ansehen" under "Meine Anträge" on the
   * start page). A removable chip shows it, and the reset clears it with the others.
   */
  readonly mine = signal('');
  /** The applied search: what the URL holds and what the request sends. */
  readonly q = signal('');
  /**
   * The text in the search pill. It runs ahead of `q` while the debounce waits, so a
   * load of the next page in that time still sends the applied search only.
   */
  readonly searchText = signal('');
  /** Debounce timer of the search (about 400 ms, like /expenses). */
  private searchTimer: ReturnType<typeof setTimeout> | null = null;
  readonly typeId = signal('');
  /** The chosen flow states. `state` repeats in the URL and in the request (A4). */
  readonly states = signal<readonly string[]>([]);
  /**
   * Which rows to show. Archived applications leave the working list by default.
   * Tri-state, because "only the archived ones" and "both" are different questions.
   */
  readonly archived = signal<'false' | 'true' | 'all'>('false');
  readonly amountMin = signal('');
  readonly amountMax = signal('');
  readonly createdFrom = signal('');
  readonly createdTo = signal('');
  readonly budgetId = signal('');
  readonly sortField = signal<'createdAt' | 'amount'>('createdAt');
  readonly sortOrder = signal<'asc' | 'desc'>('desc');

  /**
   * The values in the "Weitere Filter" sheet. They are a draft: only "Anwenden" puts them
   * into the URL, and from there into the applied filters. A sheet closed in another way
   * (scrim, Escape, swipe) thus changes no request and no badge.
   */
  readonly draftAmountMin = signal('');
  readonly draftAmountMax = signal('');
  readonly draftCreatedFrom = signal('');
  readonly draftCreatedTo = signal('');

  /** Cost-centre tree of the filter, without the cost centres hidden in the budget tab. */
  readonly budgetTree = signal<BudgetTreeNode[]>([]);

  /** The open filter sheet. */
  readonly sheet = signal<FilterSheet>(null);
  readonly budgetSheetOpen = computed(() => this.sheet() === 'budget');
  readonly moreSheetOpen = computed(() => this.sheet() === 'more');
  /** Phone: filters and pickers open from the bottom; wider: from the start edge. */
  readonly sheetSide = computed(() => (this.phone() ? 'bottom' : 'start'));

  /**
   * Status options: the real states of the loaded applications. No endpoint lists the
   * states of the flow for every reader, so the map keeps every state seen once; the
   * filter therefore does not collapse to the states of the current result.
   */
  private readonly seenStates = signal<Map<string, string>>(new Map());
  readonly stateOptions = computed(() =>
    [...this.seenStates()].map(([value, label]) => ({ value, label })),
  );

  readonly activeFilterCount = computed(
    () =>
      [
        this.q(),
        this.typeId(),
        this.states().length ? 'x' : '',
        this.budgetId(),
        this.amountMin(),
        this.amountMax(),
        this.createdFrom(),
        this.createdTo(),
        this.mine(),
        this.archived() === 'false' ? '' : this.archived(),
      ].filter((v) => String(v ?? '').trim() !== '').length,
  );

  /** Amount and date: the filters behind "Weitere Filter". */
  readonly moreCount = computed(
    () =>
      [this.amountMin(), this.amountMax(), this.createdFrom(), this.createdTo()].filter(
        (v) => v.trim() !== '',
      ).length,
  );

  /** The label of the status chip: the chosen states, else "Status". */
  readonly stateChipLabel = computed(() => {
    const chosen = this.states();
    if (!chosen.length) return this.i18n.translate('applications.list.filter.state');
    const names = this.seenStates();
    const known = chosen.map((id) => names.get(id)).filter((n): n is string => !!n);
    return known.length === chosen.length
      ? known.join(', ')
      : this.i18n.translate('applications.list.filter.stateCount', { count: chosen.length });
  });

  readonly budgetChipLabel = computed(() => {
    const id = this.budgetId();
    if (!id) return this.i18n.translate('applications.list.filter.budget');
    return findNode(this.budgetTree(), id)?.name ?? this.i18n.translate('applications.list.filter.budget');
  });

  readonly typeChipLabel = computed(() => {
    const id = this.typeId();
    if (!id) return this.i18n.translate('applications.list.filter.type');
    return this.typesById().get(id) ?? this.i18n.translate('applications.list.filter.type');
  });

  readonly archivedChipLabel = computed(() => {
    const v = this.archived();
    if (v === 'false') return this.i18n.translate('applications.list.filter.archived');
    return this.i18n.translate('applications.list.filter.archivedChip', {
      value: this.i18n.translate(
        v === 'true' ? 'applications.list.filter.archivedOnly' : 'applications.list.filter.archivedAll',
      ),
    });
  });

  /** The choices of the type chip: "Alle Typen" first. */
  readonly typeOptions = computed(() => [
    { value: '', label: this.i18n.translate('applications.list.filter.allTypes') },
    ...this.types().map((t) => ({ value: t.id, label: t.name })),
  ]);

  readonly archivedOptions = computed(() => [
    { value: 'false', label: this.i18n.translate('applications.list.filter.archivedHide') },
    { value: 'true', label: this.i18n.translate('applications.list.filter.archivedOnly') },
    { value: 'all', label: this.i18n.translate('applications.list.filter.archivedAll') },
  ]);

  /** The search placeholder with the number of applications, as on the board. */
  readonly searchPlaceholder = computed(() => {
    if (this.loading() && this.total() === 0) return this.i18n.translate('applications.list.searchPlain');
    if (this.total() === 1) return this.i18n.translate('applications.list.searchCountOne');
    return this.i18n.translate('applications.list.searchCount', { count: this.total() });
  });

  /** True while unloaded applications are left. It controls the sentinel and "load more". */
  readonly hasMore = computed(() => this.items().length < this.total());

  /** Sentinel at the list end. The next load starts when it becomes visible. */
  readonly sentinel = viewChild<ElementRef<HTMLElement>>('sentinel');

  /**
   * The export can carry every filter of the list except `mine`: the endpoint has no
   * such parameter. So the export goes away while `mine` is set. Otherwise the download
   * holds more rows than the list shows.
   */
  readonly exportShown = computed(() => this.canExport() && !this.mine());

  private readonly typesById = computed(
    () => new Map(this.types().map((t) => [t.id, t.name])),
  );

  readonly rows = computed<ListRow[]>(() =>
    this.items().map((item) => ({
      item,
      createdAt: item.createdAt,
      title: this.titleOf(item),
      typeLabel: this.typesById().get(item.typeId) ?? '',
      stateLabel: item.state?.label ?? null,
      stateKind: flowColorKind(item.state?.color),
      amount: this.money(item),
    })),
  );

  /**
   * The rows by month of submission, while the list sorts by date. Sorted by amount, the
   * months would interleave, so the list is then one group without a heading.
   */
  readonly groups = computed<MonthGroup<ListRow>[]>(() => {
    const rows = this.rows();
    if (this.sortField() !== 'createdAt') return rows.length ? [{ key: 'all', label: '', items: rows }] : [];
    return groupByMonth(rows, this.i18n.locale());
  });

  /** The sort menu: one checked item per order. */
  readonly sortSections = computed<RowMenuSection[]>(() => {
    const current = `${this.sortField()}:${this.sortOrder()}`;
    const sorts: RowMenuItem[] = SORTS.map((s) => ({
      id: s.key,
      label: this.i18n.translate(s.label),
      checked: s.key === current,
    }));
    return [{ label: this.i18n.translate('applications.list.sort.title'), items: sorts }];
  });

  /** Phone: the sort orders and the export in one "more" menu of the header. */
  readonly phoneMenuSections = computed<RowMenuSection[]>(() => {
    const sections = [...this.sortSections()];
    if (this.exportShown()) {
      sections.push({
        items: [{ id: 'export', label: this.i18n.translate('applications.list.export'), icon: 'download' }],
      });
    }
    return sections;
  });

  // --- row actions --------------------------------------------------------
  /** The row whose links the share dialog shows. */
  readonly shareFor = signal<Uuid | null>(null);
  readonly shareOpen = signal(false);
  /** The row the force-status dialog acts on. */
  readonly forceFor = signal<ApplicationListItem | null>(null);
  readonly forceOpen = signal(false);
  /** The row and the transition of the agenda dialog ("Auf Tagesordnung setzen"). */
  readonly agendaFor = signal<{ item: ApplicationListItem; transition: Transition } | null>(null);
  readonly agendaOpen = signal(false);
  /** The row that waits for the delete confirmation. */
  readonly deleteFor = signal<ApplicationListItem | null>(null);
  readonly deleting = signal(false);
  /** A row action in flight (archive, transition). */
  readonly busyRow = signal<Uuid | null>(null);

  constructor() {
    this.api.applicationTypes({ quiet: true }).subscribe({
      next: (types) => this.types.set(types),
      error: () => this.types.set([]),
    });
    // Cost centres hidden in the budget tab (`hiddenInBudget`) do not appear in the
    // filter either.
    this.budgetApi.tree().subscribe({
      next: (tree) => this.budgetTree.set(pruneHidden(tree)),
      error: () => this.budgetTree.set([]),
    });

    // The filter and sort values live in the query params. Every change resets the list
    // and reloads page 0. The offset is not in the URL (infinite scroll).
    this.route.queryParamMap.pipe(takeUntilDestroyed()).subscribe((pm) => {
      this.readFilters(pm);
      this.sortField.set(pm.get('sort') === 'amount' ? 'amount' : 'createdAt');
      this.sortOrder.set(pm.get('order') === 'asc' ? 'asc' : 'desc');
      this.reload();
    });

    // The open application comes from the child route (`/applications/:id`).
    this.readSelection();
    this.router.events
      .pipe(
        filter((e) => e instanceof NavigationEnd),
        takeUntilDestroyed(),
      )
      .subscribe(() => this.readSelection());

    // A change in the detail pane (a transition, an edit, an archive, a delete) shows in
    // the list. The loaded rows and the scroll position stay.
    this.page.changes$.pipe(takeUntilDestroyed()).subscribe((change) => {
      if (change.source !== 'list') this.apply(change.id, change.kind);
    });

    effect(() => this.page.split.set(this.split()));
    // Side by side the page fills the viewport: the frame drops the footer below it, so
    // only the panes scroll.
    effect(() => this.frame.fill.set(this.split()));

    // Lazy infinite scroll: an IntersectionObserver on the sentinel loads the next page
    // once the list end comes into view. The rootMargin acts as a prefetch. The effect
    // re-binds whenever the sentinel appears or disappears.
    effect((onCleanup) => {
      const el = this.sentinel()?.nativeElement;
      // Without a DOM API (SSR or tests) there is no observer. The "load more" button
      // then stays as the fallback.
      if (!el || typeof IntersectionObserver === 'undefined') return;
      const obs = new IntersectionObserver(
        (entries) => {
          if (entries.some((e) => e.isIntersecting)) this.loadMore();
        },
        { rootMargin: '400px' },
      );
      obs.observe(el);
      onCleanup(() => obs.disconnect());
    });
  }

  ngOnDestroy(): void {
    this.frame.fill.set(false);
    if (this.searchTimer) clearTimeout(this.searchTimer);
  }

  /** Application title from the system title field, with the fallback "untitled". */
  titleOf(item: ApplicationListItem): string {
    return item.title?.trim() || this.i18n.translate('applications.list.untitled');
  }

  /** The amount in the currency of the row, or null without an amount. */
  private money(item: ApplicationListItem): string | null {
    if (item.amount === null) return null;
    const value = Number(item.amount);
    if (!Number.isFinite(value)) return item.amount;
    return new Intl.NumberFormat(this.i18n.formatLocale(), {
      style: 'currency',
      currency: item.currency ?? 'EUR',
    }).format(value);
  }

  // --- navigation ---------------------------------------------------------

  /** Open a row in the detail pane. The filters stay in the URL. */
  open(id: Uuid): void {
    void this.router.navigate(['/applications', id], { queryParamsHandling: 'preserve' });
  }

  /** "Zur Liste" (narrow layout): close the detail, keep the filters. */
  closeDetail(): void {
    void this.router.navigate(['/applications'], { queryParamsHandling: 'preserve' });
  }

  private readSelection(): void {
    this.selectedId.set(this.route.snapshot.firstChild?.paramMap.get('id') ?? null);
  }

  // --- filters ------------------------------------------------------------

  /**
   * The search. After about 400 ms of debounce it writes the `q` query param and
   * reloads. The value stays in the URL, so the filtered list is shareable as a link.
   */
  onSearch(value: string): void {
    this.searchText.set(value);
    if (this.searchTimer) clearTimeout(this.searchTimer);
    this.searchTimer = setTimeout(
      () => this.navigate({ q: this.searchText().trim() || null }),
      400,
    );
  }

  /**
   * Apply one filter immediately, through the URL like every other filter. The URL is
   * what the list reloads from, so a reset always has a parameter to clear.
   */
  setFilter(param: string, value: string): void {
    const def = this.filters.find((f) => f.param === param);
    this.navigate({ [param]: value === def?.empty ? null : value });
  }

  /** The chosen states of the status chip. */
  setStates(ids: readonly string[]): void {
    this.navigate({ state: ids.length ? [...ids] : null });
  }

  /** Pick a cost centre in the tree sheet. `''` means all. */
  selectBudgetNode(id: string): void {
    this.sheet.set(null);
    this.navigate({ budget: id || null });
  }

  /** Open "Weitere Filter" with the applied values as the draft. */
  openMore(): void {
    this.draftAmountMin.set(this.amountMin());
    this.draftAmountMax.set(this.amountMax());
    this.draftCreatedFrom.set(this.createdFrom());
    this.draftCreatedTo.set(this.createdTo());
    this.sheet.set('more');
  }

  /** "Weitere Filter": apply the drafted amount and date range through the URL. */
  applyMore(): void {
    this.sheet.set(null);
    const amount = (raw: string) => (raw.trim() === '' ? null : Number(raw.trim()));
    const date = (raw: string) => raw.trim() || null;
    this.navigate({
      amountMin: amount(this.draftAmountMin()),
      amountMax: amount(this.draftAmountMax()),
      createdFrom: date(this.draftCreatedFrom()),
      createdTo: date(this.draftCreatedTo()),
    });
  }

  /** "Weitere Filter": clear the amount and the date range. */
  clearMore(): void {
    this.sheet.set(null);
    this.navigate({ amountMin: null, amountMax: null, createdFrom: null, createdTo: null });
  }

  /** Remove the `mine` filter (its chip). */
  clearMine(): void {
    this.setFilter('mine', '');
  }

  /**
   * Clear every filter. The signals go back to their defaults AND the query params are
   * cleared, because the URL is what the list reloads from.
   */
  reset(): void {
    for (const f of this.filters) f.signal.set(f.empty);
    this.states.set([]);
    this.searchText.set('');
    if (this.searchTimer) clearTimeout(this.searchTimer);
    this.navigate({ ...this.filterParams(true), state: null });
  }

  /** A sort order or the export was chosen in a header menu. */
  onHeaderMenu(item: RowMenuItem): void {
    if (item.id === 'export') {
      this.onExport();
      return;
    }
    const [sort, order] = item.id.split(':');
    this.navigate({ sort, order });
  }

  /**
   * Export the current list as Excel, with the filters of the URL (also `archived`).
   * Without `mine`, see `exportShown`.
   */
  onExport(): void {
    if (this.exporting() || !this.exportShown()) return;
    this.exporting.set(true);
    const query = this.buildQuery(0);
    delete query.limit;
    delete query.offset;
    delete query.mine;
    this.api.exportApplicationsXlsx(query).subscribe({
      next: (blob) => {
        downloadBlob(blob, 'applications.xlsx');
        this.exporting.set(false);
      },
      error: () => {
        this.exporting.set(false);
        this.toast.error(this.i18n.translate('applications.list.exportError'));
      },
    });
  }

  /** Append the next page. The visible sentinel or the "load more" button calls this. */
  loadMore(): void {
    if (this.loadingMore() || this.loading() || !this.hasMore()) return;
    this.loadingMore.set(true);
    this.fetch('more');
  }

  // --- row actions --------------------------------------------------------

  onRowAction(item: ApplicationListItem, action: RowAction): void {
    switch (action.kind) {
      case 'open':
        this.open(item.id);
        return;
      case 'share':
        this.shareFor.set(item.id);
        this.shareOpen.set(true);
        return;
      case 'force':
        this.forceFor.set(item);
        this.forceOpen.set(true);
        return;
      case 'delete':
        this.deleteFor.set(item);
        return;
      case 'archive':
        this.toggleArchived(item);
        return;
      case 'transition':
        // A transition onto the agenda needs the meeting: the dialog asks for it.
        if (action.transition.addsToAgenda) {
          this.agendaFor.set({ item, transition: action.transition });
          this.agendaOpen.set(true);
          return;
        }
        this.fire(item, action.transition.id);
    }
  }

  private fire(item: ApplicationListItem, transitionId: Uuid): void {
    if (this.busyRow()) return;
    this.busyRow.set(item.id);
    this.api.fireTransition(item.id, { transitionId }).subscribe({
      next: () => {
        this.busyRow.set(null);
        this.toast.success(this.i18n.translate('applications.actions.success'));
        this.changed(item.id, 'updated');
      },
      error: (err: { status?: number }) => {
        this.busyRow.set(null);
        this.toast.error(this.i18n.translate(actionErrorKey(err.status)));
        this.changed(item.id, 'updated');
      },
    });
  }

  private toggleArchived(item: ApplicationListItem): void {
    if (this.busyRow()) return;
    const next = item.archivedAt === null;
    this.busyRow.set(item.id);
    this.api.setApplicationArchived(item.id, next).subscribe({
      next: () => {
        this.busyRow.set(null);
        this.toast.success(
          this.i18n.translate(next ? 'applications.archived' : 'applications.unarchived'),
        );
        this.changed(item.id, 'updated');
      },
      error: () => {
        this.busyRow.set(null);
        this.toast.error(this.i18n.translate('applications.actions.error'));
      },
    });
  }

  /** The delete confirmation of a row. */
  confirmDelete(): void {
    const item = this.deleteFor();
    if (!item || this.deleting()) return;
    this.deleting.set(true);
    this.api.deleteApplication(item.id).subscribe({
      next: () => {
        this.deleting.set(false);
        this.deleteFor.set(null);
        this.toast.success(this.i18n.translate('applications.detail.deleted'));
        if (this.selectedId() === item.id) this.closeDetail();
        this.changed(item.id, 'deleted');
      },
      error: () => {
        this.deleting.set(false);
        this.toast.error(this.i18n.translate('applications.detail.deleteFailed'));
      },
    });
  }

  /** The agenda dialog fired its transition. */
  onAgendaDone(): void {
    const target = this.agendaFor();
    if (target) this.changed(target.item.id, 'updated');
  }

  /** The force-status dialog set a state. */
  onForced(): void {
    const item = this.forceFor();
    if (item) this.changed(item.id, 'updated');
  }

  /** A row changed here: update the list, the task count and the open detail. */
  private changed(id: Uuid, kind: 'updated' | 'deleted'): void {
    this.railStatus.refresh();
    this.apply(id, kind);
    this.page.notify({ id, kind, source: 'list' });
  }

  /**
   * Show a change of one application in the list, and keep the loaded rows.
   *
   * A deleted application leaves the list here, without a request. For an update, the
   * list loads again as many rows as it has loaded so far (see `refresh`): a new state can
   * move the row out of the filters, or an archive can hide it.
   */
  private apply(id: Uuid, kind: 'updated' | 'deleted'): void {
    if (kind === 'updated') {
      this.refresh();
      return;
    }
    const before = this.items().length;
    this.items.update((cur) => cur.filter((i) => i.id !== id));
    if (this.items().length < before) {
      this.total.update((t) => Math.max(0, t - 1));
      this.nextOffset = Math.max(0, this.nextOffset - 1);
    }
  }

  // --- loading ------------------------------------------------------------

  private navigate(queryParams: Record<string, string | number | readonly string[] | null>): void {
    void this.router.navigate([], {
      relativeTo: this.route.firstChild ?? this.route,
      queryParams,
      queryParamsHandling: 'merge',
    });
  }

  /**
   * Every single-value filter, declared once. The query-param reader, the reset and the
   * request builder all derive from this list, so a filter reaches every one of them or
   * none. The status filter repeats and has its own signal.
   */
  private readonly filters: readonly FilterDef[] = [
    { param: 'q', signal: this.q, empty: '', trim: true },
    { param: 'type', signal: this.typeId, empty: '' },
    { param: 'gremium', signal: this.gremium, empty: '' },
    { param: 'mine', signal: this.mine, empty: '', parse: (raw) => (raw === 'true' ? raw : '') },
    { param: 'budget', signal: this.budgetId, empty: '' },
    { param: 'amountMin', signal: this.amountMin, empty: '', numeric: true, trim: true },
    { param: 'amountMax', signal: this.amountMax, empty: '', numeric: true, trim: true },
    { param: 'createdFrom', signal: this.createdFrom, empty: '', trim: true },
    { param: 'createdTo', signal: this.createdTo, empty: '', trim: true },
    {
      param: 'archived',
      signal: this.archived as WritableSignal<string>,
      empty: 'false',
      // Anything that is not one of the two non-default values is the default, so a
      // hand-edited URL cannot leave the filter in a state no control shows.
      parse: (raw) => (raw === 'true' || raw === 'all' ? raw : 'false'),
    },
  ];

  /** Read every filter out of the URL. The URL is the single source of truth. */
  private readFilters(pm: ParamMap): void {
    for (const f of this.filters) {
      const raw = pm.get(f.param) ?? f.empty;
      f.signal.set(f.parse ? f.parse(raw) : raw);
    }
    this.searchText.set(this.q());
    this.states.set(pm.getAll('state').filter((s) => s.trim() !== ''));
  }

  /** Every filter as query params; `toDefaults` clears them all. */
  private filterParams(toDefaults = false): Record<string, string | number | null> {
    const out: Record<string, string | number | null> = {};
    for (const f of this.filters) {
      const raw = toDefaults ? f.empty : f.signal();
      const value = f.trim ? raw.trim() : raw;
      out[f.param] = value === f.empty ? null : f.numeric ? Number(value) : value;
    }
    return out;
  }

  /**
   * Reload page 0 after a filter or sort change, WITHOUT emptying the list first. The
   * rows stay until the new ones arrive, so a refresh never flashes to placeholders.
   * `loading` keeps its narrow meaning of "nothing to show yet".
   */
  protected reload(): void {
    this.nextOffset = 0;
    this.loadingMore.set(false);
    this.loading.set(this.items().length === 0);
    this.error.set(false);
    this.fetch('initial');
  }

  /**
   * Load the rows again after a change of one application, with the filters unchanged.
   *
   * One request from offset 0 gets as many rows as the list has loaded (at least one
   * page, at most `MAX_PAGE`). The loaded pages thus stay, with the open row
   * (`aria-current`) and the scroll position. A failure keeps the current rows.
   */
  protected refresh(): void {
    // Nothing shown yet: a plain reload, with its placeholder and its error.
    if (this.loading() || this.items().length === 0) {
      this.reload();
      return;
    }
    const size = Math.min(MAX_PAGE, Math.max(this.limit, this.items().length));
    this.loadingMore.set(false);
    this.fetch('refresh', size);
  }

  /**
   * The request, built from the applied filters. They change only through the URL
   * (`readFilters`), so every page and the export send what the URL and the chips show.
   */
  private buildQuery(offset: number, limit = this.limit): ApplicationListQuery {
    const query = { limit, offset } as Record<string, unknown>;
    for (const f of this.filters) {
      const raw = f.signal();
      const value = f.trim ? raw.trim() : raw;
      if (value === f.empty) continue;
      query[f.param] = f.numeric ? Number(value) : value;
    }
    if (this.states().length) query['state'] = [...this.states()];
    query['sort'] = this.sortField();
    query['order'] = this.sortOrder();
    return query as ApplicationListQuery;
  }

  /**
   * Fetch a page.
   *
   * - `initial`: the page replaces the list, and a failure shows the full error.
   * - `refresh`: as `initial`, but a failure keeps the rows and shows no error.
   * - `more`: the page appends, and a failure stays silent.
   */
  private fetch(mode: 'initial' | 'refresh' | 'more', limit = this.limit): void {
    const seq = ++this.fetchSeq;
    // A refresh starts at 0 but leaves `nextOffset` alone until its answer arrives, so a
    // failed refresh does not load the first page a second time on the next scroll.
    const offset = mode === 'refresh' ? 0 : this.nextOffset;
    this.api.listApplications(this.buildQuery(offset, limit)).subscribe({
      next: (page) => {
        if (seq !== this.fetchSeq) return;
        this.total.set(page.total);
        this.items.update((cur) => (mode === 'more' ? [...cur, ...page.items] : page.items));
        this.nextOffset = page.offset + page.items.length;
        this.collectStates(page.items);
        this.loading.set(false);
        this.loadingMore.set(false);
      },
      error: () => {
        if (seq !== this.fetchSeq) return;
        if (mode === 'initial') this.error.set(true);
        this.loading.set(false);
        this.loadingMore.set(false);
      },
    });
  }

  /** Merge the real states of the loaded applications into the status options. */
  private collectStates(items: ApplicationListItem[]): void {
    const next = new Map(this.seenStates());
    let changed = false;
    for (const item of items) {
      if (item.state && !next.has(item.state.id)) {
        next.set(item.state.id, item.state.label);
        changed = true;
      }
    }
    if (changed) this.seenStates.set(next);
  }
}

/** Remove the cost centres hidden in the budget tab, and their subtrees. */
function pruneHidden(nodes: BudgetTreeNode[]): BudgetTreeNode[] {
  return nodes
    .filter((n) => !n.hiddenInBudget)
    .map((n) => ({ ...n, children: pruneHidden(n.children) }));
}

/** Find a cost centre in the tree. */
function findNode(nodes: BudgetTreeNode[], id: string): BudgetTreeNode | null {
  for (const n of nodes) {
    if (n.id === id) return n;
    const hit = findNode(n.children, id);
    if (hit) return hit;
  }
  return null;
}

/** The toast key of a failed transition: 403 and 409 have their own text. */
export function actionErrorKey(status: number | undefined): TranslationKey {
  if (status === 403) return 'applications.transitions.forbidden';
  if (status === 409) return 'applications.actions.conflict';
  return 'applications.actions.error';
}
