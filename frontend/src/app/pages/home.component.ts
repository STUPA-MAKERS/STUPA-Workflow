import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { AuthService } from '@core/auth/auth.service';
import { BrandingService } from '@core/branding/branding.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { resolveI18n } from '@shared/forms/i18n-text';
import { IconComponent } from '@stupa-makers/ui-kit';

/**
 * Public home page (board Oeffentlich-Start).
 *
 * The body is two choices and nothing else: submit an application, or sign in as a
 * Gremium member. A visitor is one or the other, and the page cannot tell which, so it
 * weights both the same instead of guessing. Above them the heading and, when the admin
 * set one, the welcome text of the branding (Freitext "welcome"); below them the hint
 * about the status link.
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
  private readonly auth = inject(AuthService);
  private readonly branding = inject(BrandingService);
  private readonly i18n = inject(I18nService);

  /** The configured welcome text in the active language, or empty. */
  protected readonly welcome = computed(() =>
    resolveI18n(this.branding.freetexts().welcome ?? null, this.i18n.locale()).trim(),
  );

  /** Start the OIDC login. It leaves the SPA, so there is no route to navigate to. */
  login(): void {
    this.auth.login();
  }
}
