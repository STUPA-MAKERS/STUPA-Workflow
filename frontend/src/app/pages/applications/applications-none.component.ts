import { ChangeDetectionStrategy, Component } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { DetailNoneComponent } from '@shared/ui/detail-none/detail-none.component';

/**
 * The detail pane of `/applications` before a row is open. Only the side-by-side layout
 * shows it; one pane at a time, the list fills the screen.
 */
@Component({
  selector: 'app-applications-none',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, DetailNoneComponent],
  templateUrl: './applications-none.component.html',
  styleUrl: '../../shared/ui/detail-none/detail-none-host.scss',
})
export class ApplicationsNoneComponent {}
