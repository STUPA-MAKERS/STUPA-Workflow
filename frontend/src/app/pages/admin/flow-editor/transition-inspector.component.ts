import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  ButtonComponent,
  CheckboxComponent,
  SelectComponent,
  type SelectOption,
} from '@stupa-makers/ui-kit';
import type { TransitionDef } from '../admin.models';

/** Inspector panel for the selected transition. It edits endpoints, labels and flags. */
@Component({
  selector: 'app-transition-inspector',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslatePipe, ButtonComponent, CheckboxComponent, SelectComponent],
  templateUrl: './transition-inspector.component.html',
  styleUrl: './transition-inspector.component.scss',
})
export class TransitionInspectorComponent {
  readonly transition = input.required<TransitionDef>();
  readonly stateOptions = input.required<SelectOption[]>();
  /** Result branches of the source state. An empty list hides the branch select. */
  readonly branchOptions = input.required<SelectOption[]>();

  readonly fromChange = output<string>();
  readonly toChange = output<string>();
  readonly labelChange = output<{ lang: 'de' | 'en'; value: string }>();
  readonly colorChange = output<string>();
  readonly automaticChange = output<boolean>();
  readonly requiresActionChange = output<boolean>();
  readonly branchChange = output<string>();
  readonly remove = output<void>();
}
