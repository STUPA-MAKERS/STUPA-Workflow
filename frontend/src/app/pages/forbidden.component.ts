import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { FeatureService } from '@core/features/feature.service';
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
export class ForbiddenComponent {
  /** The start page: the activity, or the Anträge while `Aktivität` is off. */
  protected readonly home = inject(FeatureService).home;
}
