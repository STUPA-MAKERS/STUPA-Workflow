import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, type ParamMap, Router, RouterLink } from '@angular/router';
import { NgTemplateOutlet } from '@angular/common';
import { Subject, of } from 'rxjs';
import { catchError, map, switchMap } from 'rxjs/operators';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type { Uuid } from '@core/api/models';
import { ButtonComponent, DialogComponent, IconComponent, MEDIA } from '@stupa-makers/ui-kit';
import { AuthService } from '@core/auth/auth.service';
import { downloadBlob } from '@shared/download.util';
import { ScrollFadeDirective } from '@shared/scroll-fade.directive';
import { SimplifyPathPipe } from '@shared/budget-path';
import {
  EmptyStateComponent,
  FilterSelectComponent,
  ListItemComponent,
  RowMenuComponent,
  type RowMenuItem,
  type RowMenuSection,
  SearchPillComponent,
  type Seg,
  SegBarComponent,
  SideSheetComponent,
  PageHeaderComponent,
  SheetBarComponent,
  SheetBarKickerDirective,
  SkeletonComponent,
  StatusTextComponent,
  type StatusKind,
  flowColorKind,
} from '@shared/ui';
import { mediaQuerySignal } from '../../layout/media-query';
import { BUDGET_PERMISSIONS } from '../../layout/nav.service';
import {
  BudgetTreeApi,
  type BudgetAllocationView,
  type BudgetApplication,
  type BudgetTreeNode,
  type FiscalYear,
} from './budget-tree.api';
import { BudgetCrumbsComponent } from './budget-crumbs.component';
import { BudgetPieComponent, type PieSlice } from './budget-pie.component';
import { BudgetSunburstComponent, type SunburstMetric } from './budget-sunburst.component';
import { nodeColors, resolveNodeColors } from './budget-color.util';

/** The amounts of one cost centre in one fiscal year, as numbers. */
export interface Figures {
  allocated: number;
  requested: number;
  /** Accepted applications minus the bookings against them. */
  bound: number;
  expended: number;
  income: number;
  /** bound + expended. */
  committed: number;
  available: number;
}

/** A figure the sheet names. `committed` is only a sum for the bars. */
export type FigureKey = Exclude<keyof Figures, 'committed'>;

/** A figure that the "Verteilung" chart can show. */
export type DistributionMetric = 'allocated' | 'requested' | 'bound' | 'expended' | 'available';

/** One row of the cost-centre tree in the pane. */
interface TreeRow {
  node: BudgetTreeNode;
  depth: number;
  hasChildren: boolean;
  expanded: boolean;
  /** Display colour of the node (see `nodeColors`). */
  color: string;
  /** The node has an own or inherited colour, so the row shows a swatch. */
  swatch: boolean;
  allocated: number;
  segments: Seg[];
  total: number | null;
  percent: number | null;
}

/** One row of "Auslastung je Budget". */
interface UsageRow {
  node: BudgetTreeNode;
  color: string;
  figures: Figures;
  percent: number | null;
  segments: Seg[];
  total: number | null;
}

/** An application on the selected cost centre, ready to show. */
interface AppRow {
  app: BudgetApplication;
  title: string;
  statusLabel: string | null;
  statusKind: StatusKind;
  costCentre: string | null;
}

const ZERO: Figures = {
  allocated: 0,
  requested: 0,
  bound: 0,
  expended: 0,
  income: 0,
  committed: 0,
  available: 0,
};

/** How many applications the sheet lists before "Alle ansehen". */
export const APPS_SHOWN = 5;

/**
 * Budget: the cost-centre tree beside a sheet with the figures of the selected cost centre.
 *
 * The pane holds the fiscal year, the overview (sunburst), a search and the tree. Each
 * tree node shows its allocation and a bar of its utilisation, in its own colour or the
 * colour it inherits (O19). The sheet shows the path, the six figures (Zuteilung,
 * Beantragt, Gebunden, Ausgegeben, Einnahmen, Verfügbar; N28), the distribution over the
 * sub cost centres, the utilisation per sub cost centre and the applications on it.
 *
 * On the wide layout the page fills the height of the viewport and does not scroll: in
 * the pane only the tree scrolls, and the sheet scrolls inside itself. Below the wide
 * breakpoint the year and the overview chips sit beside a path chip on the page. The path
 * chip opens the search and the tree in the shared side sheet: from the start, or on a
 * phone from the bottom. The query params hold the
 * selection, so the view is shareable as a link. A reader with a
 * gremium scope (`viewGremiumId`) gets only the subtrees of the server response.
 */
@Component({
  selector: 'app-budget-dashboard',
  // A pane page (styles.scss): the panes fill the free height and scroll by themselves.
  host: { '[class.pane-page]': 'wide()' },
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    PageHeaderComponent,
    SheetBarComponent,
    SheetBarKickerDirective,
    BudgetCrumbsComponent,
    NgTemplateOutlet,
    RouterLink,
    TranslatePipe,
    SimplifyPathPipe,
    ButtonComponent,
    DialogComponent,
    IconComponent,
    EmptyStateComponent,
    FilterSelectComponent,
    ListItemComponent,
    RowMenuComponent,
    SearchPillComponent,
    SegBarComponent,
    SideSheetComponent,
    SkeletonComponent,
    StatusTextComponent,
    BudgetPieComponent,
    BudgetSunburstComponent,
    ScrollFadeDirective,
  ],
  templateUrl: './budget-dashboard.component.html',
  styleUrl: './budget-dashboard.component.scss',
})
export class BudgetDashboardComponent {
  private readonly api = inject(BudgetTreeApi);
  private readonly i18n = inject(I18nService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly auth = inject(AuthService);

  /** The pane sits beside the sheet only on a wide viewport. */
  readonly wide = mediaQuerySignal(MEDIA.wide);
  /** A phone opens the tree in a sheet from the bottom, a narrow viewport in a sheet
   *  from the start. */
  readonly phone = mediaQuerySignal(MEDIA.phone);

  readonly canExport = computed(() => this.auth.can('budget.export'));
  /** The bookings page needs a global budget permission; a gremium scope alone has none. */
  readonly canSeeBookings = computed(() => this.auth.canAny(...BUDGET_PERMISSIONS));
  /** Only a reader with `budget.structure` can open /admin/cost-centres and add a year. */
  readonly canManageStructure = computed(() => this.auth.can('budget.structure'));
  readonly exporting = signal(false);

  readonly loading = signal(true);
  readonly error = signal(false);
  readonly tree = signal<BudgetTreeNode[]>([]);
  /** Fiscal years per root of the tree. */
  readonly fiscalYearsByBudget = signal<Record<Uuid, FiscalYear[]>>({});

  /** The root (top budget, or a scoped sub cost centre) the selection hangs under. */
  readonly selectedBudgetId = signal('');
  readonly selectedKsId = signal('');
  readonly selectedFyId = signal('');

  /** Narrow and phone: the side sheet with the tree. */
  readonly navOpen = signal(false);
  /** The text of "Kostenstelle suchen". */
  readonly query = signal('');
  /** Tree nodes the reader opened. The path to the selection is always open. */
  readonly expanded = signal<ReadonlySet<string>>(new Set());
  /** The figure the "Verteilung" chart shows. */
  readonly metric = signal<DistributionMetric>('allocated');
  readonly metrics: readonly DistributionMetric[] = [
    'allocated',
    'requested',
    'bound',
    'expended',
    'available',
  ];

  // ---------------------------------------------------------------- tree

  /** Tree without the hidden cost centres. `hiddenInBudget` removes the node and its
   *  subtree from the budget tab. This changes the display only: the values still count
   *  in the parent rollups. */
  private readonly visibleTree = computed<BudgetTreeNode[]>(() => {
    const prune = (nodes: BudgetTreeNode[]): BudgetTreeNode[] =>
      nodes
        .filter((n) => !n.hiddenInBudget)
        .map((n) => ({ ...n, children: prune(n.children) }));
    return prune(this.tree());
  });

  /** Roots of the tree: the forest roots of the server response that HAVE a fiscal year.
   *  The full view gives the top budgets; a gremium scope gives the assigned sub cost
   *  centres. The fiscal-year endpoint resolves a sub cost centre to its top budget. */
  readonly tops = computed(() => {
    const fy = this.fiscalYearsByBudget();
    return this.visibleTree().filter((n) => (fy[n.id]?.length ?? 0) > 0);
  });

  /**
   * Why the page shows nothing, or `null` while it has something to show.
   *
   * `'noBudgets'` — no cost centre is visible to this reader.
   * `'noFiscalYear'` — cost centres exist, but not one of them has a fiscal year. Every
   * figure on this page belongs to a fiscal year, so the tree stays empty until one
   * exists.
   *
   * The years arrive as one response per root, after the tree. Until the last of them is
   * in, "no root has a year" is not yet a fact, so neither claim is made.
   */
  readonly emptyReason = computed<'noBudgets' | 'noFiscalYear' | null>(() => {
    if (!this.visibleTree().length) return 'noBudgets';
    if (this.tops().length) return null;
    return this.pendingFiscalYears() > 0 ? null : 'noFiscalYear';
  });

  private readonly nodeById = computed(() => {
    const out = new Map<string, BudgetTreeNode>();
    const walk = (nodes: BudgetTreeNode[]): void => {
      for (const n of nodes) {
        out.set(n.id, n);
        walk(n.children);
      }
    };
    walk(this.visibleTree());
    return out;
  });

  /** Own or inherited colour of every visible node, `null` when it has none (O19). */
  private readonly setColors = computed(() => resolveNodeColors(this.visibleTree()));
  /** Display colour of every visible node. The tree, the bars and the charts all use it,
   *  so a cost centre has one colour on the page (gaps D6). */
  readonly colors = computed(() => nodeColors(this.visibleTree()));

  private readonly selectedKs = computed(() => this.nodeById().get(this.selectedKsId()) ?? null);
  /** The selected cost centre, for the template. */
  readonly current = this.selectedKs;

  /** The fiscal years of the selected root, for the year chip. */
  readonly years = computed<FiscalYear[]>(
    () => this.fiscalYearsByBudget()[this.selectedBudgetId()] ?? [],
  );
  /** The choices of the year chip. */
  readonly yearOptions = computed(() =>
    this.years().map((fy) => ({
      value: fy.id,
      label: this.i18n.translate('budget.dash.yearShort', { year: fy.display }),
    })),
  );
  readonly selectedYear = computed<FiscalYear | null>(
    () => this.years().find((f) => f.id === this.selectedFyId()) ?? null,
  );

  /** The path from the root to the selected cost centre. */
  readonly breadcrumbs = computed<BudgetTreeNode[]>(() => {
    const map = this.nodeById();
    let node = this.selectedKs();
    const chain: BudgetTreeNode[] = [];
    while (node) {
      chain.unshift(node);
      node = node.parentId ? (map.get(node.parentId) ?? null) : null;
    }
    return chain;
  });

  /** The label of the path chip on a narrow viewport. */
  readonly pathLabel = computed(() => this.breadcrumbs().map((n) => n.name).join(' › '));

  /**
   * The fiscal year whose figures a node in this root shows.
   *
   * Fiscal years belong to a top budget, so another root has its own ids. A node there
   * shows the year with the same start year as the selected one.
   */
  private fyIdFor(rootId: string): string {
    if (rootId === this.selectedBudgetId()) return this.selectedFyId();
    const year = this.selectedYear()?.year;
    return (this.fiscalYearsByBudget()[rootId] ?? []).find((f) => f.year === year)?.id ?? '';
  }

  /** The figures of a node in a fiscal year. A missing allocation counts as zero. */
  figuresOf(node: BudgetTreeNode, fyId = this.selectedFyId()): Figures {
    const a = node.byFiscalYear.find((x) => x.fiscalYearId === fyId);
    return a ? toFigures(a) : ZERO;
  }

  /** The visible rows of the tree, flattened in display order. */
  readonly treeRows = computed<TreeRow[]>(() => {
    const q = this.query().trim().toLowerCase();
    const open = this.expanded();
    const colors = this.colors();
    const set = this.setColors();
    const out: TreeRow[] = [];
    const matches = (n: BudgetTreeNode): boolean =>
      n.name.toLowerCase().includes(q) ||
      n.key.toLowerCase().includes(q) ||
      n.pathKey.toLowerCase().includes(q);
    // With a search: a node shows when it or a node below it matches, and every node on
    // the way to a match is open.
    const hits = new Set<string>();
    const mark = (n: BudgetTreeNode): boolean => {
      let any = matches(n);
      for (const c of n.children) any = mark(c) || any;
      if (any) hits.add(n.id);
      return any;
    };
    if (q) for (const t of this.tops()) mark(t);

    const walk = (n: BudgetTreeNode, depth: number, fyId: string): void => {
      if (q && !hits.has(n.id)) return;
      const children = q ? n.children.filter((c) => hits.has(c.id)) : n.children;
      const expanded = children.length > 0 && (q ? true : open.has(n.id));
      const f = this.figuresOf(n, fyId);
      const total = f.available + f.committed;
      out.push({
        node: n,
        depth,
        hasChildren: n.children.length > 0,
        expanded,
        color: colors.get(n.id) ?? '',
        swatch: set.get(n.id) != null,
        allocated: f.allocated,
        segments: [{ value: f.committed, tone: f.available < 0 ? 'error' : 'filled' }],
        total: total > 0 ? total : null,
        percent: utilisation(f),
      });
      if (expanded) for (const c of children) walk(c, depth + 1, fyId);
    };
    for (const t of this.tops()) walk(t, 0, this.fyIdFor(t.id));
    return out;
  });

  toggle(id: string): void {
    this.expanded.update((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  /** Open the path to a node and the node itself, so its sub cost centres show. */
  private expandPath(id: string): void {
    const map = this.nodeById();
    const add: string[] = [];
    let node = map.get(id) ?? null;
    while (node) {
      add.push(node.id);
      node = node.parentId ? (map.get(node.parentId) ?? null) : null;
    }
    if (add.every((x) => this.expanded().has(x))) return;
    this.expanded.update((s) => new Set([...s, ...add]));
  }

  // ---------------------------------------------------------------- sheet

  /** The six figures of the selected cost centre. */
  readonly figures = computed<Figures>(() => {
    const ks = this.selectedKs();
    return ks ? this.figuresOf(ks) : ZERO;
  });

  readonly figureList = computed(() => {
    const f = this.figures();
    const keys: FigureKey[] = [
      'allocated',
      'requested',
      'bound',
      'expended',
      'income',
      'available',
    ];
    return keys.map((k) => ({ key: k, label: this.figureLabel(k), value: f[k] }));
  });

  figureLabel(key: FigureKey): string {
    return this.i18n.translate(`budget.dash.fig.${key}` as TranslationKey);
  }

  /** The selected cost centre has sub cost centres to distribute over. */
  readonly hasChildren = computed(() => (this.selectedKs()?.children.length ?? 0) > 0);

  /** "Verteilung": the chosen figure over the direct sub cost centres. The part the
   *  selected cost centre keeps for itself is its own grey slice. */
  readonly distribution = computed<PieSlice[]>(() => {
    const ks = this.selectedKs();
    if (!ks?.children.length) return [];
    const metric = this.metric();
    const colors = this.colors();
    const slices: PieSlice[] = ks.children.map((c) => ({
      label: c.name,
      value: this.figuresOf(c)[metric],
      color: colors.get(c.id) ?? '',
      id: c.id,
    }));
    const own = this.figuresOf(ks)[metric] - slices.reduce((s, x) => s + x.value, 0);
    if (own > 0.005) {
      slices.push({
        label: this.i18n.translate('budget.dash.ownShare', { name: ks.name }),
        value: own,
        color: 'var(--color-text-subtle)',
      });
    }
    return slices.filter((s) => s.value > 0);
  });

  metricLabel(m: DistributionMetric | SunburstMetric): string {
    return this.figureLabel(m);
  }

  /** The choices of the metric chip. */
  readonly metricOptions = computed(() =>
    this.metrics.map((m) => ({ value: m, label: this.metricLabel(m) })),
  );

  onMetricChange(value: string): void {
    this.metric.set(value as DistributionMetric);
  }

  /** "Auslastung je Budget": the direct sub cost centres, or the cost centre itself when
   *  it has none. */
  readonly usageRows = computed<UsageRow[]>(() => {
    const ks = this.selectedKs();
    if (!ks) return [];
    const nodes = ks.children.length ? ks.children : [ks];
    const colors = this.colors();
    return nodes.map((node) => {
      const f = this.figuresOf(node);
      const total = f.available + f.committed;
      return {
        node,
        color: colors.get(node.id) ?? '',
        figures: f,
        percent: utilisation(f),
        segments: [
          { value: f.expended, tone: f.available < 0 ? 'error' : 'filled' },
          { value: f.bound, tone: f.available < 0 ? 'error' : 'second' },
        ],
        total: total > 0 ? total : null,
      };
    });
  });

  /** The screen-reader text of a utilisation bar. */
  usageLabel(row: UsageRow): string {
    const f = row.figures;
    return this.i18n.translate('budget.dash.usageLabel', {
      percent: row.percent ?? 0,
      expended: this.money(f.expended, row.node.currency),
      bound: this.money(f.bound, row.node.currency),
      total: this.money(f.available + f.committed, row.node.currency),
    });
  }

  // ---------------------------------------------------------------- applications

  /** The applications of the selected cost centre and its subtree; `null` while loading. */
  readonly apps = signal<BudgetApplication[] | null>(null);
  readonly appsError = signal(false);
  private readonly appsKey = new Subject<{ ks: string; fy: string }>();

  /** The newest applications first, at most {@link APPS_SHOWN}. */
  readonly appRows = computed<AppRow[]>(() => {
    const list = this.apps() ?? [];
    const byId = this.nodeById();
    return [...list]
      .sort((a, b) => b.createdAt.localeCompare(a.createdAt))
      .slice(0, APPS_SHOWN)
      .map((app) => ({
        app,
        title: this.titleOf(app),
        statusLabel: app.stateLabel ? this.resolveLabel(app.stateLabel) || null : null,
        statusKind: flowColorKind(app.stateColor),
        costCentre: app.budgetId ? (byId.get(app.budgetId)?.name ?? null) : null,
      }));
  });

  /** Application title. It falls back to "Ohne Titel" when no title is set. */
  titleOf(app: Pick<BudgetApplication, 'title'>): string {
    return app.title?.trim() || this.i18n.translate('applications.list.untitled');
  }

  /** Resolve an i18n label map in the active locale. It falls back to de, then en,
   *  then the first entry. */
  private resolveLabel(map: Record<string, string>): string {
    return map[this.i18n.locale()] || map['de'] || map['en'] || Object.values(map)[0] || '';
  }

  // ---------------------------------------------------------------- overview (sunburst)

  readonly overviewOpen = signal(false);
  readonly overviewMetric = signal<SunburstMetric>('allocated');
  readonly overviewMetrics: SunburstMetric[] = ['allocated', 'available', 'expended'];
  /** Root of the sunburst: the cost centre that is selected now. */
  readonly overviewRoot = computed(() => this.selectedKs());

  /** Subtree sum of a metric. It uses the same calculation as the sunburst. */
  private metricTotal(node: BudgetTreeNode, metric: SunburstMetric): number {
    const valueOf = (n: BudgetTreeNode): number => this.figuresOf(n)[metric];
    const subtree = (n: BudgetTreeNode): number => {
      const children = n.children.reduce((s, c) => s + subtree(c), 0);
      const own = Math.max(0, valueOf(n) - n.children.reduce((s, c) => s + valueOf(c), 0));
      return own + children;
    };
    return subtree(node);
  }

  /** Only metrics WITH data get a tab. */
  readonly visibleOverviewMetrics = computed<SunburstMetric[]>(() => {
    const root = this.overviewRoot();
    if (!root) return [];
    return this.overviewMetrics.filter((m) => this.metricTotal(root, m) > 0);
  });

  /** Selected metric. It falls back to a visible metric when its data is gone. */
  readonly activeOverviewMetric = computed<SunburstMetric>(() => {
    const visible = this.visibleOverviewMetrics();
    const current = this.overviewMetric();
    return visible.includes(current) ? current : (visible[0] ?? 'allocated');
  });

  onOverviewPick(id: string): void {
    this.overviewOpen.set(false);
    this.selectKs(id);
  }

  // ---------------------------------------------------------------- selection + URL

  /**
   * The query params to resolve the selection from.
   *
   * A field rather than `route.snapshot`, because the snapshot is read while the tree
   * and the fiscal years are still arriving: by then the reader may already have been
   * sent somewhere else, and the restore would answer the URL the page opened with
   * instead of the one it is on.
   */
  private urlParams: ParamMap = this.route.snapshot.queryParamMap;

  /** Outstanding fiscal-year requests. See `resolveSelection` and `emptyReason`. */
  private readonly pendingFiscalYears = signal(0);

  constructor() {
    this.appsKey
      .pipe(
        switchMap(({ ks, fy }) =>
          this.api.applications(ks as Uuid, fy || undefined).pipe(
            map((list) => ({ list, failed: false })),
            catchError(() => of({ list: [] as BudgetApplication[], failed: true })),
          ),
        ),
        takeUntilDestroyed(),
      )
      .subscribe(({ list, failed }) => {
        this.apps.set(list);
        this.appsError.set(failed);
      });

    this.load();

    // The palette can send us here while we are already here. The router keeps this
    // component alive for a query-string-only change, so without this the URL named one
    // cost centre and the page went on showing another.
    this.route.queryParamMap.pipe(takeUntilDestroyed()).subscribe((qp) => {
      this.urlParams = qp;
      this.applyUrlSelection();
    });
  }

  money(value: string | number | null | undefined, currency = 'EUR'): string {
    const n = value == null || value === '' ? 0 : Number(value);
    return new Intl.NumberFormat(this.i18n.formatLocale(), {
      style: 'currency',
      currency: currency || 'EUR',
    }).format(n);
  }

  /** Whole currency units, for the tree and the charts. */
  moneyShort(value: number, currency = 'EUR'): string {
    return new Intl.NumberFormat(this.i18n.formatLocale(), {
      style: 'currency',
      currency: currency || 'EUR',
      maximumFractionDigits: 0,
    }).format(value);
  }

  private load(): void {
    this.loading.set(true);
    this.error.set(false);
    this.api.tree().subscribe({
      next: (tree) => {
        this.tree.set(tree);
        this.loading.set(false);
        // Forest roots. They can be sub cost centres. A hidden root is not selectable.
        const tops = tree.filter((n) => !n.hiddenInBudget);
        // The fiscal years of every root load in parallel; one failure does not stop the
        // others. The counter tells "this root has no years" from "its years have not
        // arrived yet".
        this.pendingFiscalYears.set(tops.length);
        for (const top of tops) {
          this.api.listFiscalYears(top.id as Uuid).subscribe({
            next: (fys) => {
              this.fiscalYearsByBudget.update((m) => ({ ...m, [top.id]: fys }));
              this.pendingFiscalYears.update((n) => n - 1);
              this.restoreOrDefault(tops);
            },
            error: () => {
              this.pendingFiscalYears.update((n) => n - 1);
              this.restoreOrDefault(tops);
            },
          });
        }
        if (tops.length) this.restoreOrDefault(tops);
      },
      error: () => {
        this.error.set(true);
        this.loading.set(false);
      },
    });
  }

  /** Restore the first selection from the query params. Else take the first root and
   *  its first fiscal year. */
  private restored = false;
  private restoreOrDefault(tops: BudgetTreeNode[]): void {
    if (this.restored || !tops.length) return;
    const next = this.resolveSelection(tops);
    if (next === null) return; // not loaded yet, try again later
    this.restored = true;
    this.setSelection(next.budgetId, next.ksId, next.fyId);
  }

  /**
   * Follow the URL after the first restore, so a link into this page works while the
   * reader is already on it.
   *
   * The global search sends a cost centre here as `/budget?ks=…`, and the router keeps
   * this component alive for a query-string-only change. `restoreOrDefault` cannot do
   * this job: it is latched, because its OTHER job is to pick a default exactly once
   * while the tree and the fiscal years trickle in.
   */
  private applyUrlSelection(): void {
    const tops = this.tree().filter((n) => !n.hiddenInBudget);
    const next = this.resolveSelection(tops);
    if (next === null) return; // nothing loaded yet; the restore will pick it up
    if (
      next.budgetId === this.selectedBudgetId() &&
      next.ksId === this.selectedKsId() &&
      next.fyId === this.selectedFyId()
    ) {
      return;
    }
    this.restored = true;
    this.setSelection(next.budgetId, next.ksId, next.fyId);
  }

  /**
   * What the current URL selects, or `null` while the data it names is still arriving.
   *
   * One resolver for both entry points, so a deep link cannot mean one thing on arrival
   * and another when it is followed later.
   */
  private resolveSelection(
    tops: BudgetTreeNode[],
  ): { budgetId: string; ksId: string; fyId: string } | null {
    if (!tops.length) return null;
    const withFy = tops.filter((t) => (this.fiscalYearsByBudget()[t.id]?.length ?? 0) > 0);
    if (!withFy.length) return null; // no fiscal year loaded yet, try again later
    const qp = this.urlParams;
    const selectable = (id: string | null): boolean =>
      !!id && !!this.nodeById().get(id) && (this.fiscalYearsByBudget()[id]?.length ?? 0) > 0;

    const ks = qp.get('ks');
    const qpBudget = qp.get('budget');
    // A search hit is `?ks=…` alone, so the root comes from the cost centre itself when
    // the URL does not name one.
    const derived = ks && this.nodeById().get(ks) ? this.rootOf(ks) : null;
    const wanted = selectable(qpBudget) ? qpBudget : selectable(derived) ? derived : null;
    // A URL that names a root whose years have not landed yet must WAIT rather than
    // settle for the first root that happens to be ready: the choice is latched.
    if (wanted === null && (ks || qpBudget) && this.pendingFiscalYears() > 0) return null;
    const budgetId = wanted ?? withFy[0].id;

    // Both ways to `budgetId` above require at least one year, so `fys[0]` exists.
    const fys = this.fiscalYearsByBudget()[budgetId];
    const fy = qp.get('fy');
    return {
      budgetId,
      ksId: ks && this.nodeById().get(ks) ? ks : budgetId,
      fyId: fy && fys.some((f) => f.id === fy) ? fy : fys[0].id,
    };
  }

  /** The root a cost centre hangs under. */
  private rootOf(id: string): string | null {
    const map = this.nodeById();
    let node = map.get(id) ?? null;
    while (node?.parentId) {
      const parent = map.get(node.parentId);
      if (!parent) break;
      node = parent;
    }
    return node?.id ?? null;
  }

  /** The one place that changes the selection: it opens the path in the tree and loads
   *  the applications of the new cost centre and year. */
  private setSelection(budgetId: string, ksId: string, fyId: string): void {
    const changed = ksId !== this.selectedKsId() || fyId !== this.selectedFyId();
    this.selectedBudgetId.set(budgetId);
    this.selectedKsId.set(ksId);
    this.selectedFyId.set(fyId);
    if (ksId) this.expandPath(ksId);
    if (changed || this.apps() === null) this.loadApps();
  }

  private loadApps(): void {
    const ks = this.selectedKsId();
    if (!ks) {
      this.apps.set([]);
      return;
    }
    this.apps.set(null);
    this.appsError.set(false);
    this.appsKey.next({ ks, fy: this.selectedFyId() });
  }

  private syncUrl(): void {
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: {
        budget: this.selectedBudgetId() || null,
        ks: this.selectedKsId() || null,
        fy: this.selectedFyId() || null,
      },
      queryParamsHandling: 'merge',
      replaceUrl: true,
    });
  }

  /** Select a cost centre. A node under another root switches the root and keeps the
   *  start year where that root has it. */
  selectKs(id: string): void {
    const root = this.rootOf(id) ?? id;
    if (root !== this.selectedBudgetId()) {
      const fys = this.fiscalYearsByBudget()[root] ?? [];
      const fy = this.fyIdFor(root) || (fys[0]?.id ?? '');
      this.setSelection(root, id, fy);
    } else {
      this.setSelection(root, id, this.selectedFyId());
    }
    this.navOpen.set(false);
    this.syncUrl();
  }

  /** Keyboard focus on a tree row scrolls the row into view, clear of the fades. */
  revealRow(event: FocusEvent): void {
    const row = (event.target as HTMLElement | null)?.closest<HTMLElement>('.tn');
    row?.scrollIntoView?.({ block: 'nearest' });
  }

  drillInto(node: BudgetTreeNode): void {
    this.selectKs(node.id);
  }

  /** Pick a fiscal year of the selected root. */
  selectYear(fyId: string): void {
    if (fyId === this.selectedFyId()) return;
    this.setSelection(this.selectedBudgetId(), this.selectedKsId(), fyId);
    this.syncUrl();
  }

  openApplications(): void {
    void this.router.navigate(['/applications'], { queryParams: { budget: this.selectedKsId() } });
  }

  /** The actions of the page, as the "more" menu of a phone. */
  actionSections(): RowMenuSection[] {
    const items: RowMenuItem[] = [];
    if (this.canExport()) {
      items.push({ id: 'export', label: this.i18n.translate('budget.dash.export'), icon: 'download' });
    }
    if (this.canSeeBookings()) {
      items.push({ id: 'bookings', label: this.i18n.translate('budget.usage.viewExpenses'), icon: 'receipt' });
    }
    return [{ items }];
  }

  onAction(item: RowMenuItem): void {
    if (item.id === 'export') this.onExport();
    else if (item.id === 'bookings') this.openBookings();
  }

  openBookings(): void {
    void this.router.navigate(['/expenses'], { queryParams: { budget: this.selectedKsId() } });
  }

  onExport(): void {
    if (this.exporting()) return;
    this.exporting.set(true);
    this.api
      .exportXlsx({
        node: this.selectedKsId() || undefined,
        fiscalYear: this.selectedFyId() || undefined,
      })
      .subscribe({
        next: (blob) => {
          downloadBlob(blob, 'budget.xlsx');
          this.exporting.set(false);
        },
        error: () => this.exporting.set(false),
      });
  }
}

/** The allocation view as numbers. Money is a string on the wire. */
function toFigures(a: BudgetAllocationView): Figures {
  return {
    allocated: Number(a.allocated),
    requested: Number(a.requested),
    bound: Number(a.bound),
    expended: Number(a.expended),
    income: Number(a.income),
    committed: Number(a.committed),
    available: Number(a.available),
  };
}

/** Utilisation in percent: committed / (allocated + income), where allocated + income =
 *  available + committed. `null` when there is nothing to use. */
export function utilisation(f: Figures): number | null {
  const total = f.available + f.committed;
  return total > 0 ? Math.round((f.committed / total) * 100) : null;
}
