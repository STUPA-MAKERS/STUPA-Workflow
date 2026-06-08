import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, type ParamMap, Router } from '@angular/router';
import { of } from 'rxjs';
import { catchError, switchMap } from 'rxjs/operators';
import { ApiClient } from '@core/api/api-client.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { BudgetPotInfo, BudgetStats } from '@core/api/models';
import { ButtonComponent } from '@shared/ui/button/button.component';
import { SelectComponent, type SelectOption } from '@shared/ui';
import { AdminOptionsService } from '../admin/admin-options.service';
import { type BudgetKpis, formatMoney, kpiTotals } from './budget.util';
import { PotUsageComponent } from './pot-usage.component';
import { StatusDistributionComponent } from './status-distribution.component';

/**
 * Budget-Statistik-Dashboard (T-35, api.md »budget«, Rolle `budget.view`).
 *
 * Datenquelle ist **real** `GET /budget/stats` (kein toter Mock): Kennzahlen,
 * Auslastung je Topf und Statusverteilung. Filter (`pot`/`gremium`/`period`)
 * leben in den Query-Params → die gefilterte Sicht ist verlinkbar und Browser-
 * Back funktioniert. `GET /budget-pots` (P(budget.manage)) wird **best-effort**
 * dazugeladen, um Töpfe mit Namen statt roher UUID zu zeigen und die Topf-Auswahl
 * zu füllen; fehlt die Berechtigung (403), greift der gekürzte-ID-Fallback.
 */
@Component({
  selector: 'app-budget-dashboard',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    ButtonComponent,
    SelectComponent,
    PotUsageComponent,
    StatusDistributionComponent,
  ],
  template: `
    <header class="budget__head">
      <h1 class="budget__title">{{ 'budget.title' | t }}</h1>
      <p class="budget__subtitle">{{ 'budget.subtitle' | t }}</p>
    </header>

    <form class="budget__filters" (submit)="applyFilters($event)" role="search">
      <p class="budget__filtersLegend">{{ 'budget.filter.heading' | t }}</p>
      <div class="field">
        @if (pots().length) {
          <app-select
            id="budget-pot"
            name="pot"
            [label]="'budget.filter.pot' | t"
            [placeholder]="'budget.filter.all' | t"
            [options]="potOptions()"
            [ngModel]="pot()"
            (ngModelChange)="pot.set($event)"
          />
        } @else {
          <label class="field__label" for="budget-pot">{{ 'budget.filter.pot' | t }}</label>
          <input
            id="budget-pot"
            class="field__control"
            type="text"
            name="pot"
            [ngModel]="pot()"
            (ngModelChange)="pot.set($event)"
          />
        }
      </div>

      <div class="field">
        <app-select
          id="budget-gremium"
          name="gremium"
          [label]="'budget.filter.gremium' | t"
          [placeholder]="'budget.filter.all' | t"
          [options]="gremiumOptions()"
          [ngModel]="gremium()"
          (ngModelChange)="gremium.set($event)"
        />
      </div>

      <div class="field">
        <label class="field__label" for="budget-period">{{ 'budget.filter.period' | t }}</label>
        <input
          id="budget-period"
          class="field__control"
          type="text"
          name="period"
          [placeholder]="'budget.filter.period.placeholder' | t"
          [ngModel]="period()"
          (ngModelChange)="period.set($event)"
        />
      </div>

      <div class="budget__filterActions">
        <app-button type="submit" size="sm">{{ 'budget.filter.apply' | t }}</app-button>
        <app-button type="button" variant="ghost" size="sm" (click)="reset()">
          {{ 'budget.filter.reset' | t }}
        </app-button>
      </div>
    </form>

    @if (loading()) {
      <p class="budget__status" aria-live="polite">{{ 'budget.loading' | t }}</p>
    } @else if (error()) {
      <p class="budget__status budget__status--error" role="alert">{{ 'budget.error' | t }}</p>
    } @else if (isEmpty()) {
      <section class="budget__empty">
        <h2 class="budget__emptyTitle">{{ 'budget.empty.title' | t }}</h2>
        <p>{{ 'budget.empty.body' | t }}</p>
      </section>
    } @else {
      <section class="budget__kpis" [attr.aria-label]="'budget.title' | t">
        <div class="kpi">
          <span class="kpi__label">{{ 'budget.kpi.pots' | t }}</span>
          <span class="kpi__value">{{ kpis().potCount }}</span>
        </div>
        <div class="kpi">
          <span class="kpi__label">{{ 'budget.kpi.total' | t }}</span>
          <span class="kpi__value">{{ money(kpis().total) }}</span>
        </div>
        <div class="kpi">
          <span class="kpi__label">{{ 'budget.kpi.requested' | t }}</span>
          <span class="kpi__value">{{ money(kpis().requested) }}</span>
        </div>
        <div class="kpi">
          <span class="kpi__label">{{ 'budget.kpi.committed' | t }}</span>
          <span class="kpi__value">{{ money(kpis().committed) }}</span>
        </div>
        <div class="kpi">
          <span class="kpi__label">{{ 'budget.kpi.available' | t }}</span>
          <span class="kpi__value">{{ money(kpis().available) }}</span>
        </div>
        <div class="kpi">
          <span class="kpi__label">{{ 'budget.kpi.applications' | t }}</span>
          <span class="kpi__value">{{ kpis().applicationCount }}</span>
        </div>
      </section>

      @if (kpis().mixedCurrency) {
        <p class="budget__note" role="note">{{ 'budget.mixedCurrency' | t }}</p>
      }

      <div class="budget__panels">
        <app-pot-usage class="budget__panel" [pots]="stats()!.pots" />
        <app-status-distribution class="budget__panel" [buckets]="stats()!.statusDistribution" />
      </div>
    }
  `,
  styles: [
    `
      .budget__head {
        margin-bottom: var(--space-5);
      }
      .budget__title {
        margin: 0;
      }
      .budget__subtitle {
        color: var(--color-text-muted);
        margin: var(--space-1) 0 0;
      }
      .budget__filters {
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
      .budget__filtersLegend {
        flex-basis: 100%;
        margin: 0;
        font-size: var(--fs-sm);
        font-weight: var(--fw-semibold);
        color: var(--color-text-muted);
        text-transform: uppercase;
        letter-spacing: 0.04em;
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
      .budget__filterActions {
        display: flex;
        gap: var(--space-2);
      }
      .budget__status {
        color: var(--color-text-muted);
        padding: var(--space-5) 0;
      }
      .budget__status--error {
        color: var(--color-danger);
      }
      .budget__empty {
        padding: var(--space-6);
        background: var(--color-surface);
        border: var(--border-width) dashed var(--color-border-strong);
        border-radius: var(--radius-md);
        text-align: center;
        color: var(--color-text-muted);
      }
      .budget__emptyTitle {
        margin: 0 0 var(--space-2);
        color: var(--color-text);
      }
      .budget__kpis {
        display: grid;
        /* Feste, gleich breite Spalten statt content-getriebener auto-fit-Tracks
           (#106): 2 → 3 → 6 Spalten, immer volle Reihen, alle KPIs gleich breit. */
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: var(--space-4);
        margin-bottom: var(--space-5);
      }
      @media (min-width: 40rem) {
        .budget__kpis {
          grid-template-columns: repeat(3, minmax(0, 1fr));
        }
      }
      @media (min-width: 64rem) {
        .budget__kpis {
          grid-template-columns: repeat(6, minmax(0, 1fr));
        }
      }
      .kpi {
        display: flex;
        flex-direction: column;
        gap: var(--space-1);
        padding: var(--space-4);
        background: var(--color-surface);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-md);
      }
      .kpi__label {
        font-size: var(--fs-sm);
        color: var(--color-text-muted);
      }
      .kpi__value {
        font-size: var(--fs-xl);
        font-weight: var(--fw-bold);
        font-variant-numeric: tabular-nums;
      }
      .budget__note {
        margin: 0 0 var(--space-5);
        color: var(--color-text-muted);
        font-size: var(--fs-sm);
      }
      .budget__panels {
        display: grid;
        grid-template-columns: 1fr;
        gap: var(--space-6);
      }
      .budget__panel {
        display: block;
        padding: var(--space-5);
        background: var(--color-surface);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-md);
      }
      @media (min-width: 60rem) {
        .budget__panels {
          grid-template-columns: 3fr 2fr;
        }
      }
    `,
  ],
})
export class BudgetDashboardComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly options = inject(AdminOptionsService);

  readonly loading = signal(true);
  readonly error = signal(false);
  readonly stats = signal<BudgetStats | null>(null);
  readonly pots = signal<BudgetPotInfo[]>([]);
  /** Gremien als Dropdown-Optionen (#77) statt Freitext-ID. */
  readonly gremiumOptions = signal<SelectOption[]>([]);
  /** Töpfe als Dropdown-Optionen (#106 — custom app-select statt nativem select). */
  readonly potOptions = computed<SelectOption[]>(() =>
    this.pots().map((p) => ({ value: p.id, label: p.name })),
  );

  /** Sichtbare Filter-Controls (gespiegelt aus den Query-Params). */
  readonly pot = signal('');
  readonly gremium = signal('');
  readonly period = signal('');

  readonly kpis = computed<BudgetKpis>(() =>
    kpiTotals(this.stats() ?? { pots: [], statusDistribution: [] }),
  );

  readonly isEmpty = computed(() => {
    const s = this.stats();
    return !!s && s.pots.length === 0 && s.statusDistribution.length === 0;
  });

  constructor() {
    this.options
      .gremiumOptions()
      .pipe(takeUntilDestroyed())
      .subscribe((opts) => this.gremiumOptions.set(opts));
    this.route.queryParamMap.pipe(takeUntilDestroyed()).subscribe((pm) => {
      this.pot.set(pm.get('pot') ?? '');
      this.gremium.set(pm.get('gremium') ?? '');
      this.period.set(pm.get('period') ?? '');
      this.load(pm);
    });
  }

  money(value: number | null): string {
    return formatMoney(value, this.kpis().currency, this.i18n.locale());
  }

  applyFilters(event: Event): void {
    event.preventDefault();
    this.navigate({
      pot: this.pot() || null,
      gremium: this.gremium() || null,
      period: this.period() || null,
    });
  }

  reset(): void {
    this.pot.set('');
    this.gremium.set('');
    this.period.set('');
    this.navigate({ pot: null, gremium: null, period: null });
  }

  private navigate(queryParams: Record<string, string | null>): void {
    this.router.navigate([], {
      relativeTo: this.route,
      queryParams,
      queryParamsHandling: 'merge',
    });
  }

  private load(pm: ParamMap): void {
    const gremium = pm.get('gremium') || undefined;
    const period = pm.get('period') || undefined;
    const pot = pm.get('pot') || undefined;

    this.loading.set(true);
    this.error.set(false);

    // Töpfe best-effort (nur P(budget.manage)) → Namensauflösung + Filter-Optionen.
    this.api
      .budgetPots({ gremium, period })
      .pipe(
        catchError(() => of([] as BudgetPotInfo[])),
        switchMap((pots) => {
          this.pots.set(pots);
          const names = new Map(pots.map((p) => [p.id, p.name]));
          return this.api.budgetStats({ pot, gremium, period }, names);
        }),
      )
      .subscribe({
        next: (stats) => {
          this.stats.set(stats);
          this.loading.set(false);
        },
        error: () => {
          this.error.set(true);
          this.loading.set(false);
        },
      });
  }
}
