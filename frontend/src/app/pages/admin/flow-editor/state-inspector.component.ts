import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  ButtonComponent,
  CheckboxComponent,
  SelectComponent,
  type SelectOption,
} from '@stupa-makers/ui-kit';
import type { StateDef } from '../admin.models';

/** Row of the guard priority stack (label precomputed by the parent). */
export interface GuardPriorityRow {
  sig: string;
  label: string;
}

/** Inspector panel for the selected state: key/labels/flags/kind/config. */
@Component({
  selector: 'app-state-inspector',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslatePipe, ButtonComponent, CheckboxComponent, SelectComponent],
  templateUrl: './state-inspector.component.html',
  styleUrl: './state-inspector.component.scss',
})
export class StateInspectorComponent {
  readonly state = input.required<StateDef>();
  readonly kindOptions = input.required<SelectOption[]>();
  readonly gremiumOptions = input.required<SelectOption[]>();
  readonly deadlinePolicyOptions = input.required<SelectOption[]>();
  /** Guard priority rows; the stack is shown for normal states with ≥2 groups. */
  readonly guardGroups = input.required<GuardPriorityRow[]>();

  readonly keyChange = output<string>();
  readonly labelChange = output<{ lang: 'de' | 'en'; value: string }>();
  readonly colorChange = output<string>();
  readonly makeInitial = output<void>();
  readonly editAllowedChange = output<boolean>();
  readonly terminalChange = output<boolean>();
  readonly kindChange = output<string>();
  readonly gremiumChange = output<string>();
  readonly deadlinePolicyChange = output<string>();
  readonly guardMove = output<{ sig: string; dir: -1 | 1 }>();
  readonly remove = output<void>();
}
