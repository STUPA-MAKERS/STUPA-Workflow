import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  ButtonComponent,
  IconComponent,
  InputComponent,
  SelectComponent,
  SwitchComponent,
  type SelectOption,
} from '@stupa-makers/ui-kit';
import type { StateDef } from '../admin.models';
import { FlowColorComponent } from './flow-color.component';

/** Row of the guard priority stack. The parent computes the label. */
export interface GuardPriorityRow {
  sig: string;
  label: string;
}

/**
 * Inspector panel for the selected state. It edits key, labels, colour, the flags
 * (start, editing allowed, terminal), the kind with its gremium, the deadline and the
 * guard priority of the exits.
 */
@Component({
  selector: 'app-state-inspector',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    ButtonComponent,
    IconComponent,
    InputComponent,
    SelectComponent,
    SwitchComponent,
    FlowColorComponent,
  ],
  templateUrl: './state-inspector.component.html',
  styleUrl: './state-inspector.component.scss',
})
export class StateInspectorComponent {
  private readonly i18n = inject(I18nService);

  readonly state = input.required<StateDef>();
  readonly kindOptions = input.required<SelectOption[]>();
  readonly gremiumOptions = input.required<SelectOption[]>();
  readonly deadlinePolicyOptions = input.required<SelectOption[]>();
  /** Guard priority rows. The stack appears for normal states with two or more groups. */
  readonly guardGroups = input.required<GuardPriorityRow[]>();

  readonly keyChange = output<string>();
  readonly labelChange = output<{ lang: 'de' | 'en'; value: string }>();
  readonly colorChange = output<string>();
  readonly makeInitial = output<void>();
  readonly editAllowedChange = output<boolean>();
  readonly terminalChange = output<boolean>();
  readonly kindChange = output<string>();
  readonly gremiumChange = output<string>();
  readonly gremiumSourceChange = output<'fixed' | 'budget'>();

  /** The gremium source of a vote state: `budget`, else a fixed gremium. */
  protected readonly gremiumSource = computed<'fixed' | 'budget'>(() =>
    this.state().config?.gremiumSource === 'budget' ? 'budget' : 'fixed',
  );

  protected gremiumSourceOptions(): SelectOption[] {
    return [
      { value: 'fixed', label: this.i18n.translate('admin.flow.cfgGremiumSourceFixed') },
      { value: 'budget', label: this.i18n.translate('admin.flow.cfgGremiumSourceBudget') },
    ];
  }
  readonly deadlinePolicyChange = output<string>();
  readonly guardMove = output<{ sig: string; dir: -1 | 1 }>();
  readonly remove = output<void>();
}
