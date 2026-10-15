import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { EmptyStateComponent } from '@shared/ui/empty-state/empty-state.component';
import { GremienStore } from '../gremien.store';

/**
 * The detail pane of `/gremien` before a gremium is open. Only the side-by-side layout
 * shows it, and only for a moment: the page opens the first gremium by itself. Without
 * a gremium it shows the empty state; while the list loads or after an error the empty
 * sheet only, because the list pane says what happens.
 */
@Component({
  selector: 'app-gremien-none',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, EmptyStateComponent],
  templateUrl: './gremien-none.component.html',
  styleUrl: './gremien-none.component.scss',
})
export class GremienNoneComponent {
  private readonly store = inject(GremienStore, { optional: true });

  protected readonly state = computed<'busy' | 'empty' | 'pick'>(() => {
    const store = this.store;
    if (!store || store.loading() || store.error()) return 'busy';
    return store.items().length ? 'pick' : 'empty';
  });
}
