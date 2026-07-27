import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslatePipe } from '@core/i18n/translate.pipe';

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
  imports: [RouterLink, TranslatePipe],
  templateUrl: './forbidden.component.html',
  styleUrl: './forbidden.component.scss',
})
export class ForbiddenComponent {}
