import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type { Uuid } from '@core/api/models';
import {
  ButtonComponent,
  CellDirective,
  type ColumnDef,
  DataTableComponent,
  IconComponent,
} from '@stupa-makers/ui-kit';
import { AuthService } from '@core/auth/auth.service';
import { downloadBlob } from '@shared/download.util';
import {
} from '../applications/applications-table.component';
import {
  BudgetTreeApi,
  type BudgetApplication,
  type BudgetTreeNode,
  type FiscalYear,
} from './budget-tree.api';
import { SimplifyPathPipe } from '@shared/budget-path';
import {
  BudgetYearTreeComponent,
  type BudgetYearSelection,
} from './budget-year-tree.component';
import { BudgetPieComponent, type PieSlice } from './budget-pie.component';
import { BudgetSunburstComponent, type SunburstMetric } from './budget-sunburst.component';
import { PALETTE } from './budget-year-tree.component';
import { DialogComponent } from '@stupa-makers/ui-kit';

/** A tree row in the usage section. */
interface UsageRow {
  node: BudgetTreeNode;
  depth: number;
  allocated: number;
  committed: number;
  /** Bound: the accepted applications minus the committed expenses. */
  bound: number;
  /** Expended: the actual expenses. */
  expended: number;
  income: number;
  requested: number;
  available: number;
  /** committed/(available+committed) as a percentage (null when denominator is 0). */
  percent: number | null;
}

/**
 * Budget statistics as a drilldown over the cost center tree.
 *
 * Left: the budget to fiscal year navigation tree. Middle: the breadcrumbs
 * (depth > 0), the usage table of the selected cost center (allocated, committed,
 * requested, available) and the applications. Right: stacked pie charts over the
 * direct sub cost centers. The query params hold the selection, so the view is
 * shareable as a link.
 */
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';

@Component({
  selector: 'app-budget-dashboard',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    PageHeaderComponent,
    FormsModule,
    TranslatePipe,
    SimplifyPathPipe,
    ButtonComponent,
    DataTableComponent,
    CellDirective,
    IconComponent,
    BudgetYearTreeComponent,
    BudgetPieComponent,
    BudgetSunburstComponent,
    DialogComponent,
      RouterLink,
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

  readonly canExport = computed(() => this.auth.can('budget.export'));
  readonly exporting = signal(false);

  readonly loading = signal(true);
  readonly error = signal(false);
  readonly tree = signal<BudgetTreeNode[]>([]);
  /** Fiscal years per top budget (for the left tree). */
  readonly fiscalYearsByBudget = signal<Record<Uuid, FiscalYear[]>>({});

  readonly selectedBudgetId = signal('');
  readonly selectedKsId = signal('');
  readonly selectedFyId = signal('');

  /** Mobile (<=768px): the left tree picker collapses. Desktop ignores this flag,
   *  because CSS hides the toggle there and always shows the tree. */
  readonly navOpen = signal(false);

  /** Mobile toggle label: selected budget + fiscal year, else a generic title. */
  readonly navToggleLabel = computed(() => {
    const budget = this.nodeById().get(this.selectedBudgetId());
    if (!budget) return this.i18n.translate('budget.tree.navTitle');
    const fy = (this.fiscalYearsByBudget()[this.selectedBudgetId()] ?? []).find(
      (f) => f.id === this.selectedFyId(),
    );
    return fy ? `${budget.name} · ${fy.display}` : budget.name;
  });

  toggleNav(): void {
    this.navOpen.update((v) => !v);
  }

  /** Tree without the hidden cost centers. `hiddenInBudget` removes the node and
   *  its subtree from ALL views of the budget tab. This changes the display only.
   *  The values still count in the parent rollups. */
  private readonly visibleTree = computed<BudgetTreeNode[]>(() => {
    const prune = (nodes: BudgetTreeNode[]): BudgetTreeNode[] =>
      nodes
        .filter((n) => !n.hiddenInBudget)
        .map((n) => ({ ...n, children: prune(n.children) }));
    return prune(this.tree());
  });

  /** Roots for the left tree: the forest roots of the server response. The full
   *  view gives the top budgets. A gremium scope gives the assigned sub cost
   *  centers. Only roots WITH a fiscal year appear. The fiscal-year endpoint
   *  resolves a sub cost center to its top-level ancestor. */
  readonly tops = computed(() => {
    const fy = this.fiscalYearsByBudget();
    return this.visibleTree().filter((n) => (fy[n.id]?.length ?? 0) > 0);
  });

  private readonly nodeById = computed(() => {
    const map = new Map<string, BudgetTreeNode>();
    const walk = (nodes: BudgetTreeNode[]): void => {
      for (const n of nodes) {
        map.set(n.id, n);
        walk(n.children);
      }
    };
    walk(this.visibleTree());
    return map;
  });

  private readonly selectedKs = computed(() => this.nodeById().get(this.selectedKsId()) ?? null);

  /** Breadcrumbs from the top budget to the current cost center. */
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

  private alloc(node: BudgetTreeNode): number {
    const a = node.byFiscalYear.find((x) => x.fiscalYearId === this.selectedFyId());
    return a ? Number(a.allocated) : 0;
  }
  private committedOf(node: BudgetTreeNode): number {
    const a = node.byFiscalYear.find((x) => x.fiscalYearId === this.selectedFyId());
    return a ? Number(a.committed) : 0;
  }
  private availableOf(node: BudgetTreeNode): number {
    const a = node.byFiscalYear.find((x) => x.fiscalYearId === this.selectedFyId());
    return a ? Number(a.available) : 0;
  }
  private expendedOf(node: BudgetTreeNode): number {
    const a = node.byFiscalYear.find((x) => x.fiscalYearId === this.selectedFyId());
    return a ? Number(a.expended) : 0;
  }

  /** Usage rows: the selected cost center and its subtree, flattened. */
  readonly usageRows = computed<UsageRow[]>(() => {
    const ks = this.selectedKs();
    if (!ks) return [];
    const fy = this.selectedFyId();
    const out: UsageRow[] = [];
    const walk = (node: BudgetTreeNode, depth: number): void => {
      const a = node.byFiscalYear.find((x) => x.fiscalYearId === fy);
      const allocated = a ? Number(a.allocated) : 0;
      const committed = a ? Number(a.committed) : 0;
      const bound = a ? Number(a.bound) : 0;
      const expended = a ? Number(a.expended) : 0;
      const income = a ? Number(a.income) : 0;
      const requested = a ? Number(a.requested) : 0;
      const available = a ? Number(a.available) : 0;
      out.push({
        node,
        depth,
        allocated,
        committed,
        bound,
        expended,
        income,
        requested,
        available,
        percent:
          a && available + committed > 0
            ? Math.round((committed / (available + committed)) * 100)
            : null,
      });
      for (const c of node.children) walk(c, depth + 1);
    };
    walk(ks, 0);
    return out;
  });

  readonly usageColumns = computed<ColumnDef[]>(() => [
    { key: 'node', label: this.i18n.translate('budget.tree.col.node') },
    { key: 'bar', label: this.i18n.translate('budget.usage.bar'), width: '10rem' },
    { key: 'requested', label: this.i18n.translate('budget.tree.col.requested'), align: 'end' },
    { key: 'bound', label: this.i18n.translate('budget.tree.col.bound'), align: 'end' },
    { key: 'expended', label: this.i18n.translate('budget.tree.col.expended'), align: 'end' },
    { key: 'available', label: this.i18n.translate('budget.tree.col.available'), align: 'end' },
  ]);

  /** Application title. It falls back to the short id when no title is set. */
  titleOf(app: BudgetApplication): string {
    return app.title?.trim() || `${this.shortId(app.applicationId)}…`;
  }

  /** Resolve an i18n label map in the active locale. It falls back to de, then en,
   *  then the first entry. */
  private resolveLabel(map: Record<string, string>): string {
    return map[this.i18n.locale()] || map['de'] || map['en'] || Object.values(map)[0] || '';
  }
  readonly usageRowId = (r: unknown): string => (r as UsageRow).node.id;

  private color(node: BudgetTreeNode, idx: number): string {
    return node.color ?? PALETTE[idx % PALETTE.length];
  }
  private pie(metric: (n: BudgetTreeNode) => number): PieSlice[] {
    const ks = this.selectedKs();
    if (!ks) return [];
    const slices: PieSlice[] = ks.children.map((c, i) => ({
      label: c.name,
      value: metric(c),
      color: this.color(c, i),
      id: c.id,
    }));
    // Own share of the node, the part not distributed to the children. It becomes
    // its own segment with the name and the color of the open cost center.
    const own = metric(ks) - slices.reduce((s, x) => s + x.value, 0);
    if (own > 0.005) {
      slices.push({
        label: ks.name,
        value: own,
        color: ks.color ?? PALETTE[0],
      });
    }
    return slices.filter((s) => s.value > 0);
  }
  readonly allocPie = computed<PieSlice[]>(() => this.pie((n) => this.alloc(n)));
  readonly committedPie = computed<PieSlice[]>(() => this.pie((n) => this.committedOf(n)));
  readonly availablePie = computed<PieSlice[]>(() => this.pie((n) => this.availableOf(n)));
  readonly expendedPie = computed<PieSlice[]>(() => this.pie((n) => this.expendedOf(n)));

  readonly overviewOpen = signal(false);
  readonly overviewMetric = signal<SunburstMetric>('allocated');
  readonly overviewMetrics: SunburstMetric[] = ['allocated', 'available', 'expended'];
  /** Root of the sunburst: the cost center that is selected now. */
  readonly overviewRoot = computed(() => this.selectedKs());

  /** Subtree sum of a metric. It uses the same calculation as the sunburst. */
  private metricTotal(node: BudgetTreeNode, metric: SunburstMetric): number {
    const valueOf = (n: BudgetTreeNode): number => {
      const a = n.byFiscalYear.find((x) => x.fiscalYearId === this.selectedFyId());
      return a ? Number(a[metric]) : 0;
    };
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

  metricLabel(m: SunburstMetric): string {
    return this.i18n.translate(`budget.overview.metric.${m}` as TranslationKey);
  }

  constructor() {
    this.load();
  }

  money(value: string | number | null | undefined, currency = 'EUR'): string {
    const n = value == null || value === '' ? 0 : Number(value);
    return new Intl.NumberFormat(this.i18n.locale(), { style: 'currency', currency }).format(n);
  }
  /** Row total budget = available + bound + expended (= allocated + income).
   *  This is the reference value for the usage bar. Income-funded cost centers
   *  then stay at or below 100%. */
  private usageTotal(row: UsageRow): number {
    return row.available + row.committed;
  }
  /** Bound share of the total budget, drawn in light gray. */
  boundPct(row: UsageRow): number {
    const total = this.usageTotal(row);
    return total > 0 ? Math.max(0, Math.min(100, (row.bound / total) * 100)) : 0;
  }
  /** Expended share of the total budget, drawn in the primary color. */
  expendedPct(row: UsageRow): number {
    const total = this.usageTotal(row);
    return total > 0 ? Math.max(0, Math.min(100, (row.expended / total) * 100)) : 0;
  }
  shortId(id: Uuid): string {
    return id.slice(0, 8);
  }
  stageLabel(stage: string | null): string {
    if (!stage) return '—';
    return this.i18n.translate(`budget.stage.${stage}` as TranslationKey);
  }

  private load(): void {
    this.loading.set(true);
    this.error.set(false);
    this.api.tree().subscribe({
      next: (tree) => {
        this.tree.set(tree);
        this.loading.set(false);
        // Forest roots. They can be sub cost centers. A hidden root is not
        // selectable in the tab.
        const tops = tree.filter((n) => !n.hiddenInBudget);
        // Load the fiscal years of all top budgets for the left tree. The requests
        // run in parallel and a failure of one does not stop the others.
        for (const top of tops) {
          this.api.listFiscalYears(top.id as Uuid).subscribe({
            next: (fys) => {
              this.fiscalYearsByBudget.update((m) => ({ ...m, [top.id]: fys }));
              this.restoreOrDefault(tops);
            },
            error: () => this.restoreOrDefault(tops),
          });
        }
        if (tops.length) {
          this.restoreOrDefault(tops);
        }
      },
      error: () => {
        this.error.set(true);
        this.loading.set(false);
      },
    });
  }

  /** Restore the first selection from the query params. Else take the first budget
   *  and its first fiscal year. */
  private restored = false;
  private restoreOrDefault(tops: BudgetTreeNode[]): void {
    if (this.restored || !tops.length) return;
    // Only budgets with a fiscal year are selectable in the budget tab.
    const withFy = tops.filter(
      (t) => (this.fiscalYearsByBudget()[t.id]?.length ?? 0) > 0,
    );
    if (!withFy.length) return; // no fiscal year loaded yet, try again later
    const qp = this.route.snapshot.queryParamMap;
    const qpBudget = qp.get('budget');
    const budgetId =
      qpBudget &&
      this.nodeById().get(qpBudget) &&
      (this.fiscalYearsByBudget()[qpBudget]?.length ?? 0) > 0
        ? qpBudget
        : withFy[0].id;
    const fys = this.fiscalYearsByBudget()[budgetId];
    if (fys === undefined) return; // not loaded yet, try again later
    this.restored = true;
    const ksId = qp.get('ks') && this.nodeById().get(qp.get('ks')!) ? qp.get('ks')! : budgetId;
    const fyId = qp.get('fy') && fys.some((f) => f.id === qp.get('fy')) ? qp.get('fy')! : (fys[0]?.id ?? '');
    this.selectedBudgetId.set(budgetId);
    this.selectedKsId.set(ksId);
    this.selectedFyId.set(fyId);
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

  selectBudget(id: string): void {
    this.selectedBudgetId.set(id);
    this.selectedKsId.set(id); // drilldown starts at the root
    const fys = this.fiscalYearsByBudget()[id] ?? [];
    this.selectedFyId.set(fys[0]?.id ?? '');
    this.syncUrl();
  }

  onYearPicked(sel: BudgetYearSelection): void {
    this.selectedBudgetId.set(sel.budgetId);
    this.selectedKsId.set(sel.budgetId);
    this.selectedFyId.set(sel.fiscalYearId);
    // Mobile: collapse the picker again after the user picks a year. Desktop keeps
    // the tree open.
    this.navOpen.set(false);
    this.syncUrl();
  }

  selectKs(id: string): void {
    this.selectedKsId.set(id);
    this.syncUrl();
  }

  drillInto(node: BudgetTreeNode): void {
    this.selectKs(node.id);
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
