import { ChangeDetectionStrategy, Component, computed, input, model, output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ButtonComponent, InputComponent } from '@stupa-makers/ui-kit';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { PALETTE } from '../budget-color.util';

/** The colour of a Kostenstelle: `#rrggbb`, the format the server stores. */
const HEX_COLOUR = /^#[0-9a-f]{6}$/i;

/** A text is a colour the server takes: `#rrggbb`, or empty for no own colour. */
export function isColour(text: string): boolean {
  return text === '' || HEX_COLOUR.test(text);
}

/**
 * The colour of a Kostenstelle: the palette, a free colour and the hex value. `value` is
 * `#rrggbb` or '' for no own colour. `picked` fires with each valid colour a person
 * chooses, so a form that saves on leave can save it.
 */
@Component({
  selector: 'app-colour-field',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslatePipe, ButtonComponent, InputComponent],
  templateUrl: './colour-field.component.html',
  styleUrl: './colour-field.component.scss',
})
export class ColourFieldComponent {
  readonly value = model('');
  readonly disabled = input(false);
  /** The name of the hex field, unique in its form. */
  readonly name = input('colour');
  readonly picked = output<string>();

  readonly palette = PALETTE;
  readonly invalid = computed(() => !isColour(this.value()));

  pick(colour: string): void {
    this.value.set(colour.toLowerCase());
    this.picked.emit(this.value());
  }

  /** The hex field takes any text; only a valid colour leaves the field as a choice. */
  commit(): void {
    if (!this.invalid()) this.picked.emit(this.value());
  }
}
