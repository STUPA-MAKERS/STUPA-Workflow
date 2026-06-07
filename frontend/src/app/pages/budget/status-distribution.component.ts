import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { StatusBucket, Uuid } from '@core/api/models';

interface StateRow {
  stateId: Uuid | null;
  label: string;
  count: number;
  /** Breite relativ zur größten Stufe (0–100). */
  pct: number;
}

/**
 * Präsentations-Komponente: Verteilung der Anträge über Status (data-model §3
 * `mv_status_distribution`). Das Backend liefert Zellen Gremium × State ohne
 * Klartext-Labels — bis es einen Label-Endpunkt gibt, werden IDs gekürzt
 * angezeigt; die Aggregation summiert je State über alle Gremien.
 *
 * a11y: Balken sind `role="img"` mit Label; die vollständige Kreuztabelle
 * (Gremium × State) dient als Diagramm-Alternativtext.
 */
@Component({
  selector: 'app-status-distribution',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe],
  template: `
    <section class="status" [attr.aria-label]="'budget.status.heading' | t">
      <header class="status__head">
        <h2 class="status__title">{{ 'budget.status.heading' | t }}</h2>
        <p class="status__subtitle">{{ 'budget.status.subtitle' | t }}</p>
      </header>

      @if (total() === 0) {
        <p class="status__empty">{{ 'budget.status.empty' | t }}</p>
      } @else {
        <ul class="status__bars">
          @for (row of stateRows(); track row.stateId) {
            <li class="status__bar">
              <div class="status__barHead">
                <span class="status__label">{{ row.label }}</span>
                <span class="status__count">{{ row.count }}</span>
              </div>
              <div
                class="status__track"
                role="img"
                [attr.aria-label]="row.label + ': ' + row.count"
              >
                <span class="status__fill" [style.width.%]="row.pct"></span>
              </div>
            </li>
          }
        </ul>

        <!-- Diagramm-Alternativtext: Kreuztabelle Gremium × State (a11y). -->
        <table class="status__table">
          <caption>{{ 'budget.status.table.caption' | t }}</caption>
          <thead>
            <tr>
              <th scope="col">{{ 'budget.status.col.gremium' | t }}</th>
              <th scope="col">{{ 'budget.status.col.state' | t }}</th>
              <th scope="col" class="status__num">{{ 'budget.status.col.count' | t }}</th>
            </tr>
          </thead>
          <tbody>
            @for (bucket of buckets(); track $index) {
              <tr>
                <th scope="row">{{ gremiumLabel(bucket.gremiumId) }}</th>
                <td>{{ stateLabel(bucket.stateId) }}</td>
                <td class="status__num">{{ bucket.count }}</td>
              </tr>
            }
          </tbody>
          <tfoot>
            <tr>
              <th scope="row" colspan="2">{{ 'budget.status.col.total' | t }}</th>
              <td class="status__num">{{ total() }}</td>
            </tr>
          </tfoot>
        </table>
      }
    </section>
  `,
  styles: [
    `
      .status__head {
        margin-bottom: var(--space-4);
      }
      .status__title {
        font-size: var(--fs-xl);
        margin: 0;
      }
      .status__subtitle {
        color: var(--color-text-muted);
        margin: var(--space-1) 0 0;
      }
      .status__empty {
        color: var(--color-text-muted);
        padding: var(--space-5) 0;
      }
      .status__bars {
        list-style: none;
        margin: 0 0 var(--space-5);
        padding: 0;
        display: flex;
        flex-direction: column;
        gap: var(--space-3);
      }
      .status__barHead {
        display: flex;
        justify-content: space-between;
        gap: var(--space-3);
        margin-bottom: var(--space-1);
      }
      .status__label {
        font-weight: var(--fw-medium);
      }
      .status__count {
        font-variant-numeric: tabular-nums;
        font-weight: var(--fw-bold);
      }
      .status__track {
        height: 0.85rem;
        background: var(--color-surface-sunken);
        border: var(--border-width) solid var(--color-border);
        border-radius: var(--radius-pill);
        overflow: hidden;
      }
      .status__fill {
        display: block;
        height: 100%;
        background: var(--color-primary);
        transition: width var(--motion-base) var(--ease-standard);
      }
      .status__table {
        width: 100%;
        border-collapse: collapse;
        font-size: var(--fs-sm);
      }
      .status__table caption {
        text-align: start;
        color: var(--color-text-muted);
        padding-bottom: var(--space-3);
      }
      .status__table th,
      .status__table td {
        padding: var(--space-2) var(--space-3);
        border-bottom: var(--border-width) solid var(--color-border);
        text-align: start;
      }
      .status__table thead th {
        color: var(--color-text-muted);
        font-size: var(--fs-xs);
        text-transform: uppercase;
        letter-spacing: 0.04em;
      }
      .status__num {
        text-align: end;
        font-variant-numeric: tabular-nums;
      }
      .status__table tfoot th,
      .status__table tfoot td {
        font-weight: var(--fw-bold);
        border-bottom: none;
      }
      @media (prefers-reduced-motion: reduce) {
        .status__fill {
          transition: none;
        }
      }
    `,
  ],
})
export class StatusDistributionComponent {
  private readonly i18n = inject(I18nService);

  readonly buckets = input.required<StatusBucket[]>();

  readonly total = computed(() => this.buckets().reduce((s, b) => s + b.count, 0));

  /** Je State über alle Gremien summieren → Balken, nach Anzahl absteigend. */
  readonly stateRows = computed<StateRow[]>(() => {
    const byState = new Map<Uuid | null, number>();
    for (const b of this.buckets()) {
      byState.set(b.stateId, (byState.get(b.stateId) ?? 0) + b.count);
    }
    const max = Math.max(1, ...byState.values());
    return [...byState.entries()]
      .map(([stateId, count]) => ({
        stateId,
        label: this.stateLabel(stateId),
        count,
        pct: Math.round((count / max) * 100),
      }))
      .sort((a, b) => b.count - a.count);
  });

  stateLabel(id: Uuid | null): string {
    return id ? shortId(id) : this.i18n.translate('budget.status.unknownState');
  }

  gremiumLabel(id: Uuid | null): string {
    return id ? shortId(id) : this.i18n.translate('budget.status.unknownGremium');
  }
}

function shortId(id: Uuid): string {
  return id.length > 8 ? `${id.slice(0, 8)}…` : id;
}
