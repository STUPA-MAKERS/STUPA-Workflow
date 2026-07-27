import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TransitionLists } from './flow-editor.models';

/** Incoming and outgoing transitions of the selected state. A row click selects one. */
@Component({
  selector: 'app-transition-lists',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe],
  templateUrl: './transition-lists.component.html',
  styleUrl: './transition-lists.component.scss',
})
export class TransitionListsComponent {
  readonly lists = input.required<TransitionLists>();

  readonly selectTransition = output<number>();
}
