import { ChangeDetectionStrategy, Component } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { DetailNoneComponent } from '@shared/ui/detail-none/detail-none.component';

/**
 * The sheet of `/account` before an account page is open. Only the wide frame shows it,
 * beside the account navigation; below wide the navigation is the whole page.
 */
@Component({
  selector: 'app-account-none',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, DetailNoneComponent],
  templateUrl: './account-none.component.html',
  styleUrl: '../../shared/ui/detail-none/detail-none-host.scss',
})
export class AccountNoneComponent {}
