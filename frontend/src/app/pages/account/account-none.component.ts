import { ChangeDetectionStrategy, Component } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { DetailNoneComponent } from '@stupa-makers/ui-kit';

/**
 * The detail pane of `/account` before an account page is open (spec 000665). Only the
 * side-by-side layout shows it; one pane at a time, the list of Konto fills the screen.
 */
@Component({
  selector: 'app-account-none',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, DetailNoneComponent],
  templateUrl: './account-none.component.html',
  styles: `
    @use 'detail-none-host' as dnh;
    :host {
      @include dnh.host;
    }
  `,
})
export class AccountNoneComponent {}
