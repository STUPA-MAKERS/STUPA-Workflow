import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { LoadingService } from '@core/loading/loading.service';

/**
 * The global loading signal: a thin bar at the top edge of the page while a GET runs.
 *
 * It replaces a dimmed overlay with a spinner over the page. The overlay covered the
 * skeletons and the old content that a page keeps while it reloads, so a load that was
 * built to stay still flashed grey and blurred. The bar moves nothing and blocks nothing;
 * the page itself shows what is loading. The {@link LoadingService} decides when it shows.
 */
@Component({
  selector: 'app-load-bar',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe],
  templateUrl: './load-bar.component.html',
  styleUrl: './load-bar.component.scss',
})
export class LoadBarComponent {
  protected readonly loading = inject(LoadingService);
}
