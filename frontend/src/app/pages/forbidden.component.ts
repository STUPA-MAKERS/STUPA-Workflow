import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslatePipe } from '@core/i18n/translate.pipe';

/**
 * 403 page. Target of the `authGuard` when the loaded principal **really** lacks
 * the permission required for the route — instead of a silent dashboard redirect.
 * So it appears only after a real permission check (the guard loads the principal
 * via `ensureLoaded`), never during loading.
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
