import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslatePipe } from '@core/i18n/translate.pipe';

/**
 * 403-Seite (#71). Ziel des `authGuard`, wenn der geladene Principal die für die
 * Route geforderte Permission **wirklich** nicht hat — statt einer stillen
 * Dashboard-Umleitung. Erscheint also erst nach echter Perm-Auswertung (der Guard
 * lädt den Principal via `ensureLoaded`), nie während des Ladens.
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
