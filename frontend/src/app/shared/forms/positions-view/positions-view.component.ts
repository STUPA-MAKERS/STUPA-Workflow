import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { IconComponent } from '@stupa-makers/ui-kit';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { StatusTextComponent } from '@shared/ui/status-text/status-text.component';
import { formatEuro } from '../answer-format';
import {
  normalizePositions,
  positionValue,
  positionsTotal,
  preferredOffer,
  type CostPosition,
} from '../positions';

/** One position as the view draws it. */
interface PositionRow extends CostPosition {
  amount: string;
  /** "3 Angebote" or "1 Angebot". */
  count: string;
  /** The supplier of the preferred offer, or '' when none is preferred. */
  preferred: string;
}

let nextId = 0;

/**
 * "Kostenaufstellung": the cost positions of an answer, read-only (O19, the boards Anträge
 * and Schmal-Anträge-Detail).
 *
 * A position shows collapsed: its name, "n Angebote · bevorzugt: <supplier>" and its
 * amount. The whole row is the button that opens it. Open, it lists every offer; the
 * preferred one is marked "bevorzugt" and its value is the amount of the position. A
 * position without comparison offers shows "ohne Vergleichsangebote" and the reason
 * instead. The last row gives the total.
 *
 * Comparison offers stay tagged attachments (O5): the offers here have no file.
 */
@Component({
  selector: 'app-positions-view',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent, StatusTextComponent, TranslatePipe],
  templateUrl: './positions-view.component.html',
  styleUrl: './positions-view.component.scss',
})
export class PositionsViewComponent {
  private readonly i18n = inject(I18nService);

  /** The label of the field, for example "Kostenaufstellung". */
  readonly label = input.required<string>();
  /** The stored answer: a list of positions. */
  readonly value = input.required<unknown>();
  /** The surface of the rows; see `app-field-group`. */
  readonly surface = input<1 | 2 | 3>(2);
  /** Open every position at the start, for example in the review step of the wizard. */
  readonly expanded = input(false);

  protected readonly id = `pv-${nextId++}`;

  /** The positions the reader opened or closed against the start state. */
  private readonly toggled = signal<ReadonlySet<number>>(new Set());

  protected readonly rows = computed<PositionRow[]>(() => {
    // The texts follow a language switch: `translate` and `money` read the locale signal.
    return normalizePositions(this.value()).map((p) => ({
      ...p,
      amount: this.money(positionValue(p)),
      count: this.i18n.translate(
        p.offers.length === 1 ? 'forms.positions.offerOne' : 'forms.positions.offerOther',
        { count: p.offers.length },
      ),
      preferred: preferredOffer(p)?.label.trim() ?? '',
    }));
  });

  protected readonly total = computed(() => this.money(positionsTotal(this.rows())));

  protected isOpen(index: number): boolean {
    return this.expanded() !== this.toggled().has(index);
  }

  protected toggle(index: number): void {
    this.toggled.update((cur) => {
      const next = new Set(cur);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  }

  /** An amount in euro; a missing value counts as 0, as on the server. */
  protected money(value: number | null): string {
    return formatEuro(Number(value), this.i18n.locale()) as string;
  }
}
