import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import {
  IconComponent,
  StatusTextComponent,
} from '@stupa-makers/ui-kit';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { formatMoney } from '../../format-money';
import { toggled } from '../../util/immutable';
import {
  normalizePositions,
  offerHref,
  positionValue,
  positionsTotal,
  preferredOffer,
  type CostPosition,
  type PositionOffer,
} from '../positions';
import type { CostLine } from '../form-rules';

/** A file of a position as the view lists it. */
export interface PositionFile {
  readonly id: string;
  readonly filename: string;
  readonly positionId?: string | null;
}

/** One offer as the view draws it. */
interface OfferRow extends PositionOffer {
  /** The link of an offer whose text is an http(s) URL, else null. */
  readonly href: string | null;
}

/** One position as the view draws it. */
interface PositionRow extends CostPosition {
  readonly offers: readonly OfferRow[];
  readonly amount: string;
  /** "3 Angebote" or "1 Angebot". */
  readonly count: string;
  /** The supplier of the preferred offer, or '' when none is preferred. */
  readonly preferred: string;
  /** The files of the position (spec 001730). */
  readonly files: readonly PositionFile[];
}

let nextId = 0;

/**
 * "Kostenaufstellung": the cost positions of an answer, read-only.
 *
 * A position shows collapsed: its name, "n Angebote · bevorzugt: <supplier>" and its
 * amount. The whole row is the button that opens it. Open, it lists every offer; the
 * preferred one is marked "bevorzugt" and its value is the amount of the position. A
 * position without comparison offers shows "ohne Vergleichsangebote" and the reason
 * instead. The last row gives the total.
 *
 * Names, suppliers and offer texts are never cut: they wrap. An offer text that is an
 * http(s) URL is a link in the open position (a link cannot sit in the row button).
 *
 * The files of a position (spec 001730) are listed in the open position by name; the
 * block "Anhänge" opens them. Below the total, `costLine` gives the line "Gesamtkosten X
 * €, davon beantragt Y €" with the amount per person, as the form showed it (spec 001632).
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
  /** The figures of the cost line, or null when this field does not show it. */
  readonly costLine = input<CostLine | null>(null);
  /** The files of the application; the view lists those of each position. */
  readonly files = input<readonly PositionFile[]>([]);

  protected readonly id = `pv-${nextId++}`;

  /** The positions the reader opened or closed against the start state. */
  private readonly toggled = signal<ReadonlySet<number>>(new Set());

  /** The texts follow a language switch, because `translate` and `money` read the locale signal. */
  protected readonly rows = computed<PositionRow[]>(() => {
    return normalizePositions(this.value()).map((p) => ({
      ...p,
      offers: p.offers.map((o) => ({ ...o, href: offerHref(o.label) })),
      amount: this.money(positionValue(p)),
      count: this.i18n.translate(
        p.offers.length === 1 ? 'forms.positions.offerOne' : 'forms.positions.offerOther',
        { count: p.offers.length },
      ),
      preferred: preferredOffer(p)?.label.trim() ?? '',
      files: p.id ? this.files().filter((f) => f.positionId === p.id) : [],
    }));
  });

  /** "Gesamtkosten 1.200,00 €, davon beantragt 800,00 €, 40,00 € pro Person", or ''. */
  protected readonly lineText = computed(() => {
    const line = this.costLine();
    if (!line) return '';
    const head = this.i18n.translate('forms.costLine.total', {
      total: this.money(line.total),
      requested: this.money(line.requested),
    });
    return line.perPerson === null
      ? head
      : `${head}, ${this.i18n.translate('forms.costLine.perPerson', { amount: this.money(line.perPerson) })}`;
  });

  protected readonly total = computed(() => this.money(positionsTotal(this.rows())));

  protected isOpen(index: number): boolean {
    return this.expanded() !== this.toggled().has(index);
  }

  protected toggle(index: number): void {
    this.toggled.update((cur) => toggled(cur, index));
  }

  /** An amount in euro; a missing value counts as 0, as on the server. */
  protected money(value: number | null): string {
    return formatMoney(value ?? 0, this.i18n.formatLocale());
  }
}
