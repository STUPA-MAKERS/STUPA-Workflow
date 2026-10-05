import { ChangeDetectionStrategy, Component } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { EmptyStateComponent } from '@shared/ui/empty-state/empty-state.component';

/**
 * The page pane of `/admin` before an admin page is open (board Verwaltung).
 *
 * The admin frame shows the navigation beside it, so this pane is the empty sheet of
 * the other list/detail pages ("Keine Seite geöffnet"), on the same surface as an open
 * admin page. The pane does not jump when an entry opens. Only the side-by-side layout
 * shows it; one column at a time, the navigation fills the screen.
 */
@Component({
  selector: 'app-admin-home',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, EmptyStateComponent],
  template: `
    <div class="none">
      <app-empty-state
        icon="shield"
        [heading]="'admin.home.none' | t"
        [body]="'admin.home.noneBody' | t"
      />
    </div>
  `,
  styles: [
    `
      :host {
        display: flex;
        flex: 1 1 auto;
        min-height: 0;
      }
      .none {
        display: grid;
        flex: 1 1 auto;
        place-items: center;
      }
    `,
  ],
})
export class AdminHomeComponent {}
