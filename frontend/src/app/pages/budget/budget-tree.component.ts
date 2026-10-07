import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  Injector,
  afterNextRender,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import type { Uuid } from '@core/api/models';
import {
  ButtonComponent,
  CellDirective,
  CheckboxComponent,
  type ColumnDef,
  CurrencyInputComponent,
  DataTableComponent,
  DialogComponent,
  IconComponent,
  InputComponent,
  MEDIA,
  RowDetailDirective,
  SegmentedComponent,
  type SegmentedOption,
  SelectComponent,
  type SelectOption,
  SwitchComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { mediaQuerySignal } from '../../layout/media-query';
import { AdminApiService } from '../admin/admin-api.service';
import { FilterSelectComponent, type FilterSelectOption } from '@shared/ui/filter-select/filter-select.component';
import { NoteComponent } from '@shared/ui/note/note.component';
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';
import { RowMenuComponent, type RowMenuItem, type RowMenuSection } from '@shared/ui/row-menu/row-menu.component';
import { PALETTE, resolveNodeColors } from './budget-color.util';
import { BudgetTreeApi, type BudgetTreeNode, type FiscalYear } from './budget-tree.api';

/** A visible tree row: a node, its depth and whether it has children. */
interface Row {
  node: BudgetTreeNode;
  depth: number;
  hasChildren: boolean;
}

/** How the colour cell shows a node: its own colour, a colour from above, or none. */
export interface Swatch {
  kind: 'own' | 'inherited' | 'none';
  color: string | null;
}

/** The colour of a cost centre: `#rrggbb`, the format the dialog stores. */
const HEX_COLOR = /^#[0-9a-f]{6}$/i;

/** The width of an amount column: "120.000 €" in the mono font of the table. A longer
 *  amount widens its column; the name column gives up the room. */
const AMOUNT_WIDTH = '6rem';

/**
 * From this page width on, the table shows all five amounts. The fixed columns (five
 * amounts, colour, four row actions) take about 690 px; the rest, at least 180 px, is
 * the name column. The sheet beside the admin navigation is 904 px wide at 1440 px.
 */
const FULL_TABLE_MIN = 870;
/** From this page width on, the table leaves out only "Einnahmen". */
const MID_TABLE_MIN = 780;

/** The cutoff day must exist in every month (backend: 1..28). */
const MAX_CUTOFF_DAY = 28;

/**
 * The cost centres of the admin area (boards Admin-Kostenstellen, Admin-Kostenstelle-Dialog).
 *
 * A toolbar holds the budget-wide actions: the accepted and bound flow states, the
 * fiscal-year cutoff, "Haushaltsjahr anlegen" (with the list of the years to correct or
 * delete) and "Budget anlegen". A chip picks the top budget, a segmented control its
 * fiscal year (an inactive year says so).
 *
 * The table is the cost-centre tree of the picked budget: a node with children folds, the
 * name stands over its key path, the five amounts of the year follow (Zugeteilt, Gebunden,
 * Ausgegeben, Einnahmen, Verfügbar), then the colour: a node shows its own colour, the
 * colour of the nearest coloured parent in a muted look (O19), or an empty box. Each row
 * edits its node, sets its allocation for the year, adds a sub cost centre (an inline row
 * at the end of its subtree) and deletes it after a confirmation.
 *
 * The edit dialog holds every setting of a node: key, name, colour, active, "Im Budget-Tab
 * ausblenden" and the visibility gremium (`viewGremiumId`, gaps N32), whose members see the
 * subtree in the budget tab without a budget right.
 */
@Component({
  selector: 'app-budget-tree',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    ButtonComponent,
    CellDirective,
    CheckboxComponent,
    CurrencyInputComponent,
    DataTableComponent,
    DialogComponent,
    FilterSelectComponent,
    IconComponent,
    InputComponent,
    NoteComponent,
    PageHeaderComponent,
    RowDetailDirective,
    RowMenuComponent,
    SegmentedComponent,
    SelectComponent,
    SwitchComponent,
  ],
  templateUrl: './budget-tree.component.html',
  styleUrl: './budget-tree.component.scss',
})
export class BudgetTreeComponent {
  private readonly api = inject(BudgetTreeApi);
  private readonly adminApi = inject(AdminApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly auth = inject(AuthService);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly destroyRef = inject(DestroyRef);
  private readonly injector = inject(Injector);

  /** Phone: the toolbar actions go into the header menu, the rows into cards. */
  readonly phone = mediaQuerySignal(MEDIA.phone);
  /** The width of the page, measured: the sheet beside the admin navigation is narrower
   *  than the viewport says. `0` until the first measure (all columns). */
  readonly width = signal(0);
  /** The amounts a narrow page leaves out; lines under "Verfügbar" show them. */
  readonly hidden = computed<ReadonlySet<'expended' | 'income'>>(() => {
    const w = this.width();
    // A phone shows cards: they stack the amounts and have room for all five.
    if (this.phone() || w === 0 || w >= FULL_TABLE_MIN) return new Set();
    return w >= MID_TABLE_MIN ? new Set(['income']) : new Set(['expended', 'income']);
  });

  /** `budget.structure` as a front-end gate for the fiscal-year edit and delete. The
   *  backend stays authoritative. The value is reactive, because the principal loads
   *  asynchronously. */
  readonly canStructure = computed(() => this.auth.can('budget.structure'));

  readonly palette = PALETTE;

  readonly tree = signal<BudgetTreeNode[]>([]);
  readonly fiscalYears = signal<FiscalYear[]>([]);
  readonly selectedTopId = signal('');
  readonly selectedFyId = signal('');
  readonly loading = signal(true);
  readonly loadError = signal(false);
  /** Nodes whose children are folded away. Every node starts open. */
  readonly collapsed = signal<ReadonlySet<string>>(new Set());

  /** Top budgets (roots). */
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
  readonly topOpen = signal(false);
  readonly fyOpen = signal(false);
  readonly stichtagOpen = signal(false);
  readonly stateConfigOpen = signal(false);
  /** Add a sub cost centre: the parent and the draft of the inline row. */
  readonly addingChildOf = signal<Uuid | null>(null);
  readonly childDraft = signal<{ key: string; name: string }>({ key: '', name: '' });
  /** Set the limit (allocation) of a node through a per-row dialog. */
  readonly limitNode = signal<BudgetTreeNode | null>(null);
  readonly limitValue = signal('');
  /** Edit every setting of a cost centre in one dialog. */
  readonly editNode = signal<BudgetTreeNode | null>(null);
  readonly editKey = signal('');
  readonly editName = signal('');
  /** `#rrggbb`, or '' for no own colour (the node then shows the colour of its parent). */
  readonly editColor = signal('');
  readonly editActive = signal(true);
  /** Hide in the budget tab. This setting changes the display only. */
  readonly editHidden = signal(false);
  /** Visibility Gremium. Its members see the subtree in the budget tab as a root.
   *  An empty string means no assignment. */
  readonly editViewGremium = signal('');
  /** Own deciding gremium of the node. An empty string means none: the node inherits
   *  the gremium of the nearest ancestor that has one. */
  readonly editDecisionGremium = signal('');
  readonly gremiumOptions = signal<SelectOption[]>([]);
  /** Delete a cost centre after a confirmation; a 409 names the reason in the dialog. */
  readonly nodeDelete = signal<BudgetTreeNode | null>(null);
  readonly nodeDeleteBlocked = signal(false);
  /** Create a fiscal year inside the selected budget. It takes only the year. */
  readonly newFy = signal<{ year: number }>({ year: new Date().getFullYear() });
  readonly fyEdit = signal<FiscalYear | null>(null);
  readonly fyEditYear = signal<number>(new Date().getFullYear());
  readonly fyEditActive = signal(true);
  readonly fyDelete = signal<FiscalYear | null>(null);
  /** Translated reason why the delete was refused (409), else `null`. */
  readonly fyDeleteBlocked = signal<string | null>(null);

  readonly selectedTop = computed<BudgetTreeNode | null>(
    () => this.tree().find((n) => n.id === this.selectedTopId()) ?? null,
  );

  /** Display label of the selected budget (for the dialogs). */
  readonly selectedTopLabel = computed<string>(() => {
    const t = this.selectedTop();
    return t ? `${t.key} – ${t.name}` : '';
  });

  /** "01.01.": the cutoff of the selected budget. */
  readonly cutoffLabel = computed(() => {
    const t = this.selectedTop();
    if (!t) return '';
    const p = (n: number): string => String(n).padStart(2, '0');
    return `${p(t.fiscalStartDay)}.${p(t.fiscalStartMonth)}.`;
  });

  /** The budget chip: every top budget, by name and key. */
  readonly topOptions = computed<FilterSelectOption[]>(() =>
    this.tops().map((t) => ({ value: t.id, label: `${t.name} (${t.key})` })),
  );
  readonly topChipText = computed(() => {
    const t = this.selectedTop();
    if (!t) return null;
    return this.i18n.translate('budget.tree.topChip', { name: t.name, key: t.key, cutoff: this.cutoffLabel() });
  });

  /** The fiscal years as segments, newest first; an inactive year says so. */
  readonly fyOptions = computed<SegmentedOption[]>(() =>
    [...this.fiscalYears()]
      .sort((a, b) => b.year - a.year)
      .map((fy) => ({
        value: fy.id,
        label: fy.active
          ? this.i18n.translate('budget.tree.fyChip', { year: fy.display })
          : this.i18n.translate('budget.tree.fyChipInactive', { year: fy.display }),
      })),
  );

  /** The colours as the table shows them: own, from the nearest coloured parent, or none. */
  private readonly resolved = computed(() => resolveNodeColors(this.tree()));

  /** Subtree of the selected budget -> visible rows (pre-order) with depth. */
  readonly rows = computed<Row[]>(() => {
    const top = this.selectedTop();
    if (!top) return [];
    const folded = this.collapsed();
    const out: Row[] = [];
    const walk = (node: BudgetTreeNode, depth: number): void => {
      out.push({ node, depth, hasChildren: node.children.length > 0 });
      if (folded.has(node.id)) return;
      for (const c of node.children) walk(c, depth + 1);
    };
    walk(top, 0);
    return out;
  });

  /** The row after which the inline create row of `addingChildOf` stands: the last
   *  visible row of the parent's subtree. */
  private readonly childFormAfter = computed<string | null>(() => {
    const parentId = this.addingChildOf();
    if (!parentId) return null;
    const rows = this.rows();
    const start = rows.findIndex((r) => r.node.id === parentId);
    if (start < 0) return null;
    let last = start;
    for (let i = start + 1; i < rows.length && rows[i].depth > rows[start].depth; i++) last = i;
    return rows[last].node.id;
  });

  /** The parent of the inline create row, for its label "Unter VS-200". */
  readonly childParent = computed<BudgetTreeNode | null>(() => {
    const id = this.addingChildOf();
    return id ? (this.findNode(id) ?? null) : null;
  });

  readonly columns = computed<ColumnDef[]>(() => {
    const t = (k: TranslationKey): string => this.i18n.translate(k);
    // The amounts get a fixed width, so the name column takes the free width.
    const money = (key: string, label: TranslationKey): ColumnDef => ({ key, label: t(label), align: 'end', width: AMOUNT_WIDTH });
    const cols: ColumnDef[] = [
      // D6: the admin navigation stays beside the table at every width. The name column
      // keeps a minimum width, so a narrow sheet scrolls the table sideways instead of
      // squeezing the names and keys to a few characters.
      { key: 'node', label: t('budget.tree.col.node'), card: 'title', width: '13rem' },
      money('allocated', 'budget.tree.col.allocated'),
      money('bound', 'budget.tree.col.bound'),
    ];
    const hidden = this.hidden();
    if (!hidden.has('expended')) cols.push(money('expended', 'budget.tree.col.expended'));
    if (!hidden.has('income')) cols.push(money('income', 'budget.tree.col.income'));
    cols.push(
      money('available', 'budget.tree.col.available'),
      { key: 'color', label: t('budget.tree.col.color'), width: '2.75rem' },
      { key: 'actions', label: t('budget.tree.col.actions'), align: 'end', width: '9.5rem', card: 'actions', sticky: 'end' },
    );
    return cols;
  });
  readonly rowId = (r: unknown): string => (r as Row).node.id;
  readonly childExpanded = (r: unknown): boolean => this.childFormAfter() === (r as Row).node.id;

  /** Fiscal-year table inside the manage dialog. The action column appears only with
   *  `budget.structure`, so a read-only user never sees an edit or a delete button. */
  readonly fyColumns = computed<ColumnDef[]>(() => {
    const cols: ColumnDef[] = [
      { key: 'display', label: this.i18n.translate('budget.tree.fyYear'), card: 'title' },
      { key: 'active', label: this.i18n.translate('budget.tree.fyState') },
    ];
    if (this.canStructure()) {
      cols.push({
        key: 'actions',
        label: this.i18n.translate('budget.tree.col.actions'),
        align: 'end',
        width: '6rem',
        card: 'actions',
      });
    }
    return cols;
  });
  readonly fyRowId = (r: unknown): string => (r as FiscalYear).id;

  constructor() {
    this.reload();
    // Measure the page: beside the admin navigation it is narrower than the viewport.
    afterNextRender(() => {
      if (typeof ResizeObserver === 'undefined') return;
      const observer = new ResizeObserver((entries) => this.width.set(entries[0].contentRect.width));
      observer.observe(this.host.nativeElement);
      this.destroyRef.onDestroy(() => observer.disconnect());
    });
    // Gremien for the visibility select in the edit dialog.
    this.adminApi.listGremienOptions().subscribe({
      next: (list) => this.gremiumOptions.set(list.map((g) => ({ value: g.id, label: g.name }))),
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

  readonly acceptedKeys = computed(() => new Set(this.selectedTop()?.acceptedStateKeys ?? []));
  readonly deniedKeys = computed(() => new Set(this.selectedTop()?.deniedStateKeys ?? []));
  isAccepted(key: string): boolean {
    return this.acceptedKeys().has(key);
  }
  isDenied(key: string): boolean {
    return this.deniedKeys().has(key);
  }

  /** An amount in the currency of the node; cents only where they are not zero. */
  money(value: string | number | null | undefined, currency: string): string {
    const n = value == null || value === '' ? 0 : Number(value);
    return new Intl.NumberFormat(this.i18n.formatLocale(), {
      style: 'currency',
      currency,
      minimumFractionDigits: Number.isInteger(n) ? 0 : 2,
      maximumFractionDigits: 2,
    }).format(n);
  }

  alloc(node: BudgetTreeNode) {
    const fy = this.selectedFyId();
    return node.byFiscalYear.find((a) => a.fiscalYearId === fy) ?? null;
  }

  /** One amount of the selected year, or a dash without an allocation view. */
  amount(node: BudgetTreeNode, field: 'allocated' | 'bound' | 'expended' | 'income' | 'available'): string {
    const a = this.alloc(node);
    return a ? this.money(a[field], node.currency) : '—';
  }

  /**
   * The amounts a narrow table leaves out, as visible lines under "Verfügbar". They are
   * text in the cell, not a tooltip, so a keyboard, touch or screen-reader user reads
   * them too. Empty when the table shows every amount or the node has no allocation.
   */
  hiddenAmounts(node: BudgetTreeNode): string[] {
    const hidden = this.hidden();
    if (!hidden.size || !this.alloc(node)) return [];
    const lines: string[] = [];
    if (hidden.has('expended')) {
      lines.push(this.i18n.translate('budget.tree.expendedTitle', { amount: this.amount(node, 'expended') }));
    }
    lines.push(this.i18n.translate('budget.tree.incomeTitle', { amount: this.amount(node, 'income') }));
    return lines;
  }

  isNegative(node: BudgetTreeNode): boolean {
    const a = this.alloc(node);
    return !!a && Number(a.available) < 0;
  }

  swatch(node: BudgetTreeNode): Swatch {
    const own = node.color?.trim();
    if (own) return { kind: 'own', color: own };
    const above = this.resolved().get(node.id) ?? null;
    return above ? { kind: 'inherited', color: above } : { kind: 'none', color: null };
  }

  swatchLabel(s: Swatch): string {
    if (s.kind === 'own') return this.i18n.translate('budget.tree.colorOwn', { color: String(s.color) });
    if (s.kind === 'inherited') return this.i18n.translate('budget.tree.colorInherited', { color: String(s.color) });
    return this.i18n.translate('budget.tree.colorNone');
  }

  isCollapsed(id: string): boolean {
    return this.collapsed().has(id);
  }

  toggleCollapse(id: string): void {
    this.collapsed.update((set) => {
      const next = new Set(set);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  /** The phone menu of a row: the same four actions as the icon buttons. */
  readonly rowMenu = computed<RowMenuSection[]>(() => {
    const t = (k: TranslationKey): string => this.i18n.translate(k);
    return [
      {
        items: [
          { id: 'edit', label: t('budget.tree.editNode'), icon: 'edit' },
          {
            id: 'limit',
            label: t('budget.tree.setLimit'),
            icon: 'euro',
            disabledReason: this.selectedFyId() ? null : t('budget.tree.noFy'),
          },
          { id: 'child', label: t('budget.tree.addChild'), icon: 'plus' },
        ],
      },
      { items: [{ id: 'delete', label: t('budget.tree.delete'), icon: 'trash', danger: true }] },
    ];
  });

  onRowMenu(node: BudgetTreeNode, item: RowMenuItem): void {
    if (item.id === 'edit') this.openEditNode(node);
    else if (item.id === 'limit') this.openLimit(node);
    else if (item.id === 'child') this.startAddChild(node);
    else this.askDeleteNode(node);
  }

  /** The header menu on a phone: the toolbar actions except "Budget anlegen". */
  readonly headerMenu = computed<RowMenuSection[]>(() => {
    const t = (k: TranslationKey): string => this.i18n.translate(k);
    const noTop = this.selectedTopId() ? null : t('budget.tree.pickHint');
    return [
      {
        items: [
          { id: 'states', label: t('budget.tree.stateConfig'), disabledReason: noTop },
          { id: 'cutoff', label: t('budget.tree.stichtagTitle'), disabledReason: noTop },
          { id: 'fy', label: t('budget.tree.fyTitle'), icon: 'cal', disabledReason: noTop },
        ],
      },
    ];
  });

  onHeaderMenu(item: RowMenuItem): void {
    if (item.id === 'states') this.openStateConfig();
    else if (item.id === 'cutoff') this.openStichtag();
    else this.openFy();
  }

  /** Load sequence counter. It increases for each load. A response of an older
   *  load can arrive after a newer one. The sequence check drops it. Without the
   *  check it overwrites the fiscal year and the selection. */
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
        this.loading.set(false);
        if (topId) this.loadFiscalYears(topId);
        else this.fiscalYears.set([]);
      },
      error: () => {
        if (seq !== this.reloadSeq) return;
        this.loadError.set(true);
        this.loading.set(false);
      },
    });
  }

  /** Load the fiscal years of a budget. The first active year (else the newest) is the
   *  default; a year that still exists stays selected. */
  private loadFiscalYears(topId: string): void {
    const seq = ++this.reloadSeq;
    this.api.listFiscalYears(topId as Uuid).subscribe({
      next: (fys) => {
        if (seq !== this.reloadSeq) return;
        this.fiscalYears.set(fys);
        if (!fys.some((fy) => fy.id === this.selectedFyId())) this.selectedFyId.set(defaultFy(fys));
      },
      error: () => {
        if (seq !== this.reloadSeq) return;
        this.fiscalYears.set([]);
      },
    });
  }

  selectTop(id: string): void {
    if (!id) return;
    this.selectedTopId.set(id);
    this.selectedFyId.set('');
    this.addingChildOf.set(null);
    this.loadFiscalYears(id);
  }

  selectFy(id: string | null): void {
    if (id) this.selectedFyId.set(id);
  }

  /** Toggle a state key in the top budget's accepted/denied set. */
  toggleState(kind: 'accepted' | 'denied', key: string): void {
    const top = this.selectedTop();
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
      .updateNode(top.id, { acceptedStateKeys: [...accepted], deniedStateKeys: [...denied] })
      .subscribe({
        next: () => this.reload(),
        error: () => this.toast.error(this.i18n.translate('budget.tree.toast.failed')),
      });
  }

  // Create a top budget.
  patchTop<K extends 'key' | 'name'>(key: K, value: string): void {
    this.newTop.update((t) => ({ ...t, [key]: value }));
  }

  patchTopStichtag(key: 'fiscalStartMonth' | 'fiscalStartDay', value: string): void {
    this.newTop.update((t) => ({ ...t, [key]: clampCutoff(key, value) }));
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
          this.topOpen.set(false);
          this.selectedTopId.set(node.id);
          this.selectedFyId.set('');
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
    this.api.updateNode(top.id, { [key]: clampCutoff(key, value) }).subscribe({
      next: () => {
        this.toast.success(this.i18n.translate('budget.tree.toast.stichtagSaved'));
        this.reload();
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

  // The inline row for a sub cost centre.
  startAddChild(node: BudgetTreeNode): void {
    // The row stands at the end of the subtree, so the subtree must be open.
    this.collapsed.update((set) => {
      const next = new Set(set);
      next.delete(node.id);
      return next;
    });
    this.addingChildOf.set(node.id);
    this.childDraft.set({ key: '', name: '' });
    // The row can stand far below the button, after a large subtree. Move the focus to
    // its key field: the focus also scrolls the row into view inside the pane.
    afterNextRender(() => this.focusChildKey(), { injector: this.injector });
  }

  /** Focus the key field of the inline row for a sub cost centre, when it shows. */
  private focusChildKey(): void {
    const input = this.host.nativeElement.querySelector<HTMLInputElement>('.bt__child .bt__childKey input');
    if (!input) return;
    input.focus();
    input.scrollIntoView?.({ block: 'nearest' });
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

  // Delete a node after a confirmation.
  askDeleteNode(node: BudgetTreeNode): void {
    this.nodeDeleteBlocked.set(false);
    this.nodeDelete.set(node);
  }

  closeDeleteNode(): void {
    this.nodeDelete.set(null);
    this.nodeDeleteBlocked.set(false);
  }

  deleteNode(): void {
    const node = this.nodeDelete();
    if (!node) return;
    this.api.deleteNode(node.id).subscribe({
      next: () => {
        this.toast.success(this.i18n.translate('budget.tree.toast.deleted'));
        this.closeDeleteNode();
        if (node.id === this.selectedTopId()) this.selectedTopId.set('');
        this.reload();
      },
      error: (err: { status?: number }) => {
        // 409: the node still has sub cost centres or allocations. The dialog says so.
        if (err?.status === 409) {
          this.nodeDeleteBlocked.set(true);
          return;
        }
        this.toast.error(this.i18n.translate('budget.tree.toast.deleteFailed'));
      },
    });
  }

  // The edit dialog with every setting of a node.
  openEditNode(node: BudgetTreeNode): void {
    this.editNode.set(node);
    this.editKey.set(node.key);
    this.editName.set(node.name);
    this.editColor.set(node.color?.trim() ?? '');
    this.editActive.set(node.active);
    this.editHidden.set(node.hiddenInBudget);
    this.editViewGremium.set(node.viewGremiumId ?? '');
    this.editDecisionGremium.set(node.decisionGremiumId ?? '');
  }

  /**
   * The hint under the deciding-gremium select. Without an own value the node takes
   * the effective gremium of its parent (`effectiveDecisionGremiumId`, served by the
   * API), so the hint names the node that supplies it (`decisionGremiumSourceId`):
   * "Geerbt von …". Without one it says that no gremium decides.
   */
  readonly decisionGremiumHint = computed<string>(() => {
    const node = this.editNode();
    if (!node) return '';
    if (this.editDecisionGremium()) return this.i18n.translate('budget.tree.decisionGremiumHint');
    const parent = node.parentId ? this.findNode(node.parentId) : undefined;
    const gremiumId = parent?.effectiveDecisionGremiumId;
    const source = parent?.decisionGremiumSourceId
      ? this.findNode(parent.decisionGremiumSourceId)
      : undefined;
    if (!gremiumId || !source) return this.i18n.translate('budget.tree.decisionGremiumNoneHint');
    const gremium =
      this.gremiumOptions().find((o) => o.value === gremiumId)?.label ??
      this.i18n.translate('budget.tree.unknownGremium');
    return this.i18n.translate('budget.tree.decisionGremiumInherited', {
      path: source.pathKey,
      name: source.name,
      gremium,
    });
  });

  closeEditNode(): void {
    this.editNode.set(null);
  }

  /** The hex field takes any text; only `#rrggbb` (or empty) can be saved. */
  readonly editColorInvalid = computed(() => {
    const c = this.editColor();
    return c !== '' && !HEX_COLOR.test(c);
  });

  pickColor(color: string): void {
    this.editColor.set(color.toLowerCase());
  }

  clearColor(): void {
    this.editColor.set('');
  }

  saveEditNode(): void {
    const node = this.editNode();
    if (!node) return;
    const key = this.editKey().trim();
    const name = this.editName().trim();
    if (!key || !name || this.editColorInvalid()) return;
    this.api
      .updateNode(node.id, {
        key,
        name,
        // '' clears the own colour; the node then takes the colour of its parent.
        color: this.editColor(),
        active: this.editActive(),
        hiddenInBudget: this.editHidden(),
        viewGremiumId: this.editViewGremium() || null,
        // Send the deciding gremium only on a change: each sent field is audited.
        ...(this.editDecisionGremium() !== (node.decisionGremiumId ?? '')
          ? { decisionGremiumId: this.editDecisionGremium() || null }
          : {}),
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

  /** The label of the selected fiscal year ("2026"), for the limit dialog. */
  readonly selectedFyLabel = computed(
    () => this.fiscalYears().find((fy) => fy.id === this.selectedFyId())?.display ?? '',
  );

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
      next: (fy) => {
        this.toast.success(this.i18n.translate('budget.tree.toast.fyCreated'));
        this.fyOpen.set(false);
        this.selectedFyId.set(fy.id);
        this.loadFiscalYears(top);
      },
      error: () => this.toast.error(this.i18n.translate('budget.tree.toast.fyFailed')),
    });
  }

  // Correct or remove a fiscal year. Each runs in its own dialog. The manage dialog
  // closes first and opens again afterwards, so no two dialogs stack.
  openFyEdit(fy: FiscalYear): void {
    this.fyOpen.set(false);
    this.fyEdit.set(fy);
    this.fyEditYear.set(fy.year);
    this.fyEditActive.set(fy.active);
  }

  patchFyEditYear(value: string): void {
    this.fyEditYear.set(Math.trunc(Number(value)) || new Date().getFullYear());
  }

  closeFyEdit(): void {
    this.fyEdit.set(null);
    this.fyOpen.set(true);
  }

  saveFyEdit(): void {
    const fy = this.fyEdit();
    const top = this.selectedTopId();
    if (!fy || !top) return;
    this.api
      .updateFiscalYear(top as Uuid, fy.id, { year: this.fyEditYear(), active: this.fyEditActive() })
      .subscribe({
        next: () => {
          this.toast.success(this.i18n.translate('budget.tree.toast.fySaved'));
          this.closeFyEdit();
          this.loadFiscalYears(top);
        },
        // 422 means the year already exists in this budget. Name that reason.
        error: (err: { status?: number }) =>
          this.toast.error(
            this.i18n.translate(
              err?.status === 422 ? 'budget.tree.toast.fyDuplicate' : 'budget.tree.toast.fyFailed',
            ),
          ),
      });
  }

  askFyDelete(fy: FiscalYear): void {
    this.fyOpen.set(false);
    this.fyDeleteBlocked.set(null);
    this.fyDelete.set(fy);
  }

  closeFyDelete(): void {
    this.fyDelete.set(null);
    this.fyDeleteBlocked.set(null);
    this.fyOpen.set(true);
  }

  doFyDelete(): void {
    const fy = this.fyDelete();
    const top = this.selectedTopId();
    if (!fy || !top) return;
    this.api.deleteFiscalYear(top as Uuid, fy.id).subscribe({
      next: () => {
        this.toast.success(this.i18n.translate('budget.tree.toast.fyDeleted'));
        this.closeFyDelete();
        this.loadFiscalYears(top);
      },
      error: (err: { status?: number; error?: { detail?: string } }) => {
        // 409 keeps the dialog open and names the rows that still hang on the year.
        if (err?.status === 409) {
          const msg = this.i18n.translate(this.fyBlockerKey(err.error?.detail));
          this.fyDeleteBlocked.set(msg);
          this.toast.error(msg);
          return;
        }
        this.toast.error(this.i18n.translate('budget.tree.toast.fyDeleteFailed'));
      },
    });
  }

  /** Map the 409 problem detail to the concrete blocker. The backend names exactly one
   *  of `bookings`, `allocations` or `applications`. An unknown wording reads generic. */
  private fyBlockerKey(detail: string | undefined): TranslationKey {
    if (detail?.includes('bookings')) return 'budget.tree.fyBlocked.bookings';
    if (detail?.includes('allocations')) return 'budget.tree.fyBlocked.allocations';
    if (detail?.includes('applications')) return 'budget.tree.fyBlocked.applications';
    return 'budget.tree.fyBlocked.generic';
  }

  private findNode(id: string): BudgetTreeNode | undefined {
    const walk = (nodes: readonly BudgetTreeNode[]): BudgetTreeNode | undefined => {
      for (const n of nodes) {
        if (n.id === id) return n;
        const hit = walk(n.children);
        if (hit) return hit;
      }
      return undefined;
    };
    return walk(this.tree());
  }
}

/** The default year of a budget: the newest active year, else the newest year. */
function defaultFy(fys: readonly FiscalYear[]): string {
  const sorted = [...fys].sort((a, b) => b.year - a.year);
  return (sorted.find((fy) => fy.active) ?? sorted[0])?.id ?? '';
}

/** A cutoff part as a whole number in its range: month 1..12, day 1..28. */
function clampCutoff(key: 'fiscalStartMonth' | 'fiscalStartDay', value: string): number {
  const n = Math.trunc(Number(value)) || 1;
  const max = key === 'fiscalStartMonth' ? 12 : MAX_CUTOFF_DAY;
  return Math.min(max, Math.max(1, n));
}
