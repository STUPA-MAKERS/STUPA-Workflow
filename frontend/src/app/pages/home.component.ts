import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { AuthService } from '@core/auth/auth.service';
import { BrandingService } from '@core/branding/branding.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { IconComponent } from '@stupa-makers/ui-kit';

/**
 * Public home page.
 *
 * The body is two choices and nothing else: submit an application, or sign in as a
 * Gremium member. A visitor is one or the other, and the page cannot tell which, so it
 * weights both the same instead of guessing.
 */
@Component({
  selector: 'app-home',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, TranslatePipe, IconComponent],
  templateUrl: './home.component.html',
  styleUrl: './home.component.scss',
})
export class HomeComponent {
  /** Configurable app name for the eyebrow line. It falls back to the i18n `app.title`. */
  readonly branding = inject(BrandingService);
  private readonly auth = inject(AuthService);

  /** Start the OIDC login. It leaves the SPA, so there is no route to navigate to. */
  login(): void {
    this.auth.login();
  }
}
