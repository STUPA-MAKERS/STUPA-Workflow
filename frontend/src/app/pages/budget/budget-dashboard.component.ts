import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type { Uuid } from '@core/api/models';
import {
  BadgeComponent,
  ButtonComponent,
  DialogComponent,
  SelectComponent,
  type SelectOption,
} from '@shared/ui';
import {
  BudgetTreeApi,
  type BudgetApplication,
  type BudgetTreeNode,
  type FiscalYear,
} from './budget-tree.api';

/** Eine Baumzeile im linken Auslastungs-Teil. */
interface UsageRow {
  node: BudgetTreeNode;
  depth: number;
  allocated: number;
  committed: number;
  available: number;
  /** committed/allocated in Prozent (null wenn keine Zuteilung). */
  percent: number | null;
}

/**
 * Budget-Statistik (#17) als **Drilldown** über den Kostenstellen-Baum.
 *
 * Oben Filter Budget → Kostenstelle (Tree-Dropdown) → Haushaltsjahr + Breadcrumbs.
 * Links: Baum-Tabelle der gewählten Kostenstelle + Unterbaum mit Verbrauchs-Balken
 * (gebunden vs. zugeteilt = Roll-Down/Roll-Up). Rechts: konkrete Anträge der
 * aktuellen Kostenstelle **und ihres Unterbaums** (klickbar → Antrag-Popover). Ein
 * Klick auf eine Kostenstelle links geht tiefer (aktualisiert das Dropdown).
 */
@Component({
  selector: 'app-budget-dashboard',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    RouterLink,
    TranslatePipe,
    SelectComponent,
    BadgeComponent,
    ButtonComponent,
    DialogComponent,
  ],
  templateUrl: './budget-dashboard.component.html',
  styleUrl: './budget-dashboard.component.scss',
})
export class BudgetDashboardComponent {
  private readonly api = inject(BudgetTreeApi);
  private readonly i18n = inject(I18nService);

  readonly loading = signal(true);
  readonly error = signal(false);
  readonly tree = signal<BudgetTreeNode[]>([]);
  readonly fiscalYears = signal<FiscalYear[]>([]);
  readonly applications = signal<BudgetApplication[]>([]);

  readonly selectedBudgetId = signal('');
  readonly selectedKsId = signal('');
  readonly selectedFyId = signal('');
  readonly dialogApp = signal<BudgetApplication | null>(null);

  /** Schneller Knoten-Lookup (id → Knoten) über den ganzen Baum. */
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

  readonly budgetOptions = computed<SelectOption[]>(() =>
    this.tree().map((n) => ({ value: n.id, label: `${n.key} – ${n.name}` })),
  );

  private readonly selectedTop = computed(() => this.nodeById().get(this.selectedBudgetId()) ?? null);

  /** Kostenstellen-Optionen (Tree-Dropdown) des gewählten Budgets, eingerückt. */
  readonly ksOptions = computed<SelectOption[]>(() => {
    const top = this.selectedTop();
    if (!top) return [];
    const out: SelectOption[] = [];
    const walk = (node: BudgetTreeNode, depth: number): void => {
      const indent = '  '.repeat(depth);
      out.push({ value: node.id, label: `${indent}${node.pathKey} – ${node.name}` });
      for (const c of node.children) walk(c, depth + 1);
    };
    walk(top, 0);
    return out;
  });

  readonly fyOptions = computed<SelectOption[]>(() =>
    this.fiscalYears().map((fy) => ({ value: fy.id, label: fy.label })),
  );

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

  /** Linker Teil: gewählte Kostenstelle + Unterbaum als flache Zeilen mit Balken. */
  readonly usageRows = computed<UsageRow[]>(() => {
    const ks = this.selectedKs();
    if (!ks) return [];
    const fy = this.selectedFyId();
    const out: UsageRow[] = [];
    const walk = (node: BudgetTreeNode, depth: number): void => {
      const a = node.byFiscalYear.find((x) => x.fiscalYearId === fy);
      const allocated = a ? Number(a.allocated) : 0;
      const committed = a ? Number(a.committed) : 0;
      const available = a ? Number(a.available) : 0;
      out.push({
        node,
        depth,
        allocated,
        committed,
        available,
        percent: a && allocated > 0 ? Math.round((committed / allocated) * 100) : null,
      });
      for (const c of node.children) walk(c, depth + 1);
    };
    walk(ks, 0);
    return out;
  });

  constructor() {
    this.load();
  }

  // --- Anzeige-Helfer -------------------------------------------------------
  money(value: string | number | null | undefined, currency = 'EUR'): string {
    const n = value == null || value === '' ? 0 : Number(value);
    return new Intl.NumberFormat(this.i18n.locale(), { style: 'currency', currency }).format(n);
  }

  /** Balkenbreite (committed/allocated, gekappt auf 100 %). */
  barPct(row: UsageRow): number {
    if (!row.allocated) return 0;
    return Math.min(100, Math.round((row.committed / row.allocated) * 100));
  }

  shortId(id: Uuid): string {
    return id.slice(0, 8);
  }

  /** Übersetzte Budget-Stufe (dynamischer Key → typsicher gekapselt). */
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
        const tops = tree.filter((n) => n.parentId === null);
        if (tops.length) this.selectBudget(tops[0].id);
        this.loading.set(false);
        if (!tops.length) this.applications.set([]);
      },
      error: () => {
        this.error.set(true);
        this.loading.set(false);
      },
    });
  }

  selectBudget(id: string): void {
    this.selectedBudgetId.set(id);
    this.selectedKsId.set(id); // Drilldown startet an der Wurzel
    this.api.listFiscalYears(id as Uuid).subscribe({
      next: (fys) => {
        this.fiscalYears.set(fys);
        this.selectedFyId.set(fys[0]?.id ?? '');
        this.reloadApplications();
      },
      error: () => {
        this.fiscalYears.set([]);
        this.selectedFyId.set('');
        this.reloadApplications();
      },
    });
  }

  selectKs(id: string): void {
    this.selectedKsId.set(id);
    this.reloadApplications();
  }

  selectFy(id: string): void {
    this.selectedFyId.set(id);
    this.reloadApplications();
  }

  /** Klick auf eine Kostenstelle links → tiefer ins Detail. */
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
