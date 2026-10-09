import { ChangeDetectionStrategy, Component, computed, inject, input, model } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import {
  ButtonComponent,
  CurrencyInputComponent,
  IconComponent,
  SwitchComponent,
} from '@stupa-makers/ui-kit';
import {
  MAX_CONDITIONS,
  MAX_CONDITION_LENGTH,
  type DecisionDraft,
  draftError,
  formatDiff,
  formatMoney,
} from './decision.util';

/**
 * The decision proposal (F1, approval with deviations): a switch, and when it is on the
 * approved amount ("Förderbetrag") and the list of conditions ("Auflagen").
 *
 * The vote-open dialog and the decision dialog of a transition use it. The parent owns
 * the draft (`[(draft)]`) and sends it with `toProposal`.
 */
@Component({
  selector: 'app-decision-editor',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslatePipe, ButtonComponent, CurrencyInputComponent, IconComponent, SwitchComponent],
  templateUrl: './decision-editor.component.html',
  styleUrl: './decision-editor.component.scss',
})
export class DecisionEditorComponent {
  private readonly i18n = inject(I18nService);

  readonly draft = model.required<DecisionDraft>();
  /** The requested amount of the application (decimal string), for the hint and the check. */
  readonly requested = input<string | null>(null);
  readonly currency = input<string | null>('EUR');
  /** The hint under the switch. A vote says the proposal applies only when it passes. */
  readonly switchHint = input<TranslationKey>('decision.switchHintVote');
  /** A unique prefix for the ids of the controls. */
  readonly idPrefix = input('dec');

  readonly maxLength = MAX_CONDITION_LENGTH;
  readonly canAdd = computed(() => this.draft().conditions.length < MAX_CONDITIONS);
  readonly error = computed(() => draftError(this.draft(), this.requested()));

  /** "Beantragt: 1.250,00 € · Abweichung −350,00 €". */
  readonly amountHint = computed(() => {
    const locale = this.i18n.formatLocale();
    const requested = formatMoney(this.requested(), locale, this.currency());
    if (!requested) return '';
    const diff = formatDiff(this.requested(), this.draft().amount, locale, this.currency());
    return diff
      ? this.i18n.translate('decision.amountHintDiff', { requested, diff })
      : this.i18n.translate('decision.amountHint', { requested });
  });

  /** The error of the amount field, else the hint. */
  readonly amountError = computed(() => {
    const err = this.error();
    return err === 'decision.error.amountInvalid' || err === 'decision.error.amountExceeds'
      ? this.i18n.translate(err)
      : '';
  });

  readonly listError = computed(() => {
    const err = this.error();
    return err === 'decision.error.conditionLength' || err === 'decision.error.conditionCount'
      ? this.i18n.translate(err, { max: MAX_CONDITION_LENGTH, count: MAX_CONDITIONS })
      : '';
  });

  private patch(change: Partial<DecisionDraft>): void {
    this.draft.set({ ...this.draft(), ...change });
  }

  setEnabled(enabled: boolean): void {
    this.patch({ enabled });
  }

  setAmount(amount: string): void {
    this.patch({ amount: amount ?? '' });
  }

  setCondition(index: number, text: string): void {
    const conditions = [...this.draft().conditions];
    conditions[index] = text;
    this.patch({ conditions });
  }

  addCondition(): void {
    if (!this.canAdd()) return;
    this.patch({ conditions: [...this.draft().conditions, ''] });
  }

  removeCondition(index: number): void {
    this.patch({ conditions: this.draft().conditions.filter((_, i) => i !== index) });
  }

  /** Move a condition one place up (`-1`) or down (`+1`). */
  moveCondition(index: number, step: -1 | 1): void {
    const target = index + step;
    const conditions = [...this.draft().conditions];
    if (target < 0 || target >= conditions.length) return;
    [conditions[index], conditions[target]] = [conditions[target], conditions[index]];
    this.patch({ conditions });
  }
}
