import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
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
} from '@shared/ui';
import { AuthService } from '@core/auth/auth.service';
import { downloadBlob } from '@shared/download.util';
import {
  ApplicationsTableComponent,
  type ApplicationRow,
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
import { PALETTE } from './budget-year-tree.component';

/** Eine Baumzeile im Auslastungs-Teil. */
interface UsageRow {
  node: BudgetTreeNode;
  depth: number;
  allocated: number;
  committed: number;
  /** Gebunden: angenommene Anträge minus gebundene Ausgaben (#25). */
  bound: number;
  /** Ausgegeben: tatsächliche Ausgaben (#25). */
  expended: number;
  /** Einnahmen (#25). */
  income: number;
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
    TranslatePipe,
    SimplifyPathPipe,
    ButtonComponent,
    DataTableComponent,
    CellDirective,
    IconComponent,
    BudgetYearTreeComponent,
    BudgetPieComponent,
    ApplicationsTableComponent,
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
  readonly applications = signal<BudgetApplication[]>([]);
  /** HHJ je Top-Budget (für den linken Baum). */
  readonly fiscalYearsByBudget = signal<Record<Uuid, FiscalYear[]>>({});

  readonly selectedBudgetId = signal('');
  readonly selectedKsId = signal('');
  readonly selectedFyId = signal('');

  /** Mobil (≤768px): linker Baum-Picker einklappbar — Desktop ignoriert das Flag,
   *  dort blendet CSS den Toggle aus und zeigt den Baum immer. */
  readonly navOpen = signal(false);

  /** Label des Mobil-Toggles: gewähltes Budget + HHJ, sonst generischer Titel. */
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

  /** Top-Budgets (Wurzeln) für den linken Baum — nur Budgets **mit** Haushaltsjahr
   *  (#11): ohne HHJ gibt es im Budget-Tab nichts auszuwerten, also ausblenden. */
  readonly tops = computed(() => {
    const fy = this.fiscalYearsByBudget();
    return this.tree().filter(
      (n) => n.parentId === null && (fy[n.id]?.length ?? 0) > 0,
    );
  });

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
    { key: 'bound', label: this.i18n.translate('budget.tree.col.bound'), align: 'end' },
    { key: 'expended', label: this.i18n.translate('budget.tree.col.expended'), align: 'end' },
    { key: 'available', label: this.i18n.translate('budget.tree.col.available'), align: 'end' },
  ]);
  /** Antrags-Zeilen für die geteilte Tabelle (Optik wie ``/applications``). */
  readonly appRows = computed<ApplicationRow[]>(() =>
    this.applications().map((a) => ({
      id: a.applicationId,
      title: this.titleOf(a),
      typeLabel: a.pathKey,
      stateLabel: a.stateLabel
        ? this.resolveLabel(a.stateLabel)
        : a.stage
          ? this.stageLabel(a.stage)
          : null,
      stateColor: a.stateColor ?? null,
      amount: a.amount,
      currency: a.currency,
      createdAt: a.createdAt,
    })),
  );

  /** Antragstitel mit Fallback (kurze Id), wenn kein Titel gesetzt ist. */
  titleOf(app: BudgetApplication): string {
    return app.title?.trim() || `${this.shortId(app.applicationId)}…`;
  }

  /** i18n-Label-Map in der aktiven Sprache auflösen (Fallback de/en/erstes). */
  private resolveLabel(map: Record<string, string>): string {
    return map[this.i18n.locale()] || map['de'] || map['en'] || Object.values(map)[0] || '';
  }
  readonly usageRowId = (r: unknown): string => (r as UsageRow).node.id;

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
    // Eigenanteil des Knotens (nicht an Kinder weiterverteilt) — als eigenes Segment
    // mit dem **Namen** und der **Farbe** der offenen Kostenstelle (#budget).
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
  /** Gebundener Anteil (noch nicht ausgegeben) als % der Allokation — hellgrau. */
  boundPct(row: UsageRow): number {
    if (!row.allocated) return 0;
    return Math.max(0, Math.min(100, (row.bound / row.allocated) * 100));
  }
  /** Ausgegebener Anteil als % der Allokation — primary. */
  expendedPct(row: UsageRow): number {
    if (!row.allocated) return 0;
    return Math.max(0, Math.min(100, (row.expended / row.allocated) * 100));
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
    // Nur Budgets mit Haushaltsjahr sind im Budget-Tab auswählbar (#11).
    const withFy = tops.filter(
      (t) => (this.fiscalYearsByBudget()[t.id]?.length ?? 0) > 0,
    );
    if (!withFy.length) return; // noch keines mit HHJ (geladen) → später
    const qp = this.route.snapshot.queryParamMap;
    const qpBudget = qp.get('budget');
    const budgetId =
      qpBudget &&
      this.nodeById().get(qpBudget) &&
      (this.fiscalYearsByBudget()[qpBudget]?.length ?? 0) > 0
        ? qpBudget
        : withFy[0].id;
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
    // Mobil: nach der Jahr-Wahl den Picker wieder einklappen (Desktop egal).
    this.navOpen.set(false);
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

  // --- Export ---------------------------------------------------------------
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
