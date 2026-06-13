import {
  ChangeDetectionStrategy,
  Component,
  type ElementRef,
  computed,
  effect,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { ApiClient } from '@core/api/api-client.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type {
  ApplicationListItem,
  ApplicationListQuery,
  ApplicationType,
  Uuid,
} from '@core/api/models';
import { ButtonComponent } from '@shared/ui/button/button.component';
import {
  CurrencyInputComponent,
  DatepickerComponent,
  FilterBarComponent,
  FilterFieldComponent,
  FilterRangeComponent,
  IconComponent,
  SelectComponent,
  type SelectOption,
} from '@shared/ui';
import { BudgetTreeApi, type BudgetTreeNode } from '../budget/budget-tree.api';
import { CostCentreTreeComponent } from '../budget/cost-centre-tree.component';
import {
  ApplicationsTableComponent,
  type ApplicationRow,
  type SortState,
} from './applications-table.component';
import { AuthService } from '@core/auth/auth.service';
import { downloadBlob } from '@shared/download.util';

/**
 * Antrags-Liste (T-31, overview §4): Filter/Suche (`state/gremium/type/topf/q`)
 * + Offset-Paging. Der Filter-/Seitenzustand lebt in den **Query-Params** der
 * Route — so ist eine gefilterte Liste teil-/verlinkbar (z. B. aus dem Budget-
 * Bereich) und der Browser-Back funktioniert. Sichtbare Controls gibt es für
 * Suche/Typ/Status; `gremium`/`topf` werden aus der URL übernommen (Picker
 * folgen mit den Gremien-/Topf-Listen-Endpunkten aus T-24/Budget).
 */
@Component({
  selector: 'app-applications-list',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslatePipe, ButtonComponent, IconComponent, SelectComponent, CurrencyInputComponent, DatepickerComponent, FilterBarComponent, FilterFieldComponent, FilterRangeComponent, CostCentreTreeComponent, ApplicationsTableComponent],
  templateUrl: './applications-list.component.html',
  styleUrl: './applications-list.component.scss',
})
export class ApplicationsListComponent {
  private readonly api = inject(ApiClient);
  private readonly budgetApi = inject(BudgetTreeApi);
  private readonly i18n = inject(I18nService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly auth = inject(AuthService);

  readonly canExport = computed(() => this.auth.can('application.export'));
  readonly exporting = signal(false);

  readonly limit = 20;

  /** Erst-Ladevorgang (Filter-/Sortier-Wechsel) — blendet die ganze Liste aus. */
  readonly loading = signal(true);
  /** Nachladen weiterer Seiten beim Scrollen (inkrementell, Liste bleibt sichtbar). */
  readonly loadingMore = signal(false);
  readonly error = signal(false);
  /** Akkumulierte Anträge über alle bisher geladenen Seiten (Infinite-Scroll). */
  readonly items = signal<ApplicationListItem[]>([]);
  readonly total = signal(0);
  /** Offset der **nächsten** zu ladenden Seite. */
  private nextOffset = 0;
  /** Lauf-Nummer der Fetches: verspätete Antworten alter Filter werden verworfen. */
  private fetchSeq = 0;
  /** `gremium`/`topf` haben keine sichtbaren Controls — aus der URL gespiegelt. */
  private gremium = '';
  private topf = '';
  readonly types = signal<ApplicationType[]>([]);

  /** Sichtbare Filter-Controls (gespiegelt aus den Query-Params). */
  readonly q = signal('');
  readonly typeId = signal('');
  readonly state = signal('');

  readonly amountMin = signal('');
  readonly amountMax = signal('');
  readonly createdFrom = signal('');
  readonly createdTo = signal('');
  readonly budgetId = signal('');
  /** Kostenstellen-Baum für den linken Tree-Picker (gleiche Optik wie Budget-Tab). */
  readonly budgetTree = signal<BudgetTreeNode[]>([]);

  /** Im Budget-Tab ausgeblendete Kostenstellen (+ Unterbaum) aus dem Filter-Baum
   *  entfernen — spiegelt `visibleTree` des Budget-Dashboards (#budget-hide). */
  private pruneHidden(nodes: BudgetTreeNode[]): BudgetTreeNode[] {
    return nodes
      .filter((n) => !n.hiddenInBudget)
      .map((n) => ({ ...n, children: this.pruneHidden(n.children) }));
  }
  /** Mobil: Baum hinter einklappbarem Toggle (Desktop immer sichtbar). */
  readonly treeOpen = signal(false);
  readonly sortField = signal<'createdAt' | 'amount'>('createdAt');
  readonly sortOrder = signal<'asc' | 'desc'>('desc');

  /** Zahl aktiver Filter (für den Indikator). */
  readonly activeFilterCount = computed(
    () =>
      [
        this.q(),
        this.typeId(),
        this.state(),
        this.amountMin(),
        this.amountMax(),
        this.createdFrom(),
        this.createdTo(),
      ].filter((v) => String(v ?? '').trim() !== '').length,
  );

  /**
   * Status-Dropdown-Optionen aus den **realen** Status der geladenen Anträge
   * akkumuliert (Wert = State-UUID, Label = aufgelöster State-Name). Der gesendete
   * `state`-Filterwert bleibt die UUID (Contract: `current_state_id`). Einmal
   * gesehene Status bleiben erhalten, damit der Filter nicht auf einen Wert kollabiert.
   */
  private readonly seenStates = signal<Map<string, string>>(new Map());
  readonly stateOptions = computed<SelectOption[]>(() =>
    [...this.seenStates()].map(([value, label]) => ({ value, label })),
  );

  /** Noch ungeladene Anträge vorhanden? Steuert Sentinel + „Mehr laden". */
  readonly hasMore = computed(() => this.items().length < this.total());

  /** Sentinel am Listenende — sein Sichtbarwerden löst das Nachladen aus. */
  readonly sentinel = viewChild<ElementRef<HTMLElement>>('sentinel');

  private readonly typesById = computed(
    () => new Map(this.types().map((t) => [t.id, t.name])),
  );

  /** Antrags-Zeilen für die geteilte Tabelle. */
  readonly tableRows = computed<ApplicationRow[]>(() =>
    this.items().map((item) => ({
      id: item.id,
      title: this.titleOf(item),
      typeLabel: this.typeName(item.typeId),
      stateLabel: item.state?.label ?? null,
      stateColor: item.state?.color ?? null,
      amount: item.amount ?? null,
      currency: item.currency ?? null,
      createdAt: item.createdAt ?? null,
    })),
  );
  readonly sortState = computed<SortState>(() => ({
    field: this.sortField(),
    order: this.sortOrder(),
  }));

  constructor() {
    this.api.applicationTypes().subscribe({
      next: (types) => this.types.set(types),
      error: () => this.types.set([]),
    });
    // Kostenstellen-Baum für den linken Filter-Picker (eager). Im Budget-Tab
    // ausgeblendete Kostenstellen (`hiddenInBudget`) tauchen auch hier nicht auf.
    this.budgetApi.tree().subscribe({
      next: (tree) => this.budgetTree.set(this.pruneHidden(tree)),
      error: () => this.budgetTree.set([]),
    });

    // Filter/Sortierung leben in den Query-Params: jede Änderung setzt die Liste
    // zurück und lädt Seite 0 neu. Der Offset liegt **nicht** mehr in der URL
    // (Infinite-Scroll), sondern wird intern hochgezählt.
    this.route.queryParamMap.pipe(takeUntilDestroyed()).subscribe((pm) => {
      this.q.set(pm.get('q') ?? '');
      this.typeId.set(pm.get('type') ?? '');
      this.state.set(pm.get('state') ?? '');
      this.amountMin.set(pm.get('amountMin') ?? '');
      this.amountMax.set(pm.get('amountMax') ?? '');
      this.createdFrom.set(pm.get('createdFrom') ?? '');
      this.createdTo.set(pm.get('createdTo') ?? '');
      this.budgetId.set(pm.get('budget') ?? '');
      this.gremium = pm.get('gremium') ?? '';
      this.topf = pm.get('topf') ?? '';
      this.sortField.set(pm.get('sort') === 'amount' ? 'amount' : 'createdAt');
      this.sortOrder.set(pm.get('order') === 'asc' ? 'asc' : 'desc');
      this.reload();
    });

    // True-Lazy-Infinite-Scroll: ein IntersectionObserver am Sentinel lädt die
    // nächste Seite, sobald das Listenende in Sichtweite kommt (rootMargin als
    // Prefetch). Der Effect re-bindet, sobald der Sentinel (nur bei hasMore)
    // erscheint/verschwindet.
    effect((onCleanup) => {
      const el = this.sentinel()?.nativeElement;
      // Kein Observer ohne DOM-API (SSR/Tests) — der „Mehr laden"-Button bleibt Fallback.
      if (!el || typeof IntersectionObserver === 'undefined') return;
      const obs = new IntersectionObserver(
        (entries) => {
          if (entries.some((e) => e.isIntersecting)) this.loadMore();
        },
        { rootMargin: '400px' },
      );
      obs.observe(el);
      onCleanup(() => obs.disconnect());
    });
  }

  /** Kostenstelle im linken Baum wählen (``''`` = Alle); filtert die Liste. */
  selectBudgetNode(id: string): void {
    this.budgetId.set(id);
    this.navigate({ budget: id || null, offset: null });
  }

  typeName(typeId: Uuid): string {
    return this.typesById().get(typeId) ?? typeId;
  }

  /** Antragstitel (System-Titelfeld) mit Fallback „Ohne Titel". */
  titleOf(item: ApplicationListItem): string {
    return item.title?.trim() || this.i18n.translate('applications.list.untitled');
  }

  /** Reale Status der geladenen Anträge in die Dropdown-Optionen übernehmen. */
  private collectStates(items: ApplicationListItem[]): void {
    const next = new Map(this.seenStates());
    let changed = false;
    for (const item of items) {
      if (item.state && !next.has(item.state.id)) {
        next.set(item.state.id, item.state.label);
        changed = true;
      }
    }
    if (changed) this.seenStates.set(next);
  }

  /** Aktuelle Liste (Filter aus den Query-Params) als Excel exportieren. */
  onExport(): void {
    if (this.exporting()) return;
    this.exporting.set(true);
    const pm = this.route.snapshot.queryParamMap;
    const query: ApplicationListQuery = {};
    const str = (k: keyof ApplicationListQuery, p = k as string): void => {
      const v = pm.get(p);
      if (v) (query[k] as unknown) = v;
    };
    str('q'); str('type'); str('state'); str('gremium'); str('topf'); str('budget');
    str('createdFrom'); str('createdTo');
    const min = pm.get('amountMin'); if (min) query.amountMin = Number(min);
    const max = pm.get('amountMax'); if (max) query.amountMax = Number(max);
    const sort = pm.get('sort'); if (sort === 'amount' || sort === 'createdAt') query.sort = sort;
    const order = pm.get('order'); if (order === 'asc' || order === 'desc') query.order = order;
    this.api.exportApplicationsXlsx(query).subscribe({
      next: (blob) => {
        downloadBlob(blob, 'applications.xlsx');
        this.exporting.set(false);
      },
      error: () => this.exporting.set(false),
    });
  }

  applyFilters(): void {
    this.navigate({
      q: this.q() || null,
      type: this.typeId() || null,
      state: this.state() || null,
      amountMin: this.amountMin() ? Number(this.amountMin()) : null,
      amountMax: this.amountMax() ? Number(this.amountMax()) : null,
      createdFrom: this.createdFrom() || null,
      createdTo: this.createdTo() || null,
      budget: this.budgetId() || null,
      offset: null,
    });
  }

  reset(): void {
    this.q.set('');
    this.typeId.set('');
    this.state.set('');
    this.amountMin.set('');
    this.amountMax.set('');
    this.createdFrom.set('');
    this.createdTo.set('');
    this.budgetId.set('');
    this.navigate({
      q: null, type: null, state: null, gremium: null, topf: null, budget: null,
      amountMin: null, amountMax: null, createdFrom: null, createdTo: null, offset: null,
    });
  }

  /** Sortier-Event der geteilten Tabelle → in die Query-Params. */
  onSort(sort: SortState): void {
    this.navigate({ sort: sort.field, order: sort.order, offset: null });
  }

  /** Nächste Seite anhängen (Sentinel sichtbar oder „Mehr laden"-Button). */
  loadMore(): void {
    if (this.loadingMore() || this.loading() || !this.hasMore()) return;
    this.loadingMore.set(true);
    this.fetch(false);
  }

  private navigate(queryParams: Record<string, string | number | null>): void {
    this.router.navigate([], {
      relativeTo: this.route,
      queryParams,
      queryParamsHandling: 'merge',
    });
  }

  /** Liste zurücksetzen (Filter-/Sortier-Wechsel) und Seite 0 neu laden. */
  private reload(): void {
    this.nextOffset = 0;
    this.items.set([]);
    this.total.set(0);
    this.loadingMore.set(false);
    this.loading.set(true);
    this.error.set(false);
    this.fetch(true);
  }

  /** Query aus dem aktuellen Filter-Zustand für einen gegebenen Offset bauen. */
  private buildQuery(offset: number): ApplicationListQuery {
    const query: ApplicationListQuery = { limit: this.limit, offset };
    if (this.q().trim()) query.q = this.q().trim();
    if (this.typeId()) query.type = this.typeId();
    if (this.state()) query.state = this.state();
    if (this.gremium) query.gremium = this.gremium;
    if (this.topf) query.topf = this.topf;
    if (this.budgetId()) query.budget = this.budgetId();
    if (this.amountMin().trim()) query.amountMin = Number(this.amountMin());
    if (this.amountMax().trim()) query.amountMax = Number(this.amountMax());
    if (this.createdFrom().trim()) query.createdFrom = this.createdFrom();
    if (this.createdTo().trim()) query.createdTo = this.createdTo();
    query.sort = this.sortField();
    query.order = this.sortOrder();
    return query;
  }

  /**
   * Eine Seite holen. ``initial`` ersetzt die Liste (und zeigt bei Fehler den
   * Vollfehler), sonst wird angehängt (Fehler beim Nachladen bleibt still — die
   * bereits geladene Liste bleibt nutzbar).
   */
  private fetch(initial: boolean): void {
    // Lauf-Nummer gegen Out-of-order-Antworten: bei schnellen Filterwechseln darf
    // eine verspätete Seite des alten Filters die aktuelle Liste nicht überschreiben.
    const seq = ++this.fetchSeq;
    this.api.listApplications(this.buildQuery(this.nextOffset)).subscribe({
      next: (page) => {
        if (seq !== this.fetchSeq) return;
        this.total.set(page.total);
        this.items.update((cur) => (initial ? page.items : [...cur, ...page.items]));
        // Über die tatsächliche Trefferzahl hochzählen (letzte Seite < limit).
        this.nextOffset = page.offset + page.items.length;
        this.collectStates(page.items);
        this.loading.set(false);
        this.loadingMore.set(false);
      },
      error: () => {
        if (seq !== this.fetchSeq) return;
        if (initial) this.error.set(true);
        this.loading.set(false);
        this.loadingMore.set(false);
      },
    });
  }
}
