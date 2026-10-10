import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { ButtonComponent } from '@stupa-makers/ui-kit';
import { SwUpdateService } from './sw-update.service';

/**
 * The persistent "new version" prompt with a reload button. It shows while
 * `SwUpdateService.updateReady` is true. The ui-kit toast has no action button, so the
 * prompt is its own element in the shell. It has no close button, because the old JS
 * must not keep running against the new cache.
 */
@Component({
  selector: 'app-sw-update-prompt',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, ButtonComponent],
  templateUrl: './sw-update-prompt.component.html',
  styleUrl: './sw-update-prompt.component.scss',
})
export class SwUpdatePromptComponent {
  readonly sw = inject(SwUpdateService);
}
