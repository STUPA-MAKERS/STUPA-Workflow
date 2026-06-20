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
} from '@shared/ui';
import { ToastService } from '@shared/ui/toast/toast.service';
import { AdminApiService } from '../admin/admin-api.service';
import { BudgetTreeApi, type BudgetTreeNode, type FiscalYear } from './budget-tree.api';
import { SimplifyPathPipe } from '@shared/budget-path';
import { BudgetYearTreeComponent, type BudgetYearSelection } from './budget-year-tree.component';

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
  /** HHJ je Top-Budget (für den linken Navigations-Baum). */
  readonly fiscalYearsByBudget = signal<Record<Uuid, FiscalYear[]>>({});
  readonly selectedTopId = signal('');
  readonly selectedFyId = signal('');
  readonly loading = signal(true);
  readonly loadError = signal(false);

  /** Top-Budgets (Wurzeln) für den linken Baum. */
  readonly tops = computed(() => this.tree().filter((n) => n.parentId === null));

  /** Flow-State-Keys (globaler Flow) für die accepted/denied-Konfiguration. */
  readonly stateOptions = signal<SelectOption[]>([]);

  /** Top-Budget anlegen (kein Gremium — Budgets sind gremium-unabhängig).
   *  ``fiscalStartMonth``/``fiscalStartDay`` = HHJ-Stichtag (Default 01.01.). */
  readonly newTop = signal<{
    key: string;
    name: string;
    fiscalStartMonth: number;
    fiscalStartDay: number;
  }>({ key: '', name: '', fiscalStartMonth: 1, fiscalStartDay: 1 });
  /** Top-Budget-Dialog (über den Kopf-Button geöffnet). */
  readonly topOpen = signal(false);
  /** Haushaltsjahr-Dialog (über den Kopf-Button geöffnet). */
  readonly fyOpen = signal(false);
  /** Stichtag-Dialog (über den Kopf-Button, für das gewählte Top-Budget). */
  readonly stichtagOpen = signal(false);
  /** Status-Konfigurations-Dialog (accepted/denied States des Top-Budgets). */
  readonly stateConfigOpen = signal(false);
  /** Unterknoten anlegen: welcher Parent ist aufgeklappt + Entwurf. */
  readonly addingChildOf = signal<Uuid | null>(null);
  readonly childDraft = signal<{ key: string; name: string }>({ key: '', name: '' });
  /** Limit (Zuteilung) je Knoten setzen — per Dialog pro Zeile (#22). */
  readonly limitNode = signal<BudgetTreeNode | null>(null);
  readonly limitValue = signal('');
  /** Kostenstelle bearbeiten (Schlüssel + Name + Sichtbarkeit) — per Dialog pro Zeile. */
  readonly editNode = signal<BudgetTreeNode | null>(null);
  readonly editKey = signal('');
  readonly editName = signal('');
  /** Im Budget-Tab ausblenden (#budget-hide) — reine Anzeige-Einstellung. */
  readonly editHidden = signal(false);
  /** Sichtbarkeits-Gremium (#budget-scope): dessen Mitglieder sehen den Teilbaum
   *  im Budget-Tab als Root; '' = keine Zuordnung. */
  readonly editViewGremium = signal('');
  readonly gremiumOptions = signal<SelectOption[]>([]);
  /** Haushaltsjahr anlegen — INNERHALB des gewählten Budgets (nur das Jahr). */
  readonly newFy = signal<{ year: number }>({ year: new Date().getFullYear() });

  readonly selectedTop = computed<BudgetTreeNode | null>(
    () => this.tree().find((n) => n.id === this.selectedTopId()) ?? null,
  );

  /** Anzeige-Label des gewählten Budgets (für den HHJ-Dialog). */
  readonly selectedTopLabel = computed<string>(() => {
    const t = this.selectedTop();
    return t ? `${t.key} – ${t.name}` : '';
  });

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
    { key: 'color', label: this.i18n.translate('budget.tree.col.color'), width: '4rem' },
    { key: 'actions', label: this.i18n.translate('budget.tree.col.actions'), align: 'end', width: '8.5rem' },
  ]);
  readonly rowId = (r: unknown): string => (r as Row).node.id;
  readonly childExpanded = (r: unknown): boolean => this.addingChildOf() === (r as Row).node.id;

  constructor() {
    this.reload();
    // Gremien fürs Sichtbarkeits-Dropdown (#budget-scope) im Edit-Dialog.
    this.adminApi.listGremienOptions().subscribe({
      next: (list) =>
        this.gremiumOptions.set(list.map((g) => ({ value: g.id, label: g.name }))),
      error: () => this.gremiumOptions.set([]),
    });
    // Globaler Flow → State-Keys für die accepted/denied-Konfiguration (still degr.).
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

  /** Aktuell gewähltes Top-Budget (für Farbe/State-Config). */
  private readonly currentTop = computed(() => this.selectedTop());
  readonly acceptedKeys = computed(() => new Set(this.currentTop()?.acceptedStateKeys ?? []));
  readonly deniedKeys = computed(() => new Set(this.currentTop()?.deniedStateKeys ?? []));
  isAccepted(key: string): boolean {
    return this.acceptedKeys().has(key);
  }
  isDenied(key: string): boolean {
    return this.deniedKeys().has(key);
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
        if (!topId) this.fiscalYears.set([]);
        // HHJ aller Top-Budgets für den linken Baum (fehlertolerant); für das
        // gewählte Budget zugleich die rechte HHJ-Liste setzen.
        for (const top of tops) {
          this.api.listFiscalYears(top.id as Uuid).subscribe({
            next: (fys) => {
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

  /** Jahr im linken Baum gewählt → Budget + HHJ setzen. */
  onYearPicked(sel: BudgetYearSelection): void {
    this.selectedTopId.set(sel.budgetId);
    const fys = this.fiscalYearsByBudget()[sel.budgetId] ?? [];
    this.fiscalYears.set(fys);
    this.selectedFyId.set(sel.fiscalYearId);
  }

  /** Farbe einer Kostenstelle setzen/löschen (leer = automatisch). */
  saveColor(node: BudgetTreeNode, color: string): void {
    this.api.updateNode(node.id, { color: color || '' }).subscribe({
      next: () => {
        this.toast.success(this.i18n.translate('budget.tree.toast.colorSaved'));
        this.reload();
      },
      error: () => this.toast.error(this.i18n.translate('budget.tree.toast.failed')),
    });
  }

  /** Einen State-Key im accepted/denied-Set des Top-Budgets umschalten (#budget). */
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
      other.delete(key); // ein State ist nicht gleichzeitig accepted UND denied
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

  // --- Knoten anlegen/löschen ----------------------------------------------
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

  /** HHJ-Stichtag des gewählten Top-Budgets ändern (leitet bestehende HHJ neu ab). */
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

  // --- Limit / Zuteilung (Dialog pro Zeile) --------------------------------
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

  // --- Haushaltsjahre (innerhalb des Budgets) ------------------------------
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

/** Ganzzahl auf ``[min, max]`` begrenzen. */
function clampRange(n: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, n));
}
