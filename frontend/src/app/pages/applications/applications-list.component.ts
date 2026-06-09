import { DatePipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, type ParamMap, Router, RouterLink } from '@angular/router';
import { ApiClient } from '@core/api/api-client.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type {
  ApplicationListItem,
  ApplicationListQuery,
  ApplicationType,
  Page,
  Uuid,
} from '@core/api/models';
import { BadgeComponent } from '@shared/ui/badge/badge.component';
import { ButtonComponent } from '@shared/ui/button/button.component';
import { IconComponent, SelectComponent, type SelectOption } from '@shared/ui';
import { BudgetTreeApi, type BudgetTreeNode } from '../budget/budget-tree.api';
import { CostCentreTreeComponent } from '../budget/cost-centre-tree.component';
import { stateBadgeVariant } from './applications.util';
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
  imports: [RouterLink, FormsModule, DatePipe, TranslatePipe, BadgeComponent, ButtonComponent, IconComponent, SelectComponent, CostCentreTreeComponent],
  template: `
    <header class="apps__head">
      <div class="apps__headRow">
        <div>
          <h1 class="apps__title">{{ 'applications.list.title' | t }}</h1>
          <p class="apps__subtitle">{{ 'applications.list.subtitle' | t }}</p>
        </div>
        <!-- Filter in einem Popout (#20): Button mit Icon + Aktiv-Indikator. -->
        <div class="apps__headActions">
          @if (canExport()) {
            <app-button variant="secondary" size="sm" (click)="onExport()" [loading]="exporting()">
              <span class="apps__filterBtn">
                <app-icon name="export" [size]="16" />
                {{ 'applications.list.export' | t }}
              </span>
            </app-button>
          }
          <div class="apps__filterWrap">
          <app-button variant="secondary" size="sm" (click)="toggleFilters()">
            <span class="apps__filterBtn">
              <app-icon name="filter" [size]="16" />
              {{ 'applications.list.filter.button' | t }}
              @if (activeFilterCount() > 0) {
                <span class="apps__filterCount" aria-hidden="true">{{ activeFilterCount() }}</span>
              }
            </span>
          </app-button>
          @if (filtersOpen()) {
            <form class="apps__filterPanel" (submit)="applyFilters($event)" role="search">
              <div class="field">
                <label class="field__label" [for]="'apps-q'">{{ 'applications.list.search' | t }}</label>
                <input
                  id="apps-q"
                  class="field__control"
                  type="search"
                  [placeholder]="'applications.list.search.placeholder' | t"
                  [ngModel]="q()"
                  (ngModelChange)="q.set($event)"
                  name="q"
                />
              </div>
              <div class="field">
                <label class="field__label" [for]="'apps-type'">{{ 'applications.list.filter.type' | t }}</label>
                <select id="apps-type" class="field__control" [ngModel]="typeId()" (ngModelChange)="typeId.set($event)" name="type">
                  <option value="">{{ 'applications.list.filter.all' | t }}</option>
                  @for (type of types(); track type.id) {
                    <option [value]="type.id">{{ type.name }}</option>
                  }
                </select>
              </div>
              <div class="field">
                <app-select
                  id="apps-state"
                  name="state"
                  [label]="'applications.list.filter.state' | t"
                  [placeholder]="'applications.list.filter.all' | t"
                  [options]="stateOptions()"
                  [ngModel]="state()"
                  (ngModelChange)="state.set($event)"
                />
              </div>
              <div class="field">
                <span class="field__label">{{ 'applications.list.filter.amount' | t }}</span>
                <div class="apps__range">
                  <input type="number" min="0" step="1" class="field__control" [placeholder]="'applications.list.filter.min' | t" [attr.aria-label]="'applications.list.filter.min' | t" [ngModel]="amountMin()" (ngModelChange)="amountMin.set($event)" name="amountMin" />
                  <span class="apps__rangeSep">–</span>
                  <input type="number" min="0" step="1" class="field__control" [placeholder]="'applications.list.filter.max' | t" [attr.aria-label]="'applications.list.filter.max' | t" [ngModel]="amountMax()" (ngModelChange)="amountMax.set($event)" name="amountMax" />
                </div>
              </div>
              <div class="field">
                <span class="field__label">{{ 'applications.list.filter.date' | t }}</span>
                <div class="apps__range">
                  <input type="date" class="field__control" [attr.aria-label]="'applications.list.filter.from' | t" [ngModel]="createdFrom()" (ngModelChange)="createdFrom.set($event)" name="createdFrom" />
                  <span class="apps__rangeSep">–</span>
                  <input type="date" class="field__control" [attr.aria-label]="'applications.list.filter.to' | t" [ngModel]="createdTo()" (ngModelChange)="createdTo.set($event)" name="createdTo" />
                </div>
              </div>
              <div class="apps__filterActions">
                <app-button type="submit" size="sm">{{ 'applications.list.filter.apply' | t }}</app-button>
                <app-button type="button" variant="ghost" size="sm" (click)="reset()">
                  {{ 'applications.list.filter.reset' | t }}
                </app-button>
              </div>
            </form>
          }
          </div>
        </div>
      </div>
    </header>

    <div class="apps__layout">
    <aside class="apps__tree">
      <app-cost-centre-tree
        [nodes]="budgetTree()"
        [selectedId]="budgetId()"
        [allLabel]="'applications.list.filter.all' | t"
        [ariaLabel]="'applications.list.filter.budget' | t"
        (picked)="selectBudgetNode($event)"
      />
    </aside>
    <div class="apps__main">
    @if (loading()) {
      <p class="apps__status" aria-live="polite">{{ 'applications.list.loading' | t }}</p>
    } @else if (error()) {
      <p class="apps__status apps__status--error" role="alert">
        {{ 'applications.list.error' | t }}
      </p>
    } @else {
      <div class="apps__tableWrap">
        <table class="apps__table">
          <thead>
            <tr>
              <th scope="col">{{ 'applications.list.col.title' | t }}</th>
              <th scope="col">{{ 'applications.list.col.type' | t }}</th>
              <th scope="col">{{ 'applications.list.col.state' | t }}</th>
              <th scope="col" class="apps__num" [attr.aria-sort]="ariaSort('amount')">
                <button type="button" class="apps__sort" (click)="sortBy('amount')">{{ 'applications.list.col.amount' | t }}{{ sortIndicator('amount') }}</button>
              </th>
              <th scope="col" [attr.aria-sort]="ariaSort('createdAt')">
                <button type="button" class="apps__sort" (click)="sortBy('createdAt')">{{ 'applications.list.col.created' | t }}{{ sortIndicator('createdAt') }}</button>
              </th>
            </tr>
          </thead>
          <tbody>
            @for (item of items(); track item.id) {
              <tr>
                <td>
                  <a class="apps__rowLink" [routerLink]="['/applications', item.id]">
                    {{ titleOf(item) }}
                    <span class="apps__rowHint">{{ 'applications.list.open' | t }}</span>
                  </a>
                </td>
                <td>{{ typeName(item.typeId) }}</td>
                <td>
                  @if (item.state) {
                    <app-badge [variant]="stateVariant(item.state.category)">
                      {{ item.state.label }}
                    </app-badge>
                  } @else {
                    —
                  }
                </td>
                <td class="apps__num">{{ amount(item) }}</td>
                <td>
                  <time [attr.datetime]="item.createdAt">{{ item.createdAt | date: 'mediumDate' }}</time>
                </td>
              </tr>
            } @empty {
              <tr>
                <td class="apps__empty" colspan="5">{{ 'applications.list.empty' | t }}</td>
              </tr>
            }
          </tbody>
        </table>
      </div>

      @if (total() > limit) {
        <nav class="apps__pager" [attr.aria-label]="'applications.list.title' | t">
          <app-button
            variant="secondary"
            size="sm"
            [disabled]="!hasPrev()"
            (click)="prev()"
          >
            ← {{ 'applications.list.prev' | t }}
          </app-button>
          <span class="apps__pageInfo">
            {{ 'applications.list.page' | t: { page: pageNumber(), pages: pageCount() } }}
          </span>
          <app-button
            variant="secondary"
            size="sm"
            [disabled]="!hasNext()"
            (click)="next()"
          >
            {{ 'applications.list.next' | t }} →
          </app-button>
        </nav>
      }
    }
    </div>
    </div>
  `,
  styles: [
    `
      /* Body (Kopf + Tabelle) auf normale Breite zentriert; der Baum sitzt im
         linken Rand außerhalb des Bodys (Breakout, wie der Budget-Tab). */
      .apps__head {
        width: 100%;
        max-width: var(--layout-max-width);
        margin-inline: auto;
        margin-bottom: var(--space-5);
      }
      .apps__layout {
        display: grid;
        grid-template-columns:
          minmax(12rem, 1fr)
          minmax(0, var(--layout-max-width))
          minmax(0, 1fr);
        gap: var(--space-5);
        align-items: start;
      }
      .apps__main {
        min-width: 0;
      }
      .apps__tree {
        justify-self: end;
        width: 100%;
        max-width: 16rem;
        position: sticky;
        top: var(--space-4);
        max-height: calc(100vh - 8rem);
        overflow-y: auto;
      }
      @media (max-width: 60rem) {
        .apps__layout {
          grid-template-columns: minmax(11rem, 14rem) minmax(0, 1fr);
        }
        .apps__head {
          max-width: none;
        }
      }
      @media (max-width: 40rem) {
        .apps__layout {
          grid-template-columns: 1fr;
        }
        .apps__tree {
          position: static;
          max-height: none;
        }
      }
      .apps__headRow {
        display: flex;
        align-items: start;
        justify-content: space-between;
        gap: var(--space-4);
        flex-wrap: wrap;
      }
      .apps__subtitle {
        color: var(--color-text-muted);
      }
      .apps__headActions {
        display: flex;
        align-items: center;
        gap: var(--space-2);
      }
      .apps__filterWrap {
        position: relative;
      }
      .apps__filterBtn {
        display: inline-flex;
        align-items: center;
        gap: var(--space-2);
      }
      .apps__filterCount {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 1.25rem;
        height: 1.25rem;
        padding: 0 var(--space-1);
        margin-left: var(--space-2);
        border-radius: 999px;
        background: var(--color-primary);
        color: var(--color-on-primary, #fff);
        font-size: var(--fs-xs);
        font-weight: var(--fw-bold);
      }
      .apps__filterPanel {
        position: absolute;
        right: 0;
        z-index: var(--z-dropdown, 50);
        margin-top: var(--space-2);
        width: min(22rem, 90vw);
        max-height: 80vh;
        overflow-y: auto;
        display: flex;
        flex-direction: column;
        gap: var(--space-4);
        padding: var(--space-4);
        background: var(--color-bg-elevated, var(--color-surface));
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-lg);
        box-shadow: var(--shadow-lg);
      }
      /* Im senkrechten Popout duerfen die Felder NICHT vertikal wachsen
         (die geteilte .field-Regel hat flex 1 1 12rem fuer die alte Zeile). */
      .apps__filterPanel .field {
        flex: 0 0 auto;
        min-width: 0;
      }
      .field {
        display: flex;
        flex-direction: column;
        gap: var(--space-1);
        min-width: 12rem;
        flex: 1 1 12rem;
      }
      .field__label {
        font-size: var(--fs-sm);
        font-weight: var(--fw-medium);
        color: var(--color-text-muted);
      }
      .field__control {
        height: var(--control-height);
        padding: 0 var(--space-3);
        background: var(--color-bg);
        color: var(--color-text);
        border: var(--border-width) solid var(--color-border-strong);
        border-radius: var(--radius-md);
        font-size: var(--fs-md);
      }
      .field__control:focus-visible {
        outline: 2px solid var(--color-primary);
        outline-offset: 1px;
      }
      .apps__filterActions {
        display: flex;
        gap: var(--space-2);
      }
      .apps__status {
        color: var(--color-text-muted);
        padding: var(--space-5) 0;
      }
      .apps__status--error {
        color: var(--color-danger);
      }
      .apps__tableWrap {
        overflow-x: auto;
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-lg);
        background: var(--color-surface);
      }
      .apps__table {
        width: 100%;
        border-collapse: collapse;
        font-size: var(--fs-sm);
      }
      .apps__table tbody tr:last-child td {
        border-bottom: none;
      }
      .apps__table th,
      .apps__table td {
        padding: var(--space-3) var(--space-4);
        border-bottom: var(--border-width) solid var(--color-border);
        text-align: start;
        vertical-align: middle;
      }
      .apps__table th {
        font-weight: var(--fw-semibold);
        color: var(--color-text-muted);
        text-transform: uppercase;
        letter-spacing: 0.04em;
        font-size: var(--fs-xs);
      }
      .apps__num {
        text-align: end;
        font-variant-numeric: tabular-nums;
      }
      .apps__range {
        display: flex;
        align-items: center;
        gap: var(--space-2);
      }
      /* Min/Max + Datumsfelder teilen die Breite gleichmäßig und laufen nicht
         über den Panel-Rand (kein horizontaler Scroll, keine Clipping). */
      .apps__range .field__control {
        flex: 1 1 0;
        min-width: 0;
        width: 100%;
      }
      /* Zahlen-Spinner ausblenden — wirkt im schmalen Popout unruhig. */
      .apps__range input[type='number'] {
        -moz-appearance: textfield;
        appearance: textfield;
      }
      .apps__range input[type='number']::-webkit-outer-spin-button,
      .apps__range input[type='number']::-webkit-inner-spin-button {
        -webkit-appearance: none;
        margin: 0;
      }
      .apps__rangeSep {
        color: var(--color-text-muted);
        flex: 0 0 auto;
      }
      .apps__sort {
        background: transparent;
        border: 0;
        padding: 0;
        cursor: pointer;
        font: inherit;
        color: inherit;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        font-size: var(--fs-xs);
        font-weight: var(--fw-semibold);
      }
      .apps__sort:hover {
        color: var(--color-primary);
      }
      .apps__table tbody tr:hover {
        background: var(--color-surface-sunken);
      }
      .apps__rowLink {
        display: inline-flex;
        flex-direction: column;
        color: var(--color-primary);
        font-weight: var(--fw-medium);
        text-decoration: none;
      }
      .apps__rowLink:hover {
        text-decoration: underline;
      }
      .apps__rowHint {
        font-size: var(--fs-xs);
        color: var(--color-text-muted);
        font-weight: var(--fw-normal);
      }
      .apps__empty {
        text-align: center;
        color: var(--color-text-muted);
        padding: var(--space-6);
      }
      .apps__pager {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: var(--space-4);
        margin-top: var(--space-5);
      }
      .apps__pageInfo {
        color: var(--color-text-muted);
        font-size: var(--fs-sm);
      }
    `,
  ],
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

  readonly loading = signal(true);
  readonly error = signal(false);
  private readonly result = signal<Page<ApplicationListItem> | null>(null);
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
  readonly sortField = signal<'createdAt' | 'amount'>('createdAt');
  readonly sortOrder = signal<'asc' | 'desc'>('desc');

  /** Filter-Popout offen? + Zahl aktiver Filter (für den Indikator). */
  readonly filtersOpen = signal(false);
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

  readonly items = computed(() => this.result()?.items ?? []);
  readonly total = computed(() => this.result()?.total ?? 0);
  private readonly offset = computed(() => this.result()?.offset ?? 0);
  readonly pageCount = computed(() => Math.max(1, Math.ceil(this.total() / this.limit)));
  readonly pageNumber = computed(() => Math.floor(this.offset() / this.limit) + 1);
  readonly hasPrev = computed(() => this.offset() > 0);
  readonly hasNext = computed(() => this.offset() + this.limit < this.total());

  private readonly typesById = computed(
    () => new Map(this.types().map((t) => [t.id, t.name])),
  );

  readonly stateVariant = stateBadgeVariant;

  constructor() {
    this.api.applicationTypes().subscribe({
      next: (types) => this.types.set(types),
      error: () => this.types.set([]),
    });
    // Kostenstellen-Baum für den linken Filter-Picker (eager).
    this.budgetApi.tree().subscribe({
      next: (tree) => this.budgetTree.set(tree),
      error: () => this.budgetTree.set([]),
    });

    this.route.queryParamMap.pipe(takeUntilDestroyed()).subscribe((pm) => {
      this.q.set(pm.get('q') ?? '');
      this.typeId.set(pm.get('type') ?? '');
      this.state.set(pm.get('state') ?? '');
      this.amountMin.set(pm.get('amountMin') ?? '');
      this.amountMax.set(pm.get('amountMax') ?? '');
      this.createdFrom.set(pm.get('createdFrom') ?? '');
      this.createdTo.set(pm.get('createdTo') ?? '');
      this.budgetId.set(pm.get('budget') ?? '');
      this.sortField.set(pm.get('sort') === 'amount' ? 'amount' : 'createdAt');
      this.sortOrder.set(pm.get('order') === 'asc' ? 'asc' : 'desc');
      this.load(pm);
    });
  }

  toggleFilters(): void {
    this.filtersOpen.update((v) => !v);
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

  amount(item: ApplicationListItem): string {
    if (item.amount === null) return this.i18n.translate('applications.detail.notProvided');
    const value = Number(item.amount);
    if (Number.isNaN(value)) return item.amount;
    return new Intl.NumberFormat(this.i18n.locale(), {
      style: 'currency',
      currency: item.currency ?? 'EUR',
    }).format(value);
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

  applyFilters(event: Event): void {
    event.preventDefault();
    this.filtersOpen.set(false);
    this.navigate({
      q: this.q() || null,
      type: this.typeId() || null,
      state: this.state() || null,
      amountMin: this.amountMin() || null,
      amountMax: this.amountMax() || null,
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
    this.filtersOpen.set(false);
    this.navigate({
      q: null, type: null, state: null, gremium: null, topf: null, budget: null,
      amountMin: null, amountMax: null, createdFrom: null, createdTo: null, offset: null,
    });
  }

  /** Spalte sortieren: gleiche Spalte → Richtung toggeln, sonst neue Spalte (Default desc). */
  sortBy(field: 'createdAt' | 'amount'): void {
    const order = this.sortField() === field && this.sortOrder() === 'desc' ? 'asc' : 'desc';
    this.navigate({ sort: field, order, offset: null });
  }

  sortIndicator(field: 'createdAt' | 'amount'): string {
    if (this.sortField() !== field) return '';
    return this.sortOrder() === 'asc' ? ' ↑' : ' ↓';
  }

  ariaSort(field: 'createdAt' | 'amount'): 'ascending' | 'descending' | 'none' {
    if (this.sortField() !== field) return 'none';
    return this.sortOrder() === 'asc' ? 'ascending' : 'descending';
  }

  prev(): void {
    this.navigate({ offset: Math.max(0, this.offset() - this.limit) || null });
  }

  next(): void {
    this.navigate({ offset: this.offset() + this.limit });
  }

  private navigate(queryParams: Record<string, string | number | null>): void {
    this.router.navigate([], {
      relativeTo: this.route,
      queryParams,
      queryParamsHandling: 'merge',
    });
  }

  private load(pm: ParamMap): void {
    const query: ApplicationListQuery = {
      limit: this.limit,
      offset: Number(pm.get('offset') ?? 0) || 0,
    };
    const q = pm.get('q');
    const type = pm.get('type');
    const state = pm.get('state');
    const gremium = pm.get('gremium');
    const topf = pm.get('topf');
    const budget = pm.get('budget');
    const amountMin = pm.get('amountMin');
    const amountMax = pm.get('amountMax');
    const createdFrom = pm.get('createdFrom');
    const createdTo = pm.get('createdTo');
    const sort = pm.get('sort');
    const order = pm.get('order');
    if (q) query.q = q;
    if (type) query.type = type;
    if (state) query.state = state;
    if (gremium) query.gremium = gremium;
    if (topf) query.topf = topf;
    if (budget) query.budget = budget;
    if (amountMin) query.amountMin = Number(amountMin);
    if (amountMax) query.amountMax = Number(amountMax);
    if (createdFrom) query.createdFrom = createdFrom;
    if (createdTo) query.createdTo = createdTo;
    if (sort === 'amount' || sort === 'createdAt') query.sort = sort;
    if (order === 'asc' || order === 'desc') query.order = order;

    this.loading.set(true);
    this.error.set(false);
    this.api.listApplications(query).subscribe({
      next: (page) => {
        this.result.set(page);
        this.collectStates(page.items);
        this.loading.set(false);
      },
      error: () => {
        this.error.set(true);
        this.loading.set(false);
      },
    });
  }
}
