import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { PotUsage } from '@core/api/models';
import { type PotUsageBar, formatMoney, potUsageBar, usagePercent } from './budget.util';

interface PotRow {
  pot: PotUsage;
  bar: PotUsageBar;
  /** committed/total in Prozent (`null` bei unlimitiertem Topf). */
  percent: number | null;
}

/**
 * Präsentations-Komponente: Auslastung je Budget-Topf als gestapelte Leiste
 * (paid/approved/reserved = `committed`) plus freier Rest. Das `requested`
 * (Pipeline) wird separat als Kennzahl gezeigt — es kann das Limit übersteigen.
 *
 * a11y: die Leiste ist `role="img"` mit sprechendem `aria-label`; zusätzlich
 * trägt **jede** Topf-Zeile die Zahlen sichtbar, und eine Tabelle (für
 * Screenreader/„Diagramm-Alternativtext") fasst alle Stufen zusammen. Farben
 * kommen ausschließlich aus Tokens (Light/Dark), Bedeutung nie nur über Farbe.
 */
@Component({
  selector: 'app-pot-usage',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe],
  template: `
    <section class="usage" [attr.aria-label]="'budget.usage.heading' | t">
      <header class="usage__head">
        <h2 class="usage__title">{{ 'budget.usage.heading' | t }}</h2>
        <p class="usage__subtitle">{{ 'budget.usage.subtitle' | t }}</p>
      </header>

      @if (rows().length === 0) {
        <p class="usage__empty">{{ 'budget.usage.empty' | t }}</p>
      } @else {
        <ul class="usage__list">
          @for (row of rows(); track row.pot.budgetPotId) {
            <li class="usage__row">
              <div class="usage__rowHead">
                <span class="usage__pot">
                  {{ row.pot.name }}
                  @if (row.pot.period) {
                    <span class="usage__period">· {{ row.pot.period }}</span>
                  }
                </span>
                <span class="usage__ratio">
                  @if (row.percent !== null) {
                    {{ row.percent }}%
                  } @else {
                    {{ 'budget.usage.unlimited' | t }}
                  }
                  @if (row.bar.overcommitted) {
                    <span class="usage__warn" role="status">{{ 'budget.usage.overcommitted' | t }}</span>
                  }
                </span>
              </div>

              <div
                class="usage__track"
                role="img"
                [attr.aria-label]="barLabel(row)"
                [class.usage__track--over]="row.bar.overcommitted"
              >
                @for (seg of row.bar.segments; track seg.stage) {
                  @if (seg.amount > 0) {
                    <span
                      class="usage__seg"
                      [class]="'usage__seg--' + seg.stage"
                      [style.width.%]="seg.pct"
                    ></span>
                  }
                }
              </div>

              <dl class="usage__figures">
                <div class="usage__fig">
                  <dt>{{ 'budget.stage.requested' | t }}</dt>
                  <dd>{{ money(row.pot.requested, row.pot.currency) }}</dd>
                </div>
                <div class="usage__fig">
                  <dt>{{ 'budget.stage.committed' | t }}</dt>
                  <dd>{{ money(row.pot.committed, row.pot.currency) }}</dd>
                </div>
                <div class="usage__fig">
                  <dt>{{ 'budget.stage.available' | t }}</dt>
                  <dd>{{ row.pot.available !== null ? money(row.pot.available, row.pot.currency) : ('budget.usage.unlimited' | t) }}</dd>
                </div>
                <div class="usage__fig">
                  <dt>{{ 'budget.usage.col.total' | t }}</dt>
                  <dd>{{ row.pot.total !== null ? money(row.pot.total, row.pot.currency) : ('budget.usage.unlimited' | t) }}</dd>
                </div>
              </dl>
            </li>
          }
        </ul>

        <!-- Diagramm-Alternativtext: vollständige Tabelle (a11y, AK T-35). -->
        <table class="usage__table">
          <caption>{{ 'budget.usage.table.caption' | t }}</caption>
          <thead>
            <tr>
              <th scope="col">{{ 'budget.usage.col.pot' | t }}</th>
              <th scope="col" class="usage__num">{{ 'budget.stage.requested' | t }}</th>
              <th scope="col" class="usage__num">{{ 'budget.stage.reserved' | t }}</th>
              <th scope="col" class="usage__num">{{ 'budget.stage.approved' | t }}</th>
              <th scope="col" class="usage__num">{{ 'budget.stage.paid' | t }}</th>
              <th scope="col" class="usage__num">{{ 'budget.stage.committed' | t }}</th>
              <th scope="col" class="usage__num">{{ 'budget.usage.col.total' | t }}</th>
            </tr>
          </thead>
          <tbody>
            @for (row of rows(); track row.pot.budgetPotId) {
              <tr>
                <th scope="row">{{ row.pot.name }}</th>
                <td class="usage__num">{{ money(row.pot.requested, row.pot.currency) }}</td>
                <td class="usage__num">{{ money(row.pot.reserved, row.pot.currency) }}</td>
                <td class="usage__num">{{ money(row.pot.approved, row.pot.currency) }}</td>
                <td class="usage__num">{{ money(row.pot.paid, row.pot.currency) }}</td>
                <td class="usage__num">{{ money(row.pot.committed, row.pot.currency) }}</td>
                <td class="usage__num">
                  {{ row.pot.total !== null ? money(row.pot.total, row.pot.currency) : ('budget.usage.unlimited' | t) }}
                </td>
              </tr>
            }
          </tbody>
        </table>
      }
    </section>
  `,
  styles: [
    `
      .usage__head {
        margin-bottom: var(--space-4);
      }
      .usage__title {
        font-size: var(--fs-xl);
        margin: 0;
      }
      .usage__subtitle {
        color: var(--color-text-muted);
        margin: var(--space-1) 0 0;
      }
      .usage__empty {
        color: var(--color-text-muted);
        padding: var(--space-5) 0;
      }
      .usage__list {
        list-style: none;
        margin: 0;
        padding: 0;
        display: flex;
        flex-direction: column;
        gap: var(--space-5);
      }
      .usage__row {
        display: flex;
        flex-direction: column;
        gap: var(--space-2);
      }
      .usage__rowHead {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: var(--space-3);
        flex-wrap: wrap;
      }
      .usage__pot {
        font-weight: var(--fw-semibold);
      }
      .usage__period {
        color: var(--color-text-muted);
        font-weight: var(--fw-normal);
        font-size: var(--fs-sm);
      }
      .usage__ratio {
        font-variant-numeric: tabular-nums;
        font-weight: var(--fw-bold);
        display: inline-flex;
        align-items: center;
        gap: var(--space-2);
      }
      .usage__warn {
        font-size: var(--fs-xs);
        font-weight: var(--fw-semibold);
        color: var(--color-danger);
        border: var(--border-width) solid var(--color-danger);
        border-radius: var(--radius-pill);
        padding: 0 var(--space-2);
      }
      .usage__track {
        display: flex;
        height: 1rem;
        background: var(--color-surface-sunken);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-pill);
        overflow: hidden;
      }
      .usage__track--over {
        border-color: var(--color-danger);
      }
      .usage__seg {
        height: 100%;
        transition: width var(--motion-base) var(--ease-standard);
      }
      /* Drei Sättigungsstufen des Grün-Akzents — Bedeutung steht auch in Text/Tabelle. */
      .usage__seg--paid {
        background: var(--color-primary);
      }
      .usage__seg--approved {
        background: var(--color-success);
      }
      .usage__seg--reserved {
        background: color-mix(in srgb, var(--color-success) 45%, var(--color-surface));
      }
      .usage__figures {
        display: flex;
        flex-wrap: wrap;
        gap: var(--space-2) var(--space-5);
        margin: 0;
      }
      .usage__fig {
        display: flex;
        gap: var(--space-2);
        align-items: baseline;
      }
      .usage__fig dt {
        color: var(--color-text-muted);
        font-size: var(--fs-sm);
        margin: 0;
      }
      .usage__fig dd {
        margin: 0;
        font-variant-numeric: tabular-nums;
        font-weight: var(--fw-medium);
      }
      .usage__table {
        width: 100%;
        border-collapse: collapse;
        margin-top: var(--space-5);
        font-size: var(--fs-sm);
      }
      .usage__table caption {
        text-align: start;
        color: var(--color-text-muted);
        padding-bottom: var(--space-3);
      }
      .usage__table th,
      .usage__table td {
        padding: var(--space-2) var(--space-3);
        border-bottom: var(--border-width) solid var(--color-border);
        text-align: start;
      }
      .usage__table thead th {
        color: var(--color-text-muted);
        font-size: var(--fs-xs);
        text-transform: uppercase;
        letter-spacing: 0.04em;
      }
      .usage__num {
        text-align: end;
        font-variant-numeric: tabular-nums;
      }
      @media (prefers-reduced-motion: reduce) {
        .usage__seg {
          transition: none;
        }
      }
    `,
  ],
})
export class PotUsageComponent {
  private readonly i18n = inject(I18nService);

  readonly pots = input.required<PotUsage[]>();

  readonly rows = computed<PotRow[]>(() =>
    this.pots().map((pot) => ({ pot, bar: potUsageBar(pot), percent: usagePercent(pot) })),
  );

  money(value: number | null, currency: string): string {
    return formatMoney(value, currency, this.i18n.locale());
  }

  /** Sprechendes Diagramm-Label: „Topf A: 30 % gebunden, 700 € frei". */
  barLabel(row: PotRow): string {
    const committed = this.money(row.pot.committed, row.pot.currency);
    const available =
      row.pot.available !== null
        ? this.money(row.pot.available, row.pot.currency)
        : this.i18n.translate('budget.usage.unlimited');
    return this.i18n.translate('budget.usage.bar.label', {
      name: row.pot.name,
      committed,
      available,
    });
  }
}
