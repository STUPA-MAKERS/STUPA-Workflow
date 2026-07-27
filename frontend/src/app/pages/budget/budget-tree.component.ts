import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Uuid } from '@core/api/models';
import {
  ButtonComponent,
  CellDirective,
  type ColumnDef,
  CurrencyInputComponent,
  DataTableComponent,
  DialogComponent,
  IconComponent,
  RowDetailDirective,
  SelectComponent,
  type SelectOption,
} from '@stupa-makers/ui-kit';
import { ToastService } from '@stupa-makers/ui-kit';
import { AdminApiService } from '../admin/admin-api.service';
import { BudgetTreeApi, type BudgetTreeNode, type FiscalYear } from './budget-tree.api';
import { SimplifyPathPipe } from '@shared/budget-path';
import { BudgetYearTreeComponent, type BudgetYearSelection } from './budget-year-tree.component';

/** A tree row: a node plus the depth for the indentation. */
interface Row {
  node: BudgetTreeNode;
  depth: number;
}

/**
 * Budget and cost-center tree editor. The page is budget-scoped. Pick a budget at
 * the top, then edit its cost-center subtree (`VS-800-40 – …`) below.
 *
 * A budget is NOT bound to a Gremium. Fiscal years belong to the budget. Each
 * selected budget shows them on its own card. There is no global fiscal-year
 * dropdown. Available rolls down as the allocation. Bound rolls up from the
 * assigned applications. Each node has an inline-editable allocation for the
 * selected fiscal year.
 */
@Component({
  selector: 'app-budget-tree',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslatePipe, SimplifyPathPipe, ButtonComponent, DialogComponent, DataTableComponent, CellDirective, RowDetailDirective, IconComponent, CurrencyInputComponent, SelectComponent, BudgetYearTreeComponent],
  templateUrl: './budget-tree.component.html',
  styleUrl: './budget-tree.component.scss',
})
export class BudgetTreeComponent {
  private readonly api = inject(BudgetTreeApi);
  private readonly adminApi = inject(AdminApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly tree = signal<BudgetTreeNode[]>([]);
  readonly fiscalYears = signal<FiscalYear[]>([]);
  /** Fiscal years per top budget (for the left navigation tree). */
  readonly fiscalYearsByBudget = signal<Record<Uuid, FiscalYear[]>>({});
  readonly selectedTopId = signal('');
  readonly selectedFyId = signal('');
  readonly loading = signal(true);
  readonly loadError = signal(false);

  /** Top budgets (roots) for the left tree. */
  readonly tops = computed(() => this.tree().filter((n) => n.parentId === null));

  /** Flow-state keys (global flow) for the accepted/denied config. */
  readonly stateOptions = signal<SelectOption[]>([]);

  /** Create a top budget. A budget has no Gremium. ``fiscalStartMonth`` and
   *  ``fiscalStartDay`` hold the fiscal-year cutoff. The default is 01.01. */
  readonly newTop = signal<{
    key: string;
    name: string;
    fiscalStartMonth: number;
    fiscalStartDay: number;
  }>({ key: '', name: '', fiscalStartMonth: 1, fiscalStartDay: 1 });
  /** Top-budget dialog (opened via the header button). */
  readonly topOpen = signal(false);
  /** Fiscal-year dialog (opened via the header button). */
  readonly fyOpen = signal(false);
  /** Cutoff dialog for the selected top budget (opened via the header button). */
  readonly stichtagOpen = signal(false);
  /** Status config dialog (accepted/denied states of the top budget). */
  readonly stateConfigOpen = signal(false);
  /** Add child node: which parent is expanded + the draft. */
  readonly addingChildOf = signal<Uuid | null>(null);
  readonly childDraft = signal<{ key: string; name: string }>({ key: '', name: '' });
  /** Set the limit (allocation) of a node through a per-row dialog. */
  readonly limitNode = signal<BudgetTreeNode | null>(null);
  readonly limitValue = signal('');
  /** Edit a cost center (key, name, visibility) through a per-row dialog. */
  readonly editNode = signal<BudgetTreeNode | null>(null);
  readonly editKey = signal('');
  readonly editName = signal('');
  /** Hide in the budget tab. This setting changes the display only. */
  readonly editHidden = signal(false);
  /** Visibility Gremium. Its members see the subtree in the budget tab as a root.
   *  An empty string means no assignment. */
  readonly editViewGremium = signal('');
  readonly gremiumOptions = signal<SelectOption[]>([]);
  /** Create a fiscal year inside the selected budget. It takes only the year. */
  readonly newFy = signal<{ year: number }>({ year: new Date().getFullYear() });

  readonly selectedTop = computed<BudgetTreeNode | null>(
    () => this.tree().find((n) => n.id === this.selectedTopId()) ?? null,
  );

  /** Display label of the selected budget (for the fiscal-year dialog). */
  readonly selectedTopLabel = computed<string>(() => {
    const t = this.selectedTop();
    return t ? `${t.key} – ${t.name}` : '';
  });

  /** Subtree of the selected budget -> flat rows (pre-order) with depth. */
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
    { key: 'color', label: this.i18n.translate('budget.tree.col.color'), width: '4rem' },
    { key: 'actions', label: this.i18n.translate('budget.tree.col.actions'), align: 'end', width: '8.5rem' },
  ]);
  readonly rowId = (r: unknown): string => (r as Row).node.id;
  readonly childExpanded = (r: unknown): boolean => this.addingChildOf() === (r as Row).node.id;

  constructor() {
    this.reload();
    // Gremien for the visibility dropdown in the edit dialog.
    this.adminApi.listGremienOptions().subscribe({
      next: (list) =>
        this.gremiumOptions.set(list.map((g) => ({ value: g.id, label: g.name }))),
      error: () => this.gremiumOptions.set([]),
    });
    // The global flow gives the state keys for the accepted/denied config. An error
    // stays silent.
    this.adminApi.getGlobalFlow().subscribe({
      next: (graph) =>
        this.stateOptions.set(
          (graph?.states ?? []).map((s) => ({
            value: s.key,
            label: `${s.label['de'] ?? s.key} (${s.key})`,
          })),
        ),
      error: () => this.stateOptions.set([]),
    });
  }

  /** Currently selected top budget. The color and state config read it. */
  private readonly currentTop = computed(() => this.selectedTop());
  readonly acceptedKeys = computed(() => new Set(this.currentTop()?.acceptedStateKeys ?? []));
  readonly deniedKeys = computed(() => new Set(this.currentTop()?.deniedStateKeys ?? []));
  isAccepted(key: string): boolean {
    return this.acceptedKeys().has(key);
  }
  isDenied(key: string): boolean {
    return this.deniedKeys().has(key);
  }

  money(value: string | number | null | undefined, currency: string): string {
    const n = value == null || value === '' ? 0 : Number(value);
    return new Intl.NumberFormat(this.i18n.locale(), { style: 'currency', currency }).format(n);
  }

  alloc(node: BudgetTreeNode) {
    const fy = this.selectedFyId();
    return node.byFiscalYear.find((a) => a.fiscalYearId === fy) ?? null;
  }

  /** Load sequence counter. It increases for each load. A response of an older
   *  reload() fan-out can arrive after a newer reload(). The sequence check drops it.
   *  Without the check it overwrites the fiscal year and the selection. */
  private reloadSeq = 0;

  private reload(): void {
    const seq = ++this.reloadSeq;
    this.loading.set(true);
    this.loadError.set(false);
    this.api.tree().subscribe({
      next: (tree) => {
        if (seq !== this.reloadSeq) return;
        this.tree.set(tree);
        const tops = tree.filter((n) => n.parentId === null);
        const keep = tops.some((t) => t.id === this.selectedTopId());
        const topId = keep ? this.selectedTopId() : (tops[0]?.id ?? '');
        this.selectedTopId.set(topId);
        if (!topId) this.fiscalYears.set([]);
        // Load the fiscal years of all top budgets for the left tree. An error stays
        // silent. For the selected budget, also set the fiscal-year list on the right.
        for (const top of tops) {
          this.api.listFiscalYears(top.id as Uuid).subscribe({
            next: (fys) => {
              if (seq !== this.reloadSeq) return;
              this.fiscalYearsByBudget.update((m) => ({ ...m, [top.id]: fys }));
              if (top.id === topId) {
                this.fiscalYears.set(fys);
                if (!fys.some((fy) => fy.id === this.selectedFyId()))
                  this.selectedFyId.set(fys[0]?.id ?? '');
              }
            },
            error: () => undefined,
          });
        }
        this.loading.set(false);
      },
      error: () => {
        if (seq !== this.reloadSeq) return;
        this.loadError.set(true);
        this.loading.set(false);
      },
    });
  }

  /** Load the fiscal years of the selected budget. They live inside the budget. This
   *  raises the load sequence. A reload() fan-out that still runs then does not
   *  overwrite this selection. The reverse also holds. */
  private loadFiscalYears(topId: string): void {
    const seq = ++this.reloadSeq;
    this.api.listFiscalYears(topId as Uuid).subscribe({
      next: (fys) => {
        if (seq !== this.reloadSeq) return;
        this.fiscalYears.set(fys);
        if (!fys.some((fy) => fy.id === this.selectedFyId())) this.selectedFyId.set(fys[0]?.id ?? '');
      },
      error: () => {
        if (seq !== this.reloadSeq) return;
        this.fiscalYears.set([]);
      },
    });
  }

  selectTop(id: string): void {
    this.selectedTopId.set(id);
    this.selectedFyId.set('');
    this.loadFiscalYears(id);
  }

  /** Handle a year picked in the left tree. Set the budget and the fiscal year. This
   *  raises the load sequence. A reload() fan-out that still runs then does not
   *  overwrite this selection, the same as in loadFiscalYears and selectTop. */
  onYearPicked(sel: BudgetYearSelection): void {
    ++this.reloadSeq;
    this.selectedTopId.set(sel.budgetId);
    const fys = this.fiscalYearsByBudget()[sel.budgetId] ?? [];
    this.fiscalYears.set(fys);
    this.selectedFyId.set(sel.fiscalYearId);
  }

  /** Set or clear the color of a cost center. An empty value means automatic. */
  saveColor(node: BudgetTreeNode, color: string): void {
    this.api.updateNode(node.id, { color: color || '' }).subscribe({
      next: () => {
        this.toast.success(this.i18n.translate('budget.tree.toast.colorSaved'));
        this.reload();
      },
      error: () => this.toast.error(this.i18n.translate('budget.tree.toast.failed')),
    });
  }

  /** Toggle a state key in the top budget's accepted/denied set. */
  toggleState(kind: 'accepted' | 'denied', key: string): void {
    const top = this.currentTop();
    if (!top) return;
    const accepted = new Set(this.acceptedKeys());
    const denied = new Set(this.deniedKeys());
    const target = kind === 'accepted' ? accepted : denied;
    const other = kind === 'accepted' ? denied : accepted;
    if (target.has(key)) {
      target.delete(key);
    } else {
      target.add(key);
      other.delete(key); // A state is never accepted and denied at the same time.
    }
    this.api
      .updateNode(top.id, {
        acceptedStateKeys: [...accepted],
        deniedStateKeys: [...denied],
      })
      .subscribe({
        next: () => this.reload(),
        error: () => this.toast.error(this.i18n.translate('budget.tree.toast.failed')),
      });
  }

  // Create and delete nodes.
  patchTop<K extends 'key' | 'name'>(key: K, value: string): void {
    this.newTop.update((t) => ({ ...t, [key]: value }));
  }

  patchTopStichtag(key: 'fiscalStartMonth' | 'fiscalStartDay', value: string): void {
    const n = Math.trunc(Number(value)) || 1;
    const clamped = key === 'fiscalStartMonth' ? clampRange(n, 1, 12) : clampRange(n, 1, 31);
    this.newTop.update((t) => ({ ...t, [key]: clamped }));
  }

  openTop(): void {
    this.newTop.set({ key: '', name: '', fiscalStartMonth: 1, fiscalStartDay: 1 });
    this.topOpen.set(true);
  }

  closeTop(): void {
    this.topOpen.set(false);
  }

  createTop(event: Event): void {
    event.preventDefault();
    const t = this.newTop();
    if (!t.key.trim() || !t.name.trim()) return;
    this.api
      .createNode({
        key: t.key.trim(),
        name: t.name.trim(),
        fiscalStartMonth: t.fiscalStartMonth,
        fiscalStartDay: t.fiscalStartDay,
      })
      .subscribe({
        next: (node) => {
          this.toast.success(this.i18n.translate('budget.tree.toast.created'));
          this.newTop.set({ key: '', name: '', fiscalStartMonth: 1, fiscalStartDay: 1 });
          this.topOpen.set(false);
          this.selectedTopId.set(node.id);
          this.reload();
        },
        error: () => this.toast.error(this.i18n.translate('budget.tree.toast.failed')),
      });
  }

  /** Change the fiscal-year cutoff of the selected top budget. The server derives the
   *  existing years again. */
  saveStichtag(key: 'fiscalStartMonth' | 'fiscalStartDay', value: string): void {
    const top = this.selectedTop();
    if (!top) return;
    const n = Math.trunc(Number(value)) || 1;
    const clamped = key === 'fiscalStartMonth' ? clampRange(n, 1, 12) : clampRange(n, 1, 31);
    this.api.updateNode(top.id, { [key]: clamped }).subscribe({
      next: () => {
        this.toast.success(this.i18n.translate('budget.tree.toast.stichtagSaved'));
        this.reload();
        this.loadFiscalYears(top.id);
      },
      error: () => this.toast.error(this.i18n.translate('budget.tree.toast.failed')),
    });
  }

  openStichtag(): void {
    this.stichtagOpen.set(true);
  }
  closeStichtag(): void {
    this.stichtagOpen.set(false);
  }
  openStateConfig(): void {
    this.stateConfigOpen.set(true);
  }
  closeStateConfig(): void {
    this.stateConfigOpen.set(false);
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

  // Per-row dialogs for the node edit and the allocation limit.
  openEditNode(node: BudgetTreeNode): void {
    this.editNode.set(node);
    this.editKey.set(node.key);
    this.editName.set(node.name);
    this.editHidden.set(node.hiddenInBudget);
    this.editViewGremium.set(node.viewGremiumId ?? '');
  }

  closeEditNode(): void {
    this.editNode.set(null);
  }

  saveEditNode(): void {
    const node = this.editNode();
    if (!node) return;
    const key = this.editKey().trim();
    const name = this.editName().trim();
    if (!key || !name) return;
    this.api
      .updateNode(node.id, {
        key,
        name,
        hiddenInBudget: this.editHidden(),
        viewGremiumId: this.editViewGremium() || null,
      })
      .subscribe({
      next: () => {
        this.toast.success(this.i18n.translate('budget.tree.toast.saved'));
        this.editNode.set(null);
        this.reload();
      },
      error: () => this.toast.error(this.i18n.translate('budget.tree.toast.keyFailed')),
    });
  }

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

  // Fiscal years, which live inside the budget.
  patchFyYear(value: string): void {
    const year = Math.trunc(Number(value)) || new Date().getFullYear();
    this.newFy.set({ year });
  }

  openFy(): void {
    this.newFy.set({ year: new Date().getFullYear() });
    this.fyOpen.set(true);
  }

  closeFy(): void {
    this.fyOpen.set(false);
  }

  createFiscalYear(event: Event): void {
    event.preventDefault();
    const top = this.selectedTopId();
    const f = this.newFy();
    if (!top || !f.year) return;
    this.api.createFiscalYear(top as Uuid, { year: f.year }).subscribe({
      next: () => {
        this.toast.success(this.i18n.translate('budget.tree.toast.fyCreated'));
        this.newFy.set({ year: new Date().getFullYear() });
        this.fyOpen.set(false);
        this.loadFiscalYears(top);
      },
      error: () => this.toast.error(this.i18n.translate('budget.tree.toast.fyFailed')),
    });
  }
}

/** Clamp an integer to [min, max]. */
function clampRange(n: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, n));
}
