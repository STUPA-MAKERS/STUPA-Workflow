import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { ButtonComponent } from '@stupa-makers/ui-kit';
import type { FlowGroup } from '../admin.models';

/** Inspector panel for the group that is currently open (drilled into). */
@Component({
  selector: 'app-group-inspector',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslatePipe, ButtonComponent],
  templateUrl: './group-inspector.component.html',
  styleUrl: './group-inspector.component.scss',
})
export class GroupInspectorComponent {
  readonly group = input.required<FlowGroup>();

  readonly nameChange = output<string>();
  readonly colorChange = output<string>();
  readonly dissolve = output<void>();
}
