import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type { Uuid } from '@core/api/models';
import {
  BadgeComponent,
  CellDirective,
  type ColumnDef,
  DataTableComponent,
  DialogComponent,
} from '@shared/ui';
import {
  BudgetTreeApi,
  type BudgetApplication,
  type BudgetTreeNode,
  type FiscalYear,
} from './budget-tree.api';
import {
  BudgetYearTreeComponent,
  type BudgetYearSelection,
} from './budget-year-tree.component';
import { BudgetPieComponent, type PieSlice } from './budget-pie.component';
import { PALETTE } from './budget-year-tree.component';

/** Eine Baumzeile im Auslastungs-Teil. */
interface UsageRow {
  node: BudgetTreeNode;
  depth: number;
  allocated: number;
  committed: number;
  requested: number;
  available: number;
  /** committed/allocated in Prozent (null wenn keine Zuteilung). */
  percent: number | null;
}

/**
 * Budget-Statistik (#17 + #budget-redesign) als Drilldown über den Kostenstellen-Baum.
 *
 * Links: Navigations-Baum Budget zu Haushaltsjahr. Mitte: Breadcrumbs (ab Tiefe>0)
 * plus Auslastungs-Tabelle der gewaehlten Kostenstelle (allocated, committed,
 * beantragt, available) plus Antraege. Rechts: zwei gestapelte Tortendiagramme
 * (Zuteilung, Gebunden) ueber die direkten Unter-Kostenstellen. Auswahl liegt in
 * den Query-Params (teilbar).
 */
@Component({
  selector: 'app-budget-dashboard',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    RouterLink,
    TranslatePipe,
    BadgeComponent,
    DialogComponent,
    DataTableComponent,
    CellDirective,
    BudgetYearTreeComponent,
    BudgetPieComponent,
  ],
  templateUrl: './budget-dashboard.component.html',
  styleUrl: './budget-dashboard.component.scss',
})
export class BudgetDashboardComponent {
  private readonly api = inject(BudgetTreeApi);
  private readonly i18n = inject(I18nService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  readonly loading = signal(true);
  readonly error = signal(false);
  readonly tree = signal<BudgetTreeNode[]>([]);
  readonly applications = signal<BudgetApplication[]>([]);
  /** HHJ je Top-Budget (für den linken Baum). */
  readonly fiscalYearsByBudget = signal<Record<Uuid, FiscalYear[]>>({});

  readonly selectedBudgetId = signal('');
  readonly selectedKsId = signal('');
  readonly selectedFyId = signal('');
  readonly dialogApp = signal<BudgetApplication | null>(null);

  /** Top-Budgets (Wurzeln) für den linken Baum. */
  readonly tops = computed(() => this.tree().filter((n) => n.parentId === null));

  private readonly nodeById = computed(() => {
    const map = new Map<string, BudgetTreeNode>();
    const walk = (nodes: BudgetTreeNode[]): void => {
      for (const n of nodes) {
        map.set(n.id, n);
        walk(n.children);
      }
    };
    walk(this.tree());
    return map;
  });

  private readonly selectedKs = computed(() => this.nodeById().get(this.selectedKsId()) ?? null);

  /** Breadcrumbs vom Top-Budget bis zur aktuellen Kostenstelle. */
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

  /** Auslastungs-Zeilen: gewählte Kostenstelle + Unterbaum, flach. */
  readonly usageRows = computed<UsageRow[]>(() => {
    const ks = this.selectedKs();
    if (!ks) return [];
    const fy = this.selectedFyId();
    const out: UsageRow[] = [];
    const walk = (node: BudgetTreeNode, depth: number): void => {
      const a = node.byFiscalYear.find((x) => x.fiscalYearId === fy);
      const allocated = a ? Number(a.allocated) : 0;
      const committed = a ? Number(a.committed) : 0;
      const requested = a ? Number(a.requested) : 0;
      const available = a ? Number(a.available) : 0;
      out.push({
        node,
        depth,
        allocated,
        committed,
        requested,
        available,
        percent: a && allocated > 0 ? Math.round((committed / allocated) * 100) : null,
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
    { key: 'committed', label: this.i18n.translate('budget.tree.col.committed'), align: 'end' },
    { key: 'available', label: this.i18n.translate('budget.tree.col.available'), align: 'end' },
  ]);
  readonly appColumns = computed<ColumnDef[]>(() => [
    { key: 'title', label: this.i18n.translate('budget.apps.col.title') },
    { key: 'ks', label: this.i18n.translate('budget.apps.col.ks') },
    { key: 'stage', label: this.i18n.translate('budget.apps.col.stage') },
    { key: 'amount', label: this.i18n.translate('budget.apps.col.amount'), align: 'end' },
  ]);

  /** Antragstitel mit Fallback (kurze Id), wenn kein Titel gesetzt ist. */
  titleOf(app: BudgetApplication): string {
    return app.title?.trim() || `${this.shortId(app.applicationId)}…`;
  }
  readonly usageRowId = (r: unknown): string => (r as UsageRow).node.id;
  readonly appRowId = (a: unknown): string => (a as BudgetApplication).applicationId;

  // --- Pie-Daten: direkte Unter-Kostenstellen + Eigenanteil ------------------
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
    }));
    // Eigenanteil des Knotens (nicht an Kinder weiterverteilt).
    const own = metric(ks) - slices.reduce((s, x) => s + x.value, 0);
    if (own > 0.005) {
      slices.push({
        label: this.i18n.translate('budget.pie.own'),
        value: own,
        color: 'var(--color-text-muted)',
      });
    }
    return slices.filter((s) => s.value > 0);
  }
  readonly allocPie = computed<PieSlice[]>(() => this.pie((n) => this.alloc(n)));
  readonly committedPie = computed<PieSlice[]>(() => this.pie((n) => this.committedOf(n)));

  constructor() {
    this.load();
  }

  // --- Anzeige-Helfer -------------------------------------------------------
  money(value: string | number | null | undefined, currency = 'EUR'): string {
    const n = value == null || value === '' ? 0 : Number(value);
    return new Intl.NumberFormat(this.i18n.locale(), { style: 'currency', currency }).format(n);
  }
  barPct(row: UsageRow): number {
    if (!row.allocated) return 0;
    return Math.min(100, Math.round((row.committed / row.allocated) * 100));
  }
  shortId(id: Uuid): string {
    return id.slice(0, 8);
  }
  stageLabel(stage: string | null): string {
    if (!stage) return '—';
    return this.i18n.translate(`budget.stage.${stage}` as TranslationKey);
  }

  // --- Laden ----------------------------------------------------------------
  private load(): void {
    this.loading.set(true);
    this.error.set(false);
    this.api.tree().subscribe({
      next: (tree) => {
        this.tree.set(tree);
        this.loading.set(false);
        const tops = tree.filter((n) => n.parentId === null);
        // HHJ aller Top-Budgets laden (linker Baum) — parallel, fehlertolerant.
        for (const top of tops) {
          this.api.listFiscalYears(top.id as Uuid).subscribe({
            next: (fys) => {
              this.fiscalYearsByBudget.update((m) => ({ ...m, [top.id]: fys }));
              this.restoreOrDefault(tops);
            },
            error: () => this.restoreOrDefault(tops),
          });
        }
        if (!tops.length) {
          this.applications.set([]);
        } else {
          this.restoreOrDefault(tops);
        }
      },
      error: () => {
        this.error.set(true);
        this.loading.set(false);
      },
    });
  }

  /** Erstauswahl aus den Query-Params wiederherstellen, sonst erstes Budget/HHJ. */
  private restored = false;
  private restoreOrDefault(tops: BudgetTreeNode[]): void {
    if (this.restored || !tops.length) return;
    const qp = this.route.snapshot.queryParamMap;
    const budgetId = qp.get('budget') && this.nodeById().get(qp.get('budget')!)
      ? qp.get('budget')!
      : tops[0].id;
    const fys = this.fiscalYearsByBudget()[budgetId];
    if (fys === undefined) return; // noch nicht geladen → später
    this.restored = true;
    const ksId = qp.get('ks') && this.nodeById().get(qp.get('ks')!) ? qp.get('ks')! : budgetId;
    const fyId = qp.get('fy') && fys.some((f) => f.id === qp.get('fy')) ? qp.get('fy')! : (fys[0]?.id ?? '');
    this.selectedBudgetId.set(budgetId);
    this.selectedKsId.set(ksId);
    this.selectedFyId.set(fyId);
    this.reloadApplications();
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
    this.selectedKsId.set(id); // Drilldown startet an der Wurzel
    const fys = this.fiscalYearsByBudget()[id] ?? [];
    this.selectedFyId.set(fys[0]?.id ?? '');
    this.syncUrl();
    this.reloadApplications();
  }

  onYearPicked(sel: BudgetYearSelection): void {
    this.selectedBudgetId.set(sel.budgetId);
    this.selectedKsId.set(sel.budgetId);
    this.selectedFyId.set(sel.fiscalYearId);
    this.syncUrl();
    this.reloadApplications();
  }

  selectKs(id: string): void {
    this.selectedKsId.set(id);
    this.syncUrl();
    this.reloadApplications();
  }

  drillInto(node: BudgetTreeNode): void {
    this.selectKs(node.id);
  }

  private reloadApplications(): void {
    const ks = this.selectedKsId();
    if (!ks) {
      this.applications.set([]);
      return;
    }
    this.api.applications(ks as Uuid, this.selectedFyId() || undefined).subscribe({
      next: (apps) => this.applications.set(apps),
      error: () => this.applications.set([]),
    });
  }

  // --- Popover --------------------------------------------------------------
  openApp(app: BudgetApplication): void {
    this.dialogApp.set(app);
  }
  closeDialog(): void {
    this.dialogApp.set(null);
  }
}
