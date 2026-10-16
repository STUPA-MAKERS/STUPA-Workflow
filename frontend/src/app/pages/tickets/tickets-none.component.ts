import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { EmptyStateComponent } from '@shared/ui/empty-state/empty-state.component';
import { TicketsComponent } from './tickets.component';

/**
 * The detail pane of `/tickets` before a ticket is open. Only the side-by-side layout
 * shows it. While the list loads or after an error it shows only the empty sheet: the
 * list pane says what happens.
 */
@Component({
  selector: 'app-tickets-none',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, EmptyStateComponent],
  templateUrl: './tickets-none.component.html',
  styleUrl: './tickets-none.component.scss',
})
export class TicketsNoneComponent {
  private readonly page = inject(TicketsComponent, { optional: true });

  protected readonly state = computed<'busy' | 'empty' | 'pick'>(() => {
    const page = this.page;
    if (!page || page.loading() || page.error()) return 'busy';
    return page.hasRows() ? 'pick' : 'empty';
  });
}
