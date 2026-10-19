import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { DetailNoneComponent, type DetailNoneState } from '@shared/ui/detail-none/detail-none.component';
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
  imports: [TranslatePipe, DetailNoneComponent],
  templateUrl: './tickets-none.component.html',
  styleUrl: '../../shared/ui/detail-none/detail-none-host.scss',
})
export class TicketsNoneComponent {
  private readonly page = inject(TicketsComponent, { optional: true });

  protected readonly state = computed<DetailNoneState>(() => {
    const page = this.page;
    if (!page || page.loading() || page.error()) return 'busy';
    return page.hasRows() ? 'pick' : 'empty';
  });
}
