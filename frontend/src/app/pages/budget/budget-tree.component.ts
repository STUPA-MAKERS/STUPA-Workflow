import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Uuid } from '@core/api/models';
import {
  BadgeComponent,
  ButtonComponent,
  CardComponent,
  CellDirective,
  type ColumnDef,
  DataTableComponent,
  DialogComponent,
  RowDetailDirective,
  SelectComponent,
  type SelectOption,
} from '@shared/ui';
import { ToastService } from '@shared/ui/toast/toast.service';
import { BudgetTreeApi, type BudgetTreeNode, type FiscalYear } from './budget-tree.api';

/** Eine Baumzeile (Knoten + Tiefe für die Einrückung). */
interface Row {
  node: BudgetTreeNode;
  depth: number;
}

/**
 * Budget-/Kostenstellen-Baum-Editor (#9/#22). **Budget-bezogen**: oben ein Budget
 * wählen, darunter dessen Kostenstellen-Unterbaum (`VS-800-40 – …`) bearbeiten.
 *
 * Budgets sind **nicht** an ein Gremium gebunden. **Haushaltsjahre werden INNERHALB
 * des Budgets** angelegt (eigene Karte je gewähltem Budget) — kein globales HHJ-
 * Dropdown. Verfügbar = Roll-Down (Zuteilung), gebunden = Roll-Up (zugeordnete
 * Anträge); die Zuteilung je Knoten ist pro gewähltem HHJ inline editierbar.
 */
@Component({
  selector: 'app-budget-tree',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslatePipe, ButtonComponent, CardComponent, SelectComponent, BadgeComponent, DialogComponent, DataTableComponent, CellDirective, RowDetailDirective],
  templateUrl: './budget-tree.component.html',
  styleUrl: './budget-tree.component.scss',
})
export class BudgetTreeComponent {
  private readonly api = inject(BudgetTreeApi);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly tree = signal<BudgetTreeNode[]>([]);
  readonly fiscalYears = signal<FiscalYear[]>([]);
  readonly selectedTopId = signal('');
  readonly selectedFyId = signal('');
  readonly loading = signal(true);
  readonly loadError = signal(false);

  /** Top-Budget anlegen (kein Gremium — Budgets sind gremium-unabhängig). */
  readonly newTop = signal<{ key: string; name: string }>({ key: '', name: '' });
  /** Unterknoten anlegen: welcher Parent ist aufgeklappt + Entwurf. */
  readonly addingChildOf = signal<Uuid | null>(null);
  readonly childDraft = signal<{ key: string; name: string }>({ key: '', name: '' });
  /** Limit (Zuteilung) je Knoten setzen — per Dialog pro Zeile (#22). */
  readonly limitNode = signal<BudgetTreeNode | null>(null);
  readonly limitValue = signal('');
  /** Haushaltsjahr anlegen — INNERHALB des gewählten Budgets. */
  readonly newFy = signal<{ label: string; startDate: string; endDate: string }>({
    label: '',
    startDate: '',
    endDate: '',
  });

  readonly topOptions = computed<SelectOption[]>(() =>
    this.tree().map((n) => ({ value: n.id, label: `${n.key} – ${n.name}` })),
  );
  readonly fyOptions = computed<SelectOption[]>(() =>
    this.fiscalYears().map((fy) => ({ value: fy.id, label: fy.label })),
  );

  private readonly selectedTop = computed<BudgetTreeNode | null>(
    () => this.tree().find((n) => n.id === this.selectedTopId()) ?? null,
  );

  /** Unterbaum des gewählten Budgets → flache Zeilen (Pre-Order) mit Tiefe. */
  readonly rows = computed<Row[]>(() => {
    const top = this.selectedTop();
    if (!top) return [];
    const out: Row[] = [];
    const walk = (node: BudgetTreeNode, depth: number): void => {
      out.push({ node, depth });
      for (const c of node.children) walk(c, depth + 1);
    };
    walk(top, 0);
    return out;
  });

  readonly columns = computed<ColumnDef[]>(() => [
    { key: 'node', label: this.i18n.translate('budget.tree.col.node') },
    { key: 'allocated', label: this.i18n.translate('budget.tree.col.allocated'), align: 'end' },
    { key: 'committed', label: this.i18n.translate('budget.tree.col.committed'), align: 'end' },
    { key: 'available', label: this.i18n.translate('budget.tree.col.available'), align: 'end' },
    { key: 'actions', label: this.i18n.translate('budget.tree.col.actions'), align: 'end' },
  ]);
  readonly rowId = (r: unknown): string => (r as Row).node.id;
  readonly childExpanded = (r: unknown): boolean => this.addingChildOf() === (r as Row).node.id;

  constructor() {
    this.reload();
  }

  // --- Anzeige-Helfer -------------------------------------------------------
  money(value: string | number | null | undefined, currency: string): string {
    const n = value == null || value === '' ? 0 : Number(value);
    return new Intl.NumberFormat(this.i18n.locale(), { style: 'currency', currency }).format(n);
  }

  alloc(node: BudgetTreeNode) {
    const fy = this.selectedFyId();
    return node.byFiscalYear.find((a) => a.fiscalYearId === fy) ?? null;
  }

  // --- Laden ----------------------------------------------------------------
  private reload(): void {
    this.loading.set(true);
    this.loadError.set(false);
    this.api.tree().subscribe({
      next: (tree) => {
        this.tree.set(tree);
        const tops = tree.filter((n) => n.parentId === null);
        const keep = tops.some((t) => t.id === this.selectedTopId());
        const topId = keep ? this.selectedTopId() : (tops[0]?.id ?? '');
        this.selectedTopId.set(topId);
        if (topId) this.loadFiscalYears(topId);
        else this.fiscalYears.set([]);
        this.loading.set(false);
      },
      error: () => {
        this.loadError.set(true);
        this.loading.set(false);
      },
    });
  }

  /** HHJ des gewählten Budgets laden (sie leben innerhalb des Budgets). */
  private loadFiscalYears(topId: string): void {
    this.api.listFiscalYears(topId as Uuid).subscribe({
      next: (fys) => {
        this.fiscalYears.set(fys);
        if (!fys.some((fy) => fy.id === this.selectedFyId())) this.selectedFyId.set(fys[0]?.id ?? '');
      },
      error: () => this.fiscalYears.set([]),
    });
  }

  selectTop(id: string): void {
    this.selectedTopId.set(id);
    this.selectedFyId.set('');
    this.loadFiscalYears(id);
  }

  // --- Knoten anlegen/löschen ----------------------------------------------
  patchTop<K extends 'key' | 'name'>(key: K, value: string): void {
    this.newTop.update((t) => ({ ...t, [key]: value }));
  }

  createTop(event: Event): void {
    event.preventDefault();
    const t = this.newTop();
    if (!t.key.trim() || !t.name.trim()) return;
    this.api.createNode({ key: t.key.trim(), name: t.name.trim() }).subscribe({
      next: (node) => {
        this.toast.success(this.i18n.translate('budget.tree.toast.created'));
        this.newTop.set({ key: '', name: '' });
        this.selectedTopId.set(node.id);
        this.reload();
      },
      error: () => this.toast.error(this.i18n.translate('budget.tree.toast.failed')),
    });
  }

  startAddChild(node: BudgetTreeNode): void {
    this.addingChildOf.set(node.id);
    this.childDraft.set({ key: '', name: '' });
  }

  cancelAddChild(): void {
    this.addingChildOf.set(null);
  }

  patchChild(key: 'key' | 'name', value: string): void {
    this.childDraft.update((c) => ({ ...c, [key]: value }));
  }

  addChild(parent: BudgetTreeNode): void {
    const c = this.childDraft();
    if (!c.key.trim() || !c.name.trim()) return;
    this.api
      .createNode({ parentId: parent.id, key: c.key.trim(), name: c.name.trim(), currency: parent.currency })
      .subscribe({
        next: () => {
          this.toast.success(this.i18n.translate('budget.tree.toast.created'));
          this.addingChildOf.set(null);
          this.reload();
        },
        error: () => this.toast.error(this.i18n.translate('budget.tree.toast.failed')),
      });
  }

  deleteNode(node: BudgetTreeNode): void {
    this.api.deleteNode(node.id).subscribe({
      next: () => {
        this.toast.success(this.i18n.translate('budget.tree.toast.deleted'));
        this.reload();
      },
      error: () => this.toast.error(this.i18n.translate('budget.tree.toast.deleteFailed')),
    });
  }

  // --- Limit / Zuteilung (Dialog pro Zeile) --------------------------------
  openLimit(node: BudgetTreeNode): void {
    this.limitNode.set(node);
    this.limitValue.set(this.alloc(node)?.allocated ?? '');
  }

  closeLimit(): void {
    this.limitNode.set(null);
  }

  saveLimit(): void {
    const node = this.limitNode();
    const fy = this.selectedFyId();
    if (!node || !fy) return;
    const value = this.limitValue().trim();
    if (value === '') return;
    this.api.setAllocation(node.id, fy as Uuid, value).subscribe({
      next: () => {
        this.toast.success(this.i18n.translate('budget.tree.toast.allocated'));
        this.limitNode.set(null);
        this.reload();
      },
      error: () => this.toast.error(this.i18n.translate('budget.tree.toast.failed')),
    });
  }

  // --- Haushaltsjahre (innerhalb des Budgets) ------------------------------
  patchFy<K extends 'label' | 'startDate' | 'endDate'>(key: K, value: string): void {
    this.newFy.update((f) => ({ ...f, [key]: value }));
  }

  createFiscalYear(event: Event): void {
    event.preventDefault();
    const top = this.selectedTopId();
    const f = this.newFy();
    if (!top || !f.label.trim() || !f.startDate || !f.endDate) return;
    this.api
      .createFiscalYear(top as Uuid, { label: f.label.trim(), startDate: f.startDate, endDate: f.endDate })
      .subscribe({
        next: () => {
          this.toast.success(this.i18n.translate('budget.tree.toast.fyCreated'));
          this.newFy.set({ label: '', startDate: '', endDate: '' });
          this.loadFiscalYears(top);
        },
        error: () => this.toast.error(this.i18n.translate('budget.tree.toast.fyFailed')),
      });
  }
}
