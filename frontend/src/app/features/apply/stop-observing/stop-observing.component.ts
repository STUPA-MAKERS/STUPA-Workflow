import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { ApiClient } from '@core/api/api-client.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { ButtonComponent, ButtonLinkComponent, IconComponent } from '@stupa-makers/ui-kit';

/** The state of the page: the ask, the end in flight, the result. */
type Phase = 'ask' | 'busy' | 'done' | 'invalid';

/** Read the token of the end link from the fragment `#t=<token>`. */
export function endToken(fragment: string): string {
  return new URLSearchParams(fragment.replace(/^#/, '')).get('t')?.trim() ?? '';
}

/**
 * The page `/stop-observing#t=<token>` of the end link in the observer mails (spec 000754).
 *
 * It needs no login, because an observer may have no account. The token rides the
 * fragment, so it never reaches a server log. The page asks first and ends the
 * observation only on the button, because a mail scanner opens every link of a mail.
 */
@Component({
  selector: 'app-stop-observing',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, TranslatePipe, ButtonComponent, ButtonLinkComponent, IconComponent],
  templateUrl: './stop-observing.component.html',
  styleUrl: '../apply-confirmation.component.scss',
})
export class StopObservingComponent {
  private readonly api = inject(ApiClient);
  private readonly token = endToken(location.hash);

  readonly phase = signal<Phase>(this.token ? 'ask' : 'invalid');

  /** End the observation. A 404 means the link is dead: ended already, or cut. */
  end(): void {
    if (this.phase() !== 'ask') return;
    this.phase.set('busy');
    this.api.endObservation(this.token).subscribe({
      next: () => this.phase.set('done'),
      error: (err: { status?: number }) =>
        this.phase.set(err.status === 404 || err.status === 422 ? 'invalid' : 'ask'),
    });
  }
}
