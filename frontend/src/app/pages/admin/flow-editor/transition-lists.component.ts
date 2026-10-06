import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { IconComponent } from '@stupa-makers/ui-kit';
import type { TransitionListRow, TransitionLists } from './flow-editor.models';

/**
 * Incoming and outgoing transitions of the selected state, under the state settings in
 * the inspector. A row click selects the transition.
 */
@Component({
  selector: 'app-transition-lists',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, IconComponent],
  templateUrl: './transition-lists.component.html',
  styleUrl: './transition-lists.component.scss',
})
export class TransitionListsComponent {
  readonly lists = input.required<TransitionLists>();

  readonly selectTransition = output<number>();

  /** The two lists with their headings, incoming first. */
  protected readonly columns = computed<
    { key: string; title: TranslationKey; rows: TransitionListRow[] }[]
  >(() => [
    { key: 'in', title: 'admin.flow.list.incoming', rows: this.lists().incoming },
    { key: 'out', title: 'admin.flow.list.outgoing', rows: this.lists().outgoing },
  ]);
}
