import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { forkJoin } from 'rxjs';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Uuid } from '@core/api/models';
import { BadgeComponent, ButtonComponent, CardComponent, SelectComponent, type SelectOption } from '@shared/ui';
import { ToastService } from '@shared/ui/toast/toast.service';
import { AdminOptionsService } from '../admin/admin-options.service';
import {
  BudgetTreeApi,
  type BudgetTreeNode,
  type FiscalYear,
} from './budget-tree.api';

/** Eine Baumzeile (Knoten + Tiefe für die Einrückung). */
interface Row {
  node: BudgetTreeNode;
  depth: number;
}

/**
 * Budget-/Kostenstellen-Baum (#9, SRS R7.1). Ersetzt die flache »Budget-Töpfe«-
 * Liste durch den hierarchischen Baum: Top-Budget (z. B. VS) → beliebig tief
 * geschachtelte Kostenstellen (`VS-800-40 – Fachschaft Informatik`).
 *
 * **Verfügbar** ist Roll-Down (Top-Down-Zuteilung je HHJ), **gebunden** ist
 * Roll-Up (Summe der zugeordneten Anträge, vom Backend über den `pathKey`-Präfix
 * aggregiert). Pro Haushaltsjahr (Auswahl oben) zeigt jede Zeile zugeteilt/
 * gebunden/verfügbar; die Zuteilung ist inline editierbar.
 */
@Component({
  selector: 'app-budget-tree',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslatePipe, ButtonComponent, CardComponent, SelectComponent, BadgeComponent],
  templateUrl: './budget-tree.component.html',
  styleUrl: './budget-tree.component.scss',
})
export class BudgetTreeComponent {
  private readonly api = inject(BudgetTreeApi);
  private readonly options = inject(AdminOptionsService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  readonly gremiumOptions = signal<SelectOption[]>([]);
  readonly gremiumFilter = signal('');
  readonly tree = signal<BudgetTreeNode[]>([]);
  readonly fiscalYears = signal<FiscalYear[]>([]);
  readonly selectedFyId = signal('');
  readonly loading = signal(true);
  readonly loadError = signal(false);

  /** Top-Budget anlegen. */
  readonly newTop = signal<{ gremiumId: string; key: string; name: string }>({
    gremiumId: '',
    key: '',
    name: '',
  });
  /** Unterknoten anlegen: welcher Parent ist aufgeklappt + Entwurf. */
  readonly addingChildOf = signal<Uuid | null>(null);
  readonly childDraft = signal<{ key: string; name: string }>({ key: '', name: '' });
  /** Inline-Zuteilungs-Entwürfe je Knoten (für das gewählte HHJ). */
  readonly allocDraft = signal<Record<string, string>>({});

  /** HHJ anlegen (für ein Top-Budget). */
  readonly newFy = signal<{ topId: string; label: string; startDate: string; endDate: string }>({
    topId: '',
    label: '',
    startDate: '',
    endDate: '',
  });

  readonly fyOptions = computed<SelectOption[]>(() =>
    this.fiscalYears().map((fy) => ({ value: fy.id, label: fy.label })),
  );
  readonly topOptions = computed<SelectOption[]>(() =>
    this.tree().map((n) => ({ value: n.id, label: `${n.key} – ${n.name}` })),
  );

  /** Baum → flache Zeilen (Pre-Order) mit Tiefe für die Einrückung. */
  readonly rows = computed<Row[]>(() => {
    const out: Row[] = [];
    const walk = (nodes: BudgetTreeNode[], depth: number): void => {
      for (const node of nodes) {
        out.push({ node, depth });
        if (node.children.length) walk(node.children, depth + 1);
      }
    };
    walk(this.tree(), 0);
    return out;
  });

  constructor() {
    this.options
      .gremiumOptions()
      .pipe(takeUntilDestroyed())
      .subscribe({
        next: (opts) => this.gremiumOptions.set(opts),
        error: () => this.gremiumOptions.set([]),
      });
    this.reload();
  }

  // --- Anzeige-Helfer -------------------------------------------------------
  money(value: string | number | null | undefined, currency: string): string {
    const n = value == null || value === '' ? 0 : Number(value);
    return new Intl.NumberFormat(this.i18n.locale(), { style: 'currency', currency }).format(n);
  }

  /** Summen eines Knotens im gewählten HHJ (oder null, wenn keins gewählt/vorhanden). */
  alloc(node: BudgetTreeNode) {
    const fy = this.selectedFyId();
    return node.byFiscalYear.find((a) => a.fiscalYearId === fy) ?? null;
  }

  // --- Laden ----------------------------------------------------------------
  private reload(): void {
    this.loading.set(true);
    this.loadError.set(false);
    const gremium = this.gremiumFilter() || undefined;
    this.api.tree(gremium).subscribe({
      next: (tree) => {
        this.tree.set(tree);
        this.loadFiscalYears(tree);
        this.loading.set(false);
      },
      error: () => {
        this.loadError.set(true);
        this.loading.set(false);
      },
    });
  }

  /** HHJ je Top-Budget laden + sammeln (für Auswahl + Allokations-Anzeige). */
  private loadFiscalYears(tree: BudgetTreeNode[]): void {
    const tops = tree.filter((n) => n.parentId === null);
    if (!tops.length) {
      this.fiscalYears.set([]);
      return;
    }
    forkJoin(tops.map((t) => this.api.listFiscalYears(t.id))).subscribe({
      next: (lists) => {
        const all = lists.flat();
        this.fiscalYears.set(all);
        if (all.length && !all.some((fy) => fy.id === this.selectedFyId())) {
          this.selectedFyId.set(all[0].id);
        }
      },
      error: () => this.fiscalYears.set([]),
    });
  }

  applyGremiumFilter(value: string): void {
    this.gremiumFilter.set(value);
    this.reload();
  }

  // --- Knoten anlegen/löschen ----------------------------------------------
  patchTop<K extends 'gremiumId' | 'key' | 'name'>(key: K, value: string): void {
    this.newTop.update((t) => ({ ...t, [key]: value }));
  }

  createTop(event: Event): void {
    event.preventDefault();
    const t = this.newTop();
    if (!t.gremiumId || !t.key.trim() || !t.name.trim()) return;
    this.api
      .createNode({ gremiumId: t.gremiumId, key: t.key.trim(), name: t.name.trim() })
      .subscribe({
        next: () => {
          this.toast.success(this.i18n.translate('budget.tree.toast.created'));
          this.newTop.set({ gremiumId: '', key: '', name: '' });
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

  // --- Zuteilung ------------------------------------------------------------
  patchAlloc(nodeId: string, value: string): void {
    this.allocDraft.update((d) => ({ ...d, [nodeId]: value }));
  }

  saveAlloc(node: BudgetTreeNode): void {
    const fy = this.selectedFyId();
    if (!fy) return;
    const raw = this.allocDraft()[node.id] ?? this.alloc(node)?.allocated ?? '';
    const value = raw.toString().trim();
    if (value === '') return;
    this.api.setAllocation(node.id, fy, value).subscribe({
      next: () => {
        this.toast.success(this.i18n.translate('budget.tree.toast.allocated'));
        this.reload();
      },
      error: () => this.toast.error(this.i18n.translate('budget.tree.toast.failed')),
    });
  }

  // --- Haushaltsjahre -------------------------------------------------------
  patchFy<K extends 'topId' | 'label' | 'startDate' | 'endDate'>(key: K, value: string): void {
    this.newFy.update((f) => ({ ...f, [key]: value }));
  }

  createFiscalYear(event: Event): void {
    event.preventDefault();
    const f = this.newFy();
    if (!f.topId || !f.label.trim() || !f.startDate || !f.endDate) return;
    this.api
      .createFiscalYear(f.topId, { label: f.label.trim(), startDate: f.startDate, endDate: f.endDate })
      .subscribe({
        next: () => {
          this.toast.success(this.i18n.translate('budget.tree.toast.fyCreated'));
          this.newFy.set({ topId: '', label: '', startDate: '', endDate: '' });
          this.reload();
        },
        error: () => this.toast.error(this.i18n.translate('budget.tree.toast.fyFailed')),
      });
  }
}
