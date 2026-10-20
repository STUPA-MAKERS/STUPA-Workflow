import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { AuthService } from '@core/auth/auth.service';
import { BrandingService } from '@core/branding/branding.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { ThemeService } from '@core/theme/theme.service';
import { ButtonComponent, IconComponent } from '@stupa-makers/ui-kit';
import { HelpMenuComponent } from '../../features/help/help-menu/help-menu.component';
import { LanguageSelectComponent } from '../language-select/language-select.component';

/**
 * The top bar of the public frame (landing page, apply wizard, status page, magic link,
 * 404 while signed out): the wordmark, the help menu, the language, the appearance and
 * "Anmelden".
 *
 * A signed-out visitor has no account menu, so language and appearance stay in the bar.
 */
@Component({
  selector: 'app-public-header',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    TranslatePipe,
    ButtonComponent,
    IconComponent,
    HelpMenuComponent,
    LanguageSelectComponent,
  ],
  templateUrl: './public-header.component.html',
  styleUrl: './public-header.component.scss',
})
export class PublicHeaderComponent {
  readonly auth = inject(AuthService);
  readonly branding = inject(BrandingService);
  readonly theme = inject(ThemeService);
  readonly i18n = inject(I18nService);

  /** The wordmark of the branding, or the built-in one in the colours of the theme. */
  readonly logoSrc = this.branding.wordmarkSrc;
  /** The mark alone, for a phone, where the wordmark does not fit beside the controls. */
  readonly markSrc = this.branding.markSrc;

  login(): void {
    this.auth.login();
  }
}
