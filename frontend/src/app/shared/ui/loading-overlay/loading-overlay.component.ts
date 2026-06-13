import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { LoadingService } from '@core/loading/loading.service';

/**
 * Globaler Ladebildschirm (#loading): halbtransparenter Overlay über dem
 * Inhaltsbereich (unterhalb des Headers) mit zentriertem Spinner, gesteuert vom
 * {@link LoadingService}. Header/Navigation bleiben bedienbar. Liegt unter
 * Dialogen/Toasts (z-index), damit diese darüber sichtbar bleiben.
 */
@Component({
  selector: 'app-loading-overlay',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe],
  templateUrl: './loading-overlay.component.html',
  styleUrl: './loading-overlay.component.scss',
})
export class LoadingOverlayComponent {
  protected readonly loading = inject(LoadingService);
}
