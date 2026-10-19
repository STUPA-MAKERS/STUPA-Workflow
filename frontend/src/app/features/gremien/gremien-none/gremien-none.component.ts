import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { DetailNoneComponent, type DetailNoneState } from '@shared/ui/detail-none/detail-none.component';
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
  imports: [TranslatePipe, DetailNoneComponent],
  templateUrl: './gremien-none.component.html',
  styleUrl: '../../../shared/ui/detail-none/detail-none-host.scss',
})
export class GremienNoneComponent {
  private readonly store = inject(GremienStore, { optional: true });

  protected readonly state = computed<DetailNoneState>(() => {
    const store = this.store;
    if (!store || store.loading() || store.error()) return 'busy';
    return store.items().length ? 'pick' : 'empty';
  });
}
