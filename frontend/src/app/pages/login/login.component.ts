import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { ApiClient } from '@core/api/api-client.service';
import { AuthService } from '@core/auth/auth.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  ButtonComponent,
  ButtonLinkComponent,
  IconComponent,
  InputComponent,
  NoteComponent,
  StatusTextComponent,
} from '@stupa-makers/ui-kit';
import { AltchaComponent } from '../../features/apply/altcha.component';

/** The address shape the form takes before it sends: one `@` with text on both sides. */
const EMAIL_SHAPE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

type Phase = 'form' | 'sending' | 'sent' | 'error';

/**
 * The login page of the public website (`/login`).
 *
 * It offers the SSO login of the members and the e-mail link of the applicants without an
 * account. The e-mail form needs ALTCHA, unless the server has ALTCHA off. The server answers
 * 202 for every address, so the page shows the same confirmation for every address and tells
 * nothing about it.
 */
@Component({
  selector: 'app-login',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    RouterLink,
    TranslatePipe,
    AltchaComponent,
    ButtonComponent,
    ButtonLinkComponent,
    IconComponent,
    InputComponent,
    NoteComponent,
    StatusTextComponent,
  ],
  templateUrl: './login.component.html',
  styleUrl: './login.component.scss',
})
export class LoginComponent {
  private readonly api = inject(ApiClient);
  private readonly auth = inject(AuthService);
  private readonly route = inject(ActivatedRoute);

  /** The page was opened from an invalid login link (`?link=invalid`). */
  readonly linkInvalid = this.route.snapshot.queryParamMap.get('link') === 'invalid';

  readonly email = signal('');
  readonly phase = signal<Phase>('form');
  readonly altchaSolution = signal<string | null>(null);
  readonly altchaRequired = signal(true);

  readonly emailValid = computed(() => EMAIL_SHAPE.test(this.email().trim()));
  readonly canSend = computed(
    () =>
      this.emailValid() &&
      this.phase() !== 'sending' &&
      (!this.altchaRequired() || this.altchaSolution() !== null),
  );

  /** Start the OIDC login. It leaves the SPA. */
  ssoLogin(): void {
    this.auth.login();
  }

  onAltchaSolved(solution: string): void {
    this.altchaSolution.set(solution);
  }

  onAltchaUnavailable(): void {
    this.altchaRequired.set(false);
  }

  /** Send the address. Every answer 202 shows the same confirmation. */
  send(): void {
    if (!this.canSend()) return;
    this.phase.set('sending');
    this.api
      .requestEmailLogin({ email: this.email().trim(), altcha: this.altchaSolution() })
      .subscribe({
        next: () => this.phase.set('sent'),
        error: () => {
          this.altchaSolution.set(null);
          this.phase.set('error');
        },
      });
  }

  /** Back to the form, for a typo in the address. */
  again(): void {
    this.altchaSolution.set(null);
    this.phase.set('form');
  }
}
