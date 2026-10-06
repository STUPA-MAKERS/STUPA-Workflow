import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { EmptyStateComponent } from '@shared/ui/empty-state/empty-state.component';
import { VotingComponent } from './voting.component';

/**
 * The detail pane of `/voting` before a vote is open. Only the side-by-side layout shows
 * it; one pane at a time, the list fills the screen.
 *
 * Without votes it shows the empty state of the page ("Keine Abstimmungen"), else a hint
 * that no vote is open. While the list loads or after an error it shows only the empty
 * sheet: the list pane says what happens.
 */
@Component({
  selector: 'app-voting-none',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, EmptyStateComponent],
  templateUrl: './voting-none.component.html',
  styleUrl: './voting-none.component.scss',
})
export class VotingNoneComponent {
  private readonly page = inject(VotingComponent, { optional: true });

  protected readonly state = computed<'busy' | 'empty' | 'pick'>(() => {
    const page = this.page;
    if (!page || page.loading() || page.error()) return 'busy';
    return page.items().length || page.activeFilterCount() > 0 ? 'pick' : 'empty';
  });
}
