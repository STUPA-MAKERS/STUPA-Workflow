import { ChangeDetectionStrategy, Component } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { ErrorPageComponent } from './error-page/error-page.component';

/**
 * 404 page. The shell frames it: the public bar while nobody is signed in, the rail
 * while a principal is. The way out is the start page, which sends a signed-in
 * principal on to the dashboard.
 */
@Component({
  selector: 'app-not-found',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, ErrorPageComponent],
  templateUrl: './not-found.component.html',
})
export class NotFoundComponent {}
