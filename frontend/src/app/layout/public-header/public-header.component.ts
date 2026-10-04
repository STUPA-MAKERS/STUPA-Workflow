import { UpperCasePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { AuthService } from '@core/auth/auth.service';
import { BrandingService } from '@core/branding/branding.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { ThemeService } from '@core/theme/theme.service';
import { IconComponent } from '@stupa-makers/ui-kit';
import { LocaleSwitchService } from '../locale-switch.service';

/**
 * The top bar of the public frame (landing page, apply wizard, status page, magic link,
 * 404 while signed out): the wordmark, the language, the appearance and "Anmelden".
 *
 * A signed-out visitor has no account menu, so language and appearance stay in the bar.
 */
@Component({
  selector: 'app-public-header',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, TranslatePipe, UpperCasePipe, IconComponent],
  templateUrl: './public-header.component.html',
  styleUrl: './public-header.component.scss',
})
export class PublicHeaderComponent {
  readonly auth = inject(AuthService);
  readonly branding = inject(BrandingService);
  readonly theme = inject(ThemeService);
  readonly i18n = inject(I18nService);
  private readonly locales = inject(LocaleSwitchService);

  /** Black type on light, white type on dark: both are official CD variants. */
  readonly logoSrc = computed(() => `assets/logos/stupa-wordmark-${this.theme.resolved()}.svg`);
  /** The mark alone, for a phone, where the wordmark does not fit beside the controls. */
  readonly markSrc = 'assets/logos/stupa-mark.svg';

  setLocale(value: string): void {
    this.locales.switchTo(value);
  }

  login(): void {
    this.auth.login();
  }
}
