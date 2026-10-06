import { ChangeDetectionStrategy, Component } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { EmptyStateComponent } from '@shared/ui/empty-state/empty-state.component';

/**
 * The detail pane of `/applications` before a row is open. Only the side-by-side layout
 * shows it; one pane at a time, the list fills the screen.
 */
@Component({
  selector: 'app-applications-none',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, EmptyStateComponent],
  templateUrl: './applications-none.component.html',
  styleUrl: './applications-none.component.scss',
})
export class ApplicationsNoneComponent {}
