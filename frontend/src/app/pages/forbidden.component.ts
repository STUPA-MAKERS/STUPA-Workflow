import { ChangeDetectionStrategy, Component } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { ErrorPageComponent } from './error-page/error-page.component';

/**
 * 403 page. The `authGuard` routes here when the loaded principal truly lacks the
 * route permission, instead of a silent redirect to the dashboard.
 *
 * The guard loads the principal with `ensureLoaded` before it checks permissions. So
 * the page appears only after a real permission check. It never appears while the
 * load runs.
 */
@Component({
  selector: 'app-forbidden',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, ErrorPageComponent],
  templateUrl: './forbidden.component.html',
  styleUrl: './error-page/error-route.scss',
})
export class ForbiddenComponent {}
