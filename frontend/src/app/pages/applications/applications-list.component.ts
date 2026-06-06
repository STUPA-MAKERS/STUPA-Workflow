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
import { stateBadgeVariant } from './applications.util';

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
  imports: [RouterLink, FormsModule, DatePipe, TranslatePipe, BadgeComponent, ButtonComponent],
  template: `
    <header class="apps__head">
      <h1 class="apps__title">{{ 'applications.list.title' | t }}</h1>
      <p class="apps__subtitle">{{ 'applications.list.subtitle' | t }}</p>
    </header>

    <form class="apps__filters" (submit)="applyFilters($event)" role="search">
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
        <select
          id="apps-type"
          class="field__control"
          [ngModel]="typeId()"
          (ngModelChange)="typeId.set($event)"
          name="type"
        >
          <option value="">{{ 'applications.list.filter.all' | t }}</option>
          @for (type of types(); track type.id) {
            <option [value]="type.id">{{ type.name }}</option>
          }
        </select>
      </div>

      <div class="field">
        <label class="field__label" [for]="'apps-state'">{{ 'applications.list.filter.state' | t }}</label>
        <input
          id="apps-state"
          class="field__control"
          type="text"
          [ngModel]="state()"
          (ngModelChange)="state.set($event)"
          name="state"
        />
      </div>

      <div class="apps__filterActions">
        <app-button type="submit" size="sm">{{ 'applications.list.filter.apply' | t }}</app-button>
        <app-button type="button" variant="ghost" size="sm" (click)="reset()">
          {{ 'applications.list.filter.reset' | t }}
        </app-button>
      </div>
    </form>

    @if (loading()) {
      <p class="apps__status" aria-live="polite">{{ 'applications.list.loading' | t }}</p>
    } @else if (error()) {
      <p class="apps__status apps__status--error" role="alert">
        {{ 'applications.list.error' | t }}
      </p>
    } @else {
      <div class="apps__tableWrap">
        <table class="apps__table">
          <caption class="apps__caption">
            {{ 'applications.list.count' | t: { count: items().length, total: total() } }}
          </caption>
          <thead>
            <tr>
              <th scope="col">{{ 'applications.list.col.type' | t }}</th>
              <th scope="col">{{ 'applications.list.col.state' | t }}</th>
              <th scope="col" class="apps__num">{{ 'applications.list.col.amount' | t }}</th>
              <th scope="col">{{ 'applications.list.col.created' | t }}</th>
            </tr>
          </thead>
          <tbody>
            @for (item of items(); track item.id) {
              <tr>
                <td>
                  <a class="apps__rowLink" [routerLink]="['/applications', item.id]">
                    {{ typeName(item.typeId) }}
                    <span class="apps__rowHint">{{ 'applications.list.open' | t }}</span>
                  </a>
                </td>
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
                <td class="apps__empty" colspan="4">{{ 'applications.list.empty' | t }}</td>
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
  `,
  styles: [
    `
      .apps__head {
        margin-bottom: var(--space-5);
      }
      .apps__subtitle {
        color: var(--color-text-muted);
      }
      .apps__filters {
        display: flex;
        flex-wrap: wrap;
        align-items: flex-end;
        gap: var(--space-4);
        margin-bottom: var(--space-5);
        padding: var(--space-4);
        background: var(--color-surface);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-md);
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
      }
      .apps__table {
        width: 100%;
        border-collapse: collapse;
        font-size: var(--fs-sm);
      }
      .apps__caption {
        text-align: start;
        padding-bottom: var(--space-3);
        color: var(--color-text-muted);
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
  private readonly i18n = inject(I18nService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  readonly limit = 20;

  readonly loading = signal(true);
  readonly error = signal(false);
  private readonly result = signal<Page<ApplicationListItem> | null>(null);
  readonly types = signal<ApplicationType[]>([]);

  /** Sichtbare Filter-Controls (gespiegelt aus den Query-Params). */
  readonly q = signal('');
  readonly typeId = signal('');
  readonly state = signal('');

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

    this.route.queryParamMap.pipe(takeUntilDestroyed()).subscribe((pm) => {
      this.q.set(pm.get('q') ?? '');
      this.typeId.set(pm.get('type') ?? '');
      this.state.set(pm.get('state') ?? '');
      this.load(pm);
    });
  }

  typeName(typeId: Uuid): string {
    return this.typesById().get(typeId) ?? typeId;
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

  applyFilters(event: Event): void {
    event.preventDefault();
    this.navigate({
      q: this.q() || null,
      type: this.typeId() || null,
      state: this.state() || null,
      offset: null,
    });
  }

  reset(): void {
    this.q.set('');
    this.typeId.set('');
    this.state.set('');
    this.navigate({ q: null, type: null, state: null, gremium: null, topf: null, offset: null });
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
    if (q) query.q = q;
    if (type) query.type = type;
    if (state) query.state = state;
    if (gremium) query.gremium = gremium;
    if (topf) query.topf = topf;

    this.loading.set(true);
    this.error.set(false);
    this.api.listApplications(query).subscribe({
      next: (page) => {
        this.result.set(page);
        this.loading.set(false);
      },
      error: () => {
        this.error.set(true);
        this.loading.set(false);
      },
    });
  }
}
