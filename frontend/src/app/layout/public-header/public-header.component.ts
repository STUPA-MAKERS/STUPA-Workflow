import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { AuthService } from '@core/auth/auth.service';
import { BrandingService } from '@core/branding/branding.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { ThemeService, ButtonComponent, ButtonLinkComponent } from '@stupa-makers/ui-kit';
import { HelpMenuComponent } from '../../features/help/help-menu/help-menu.component';
import { LanguageSelectComponent } from '../language-select/language-select.component';

/**
 * The top bar of the public frame (landing page, apply wizard, status page, magic link,
 * 404 while signed out): the wordmark, the language, the menus "Barrierefreiheit" and
 * "Hilfe", and "Anmelden".
 *
 * A signed-out visitor has no account menu, so the language stays in the bar. The dark theme
 * is the switch "Dunkles Design" in "Barrierefreiheit", because one setting has one switch on
 * a screen (spec 000593).
 *
 * The bar stays at the top while the page scrolls, like the bar of a detail in the signed-in
 * frame: frosted glass with a light shadow once content runs under it (`pub--under`), the
 * solid page colour at rest, because at rest the glass would blur the page below into it.
 */
@Component({
  selector: 'app-public-header',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    TranslatePipe,
    ButtonComponent,
    ButtonLinkComponent,
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

  /** The page has scrolled, so content runs under the bar. */
  protected readonly under = signal(false);

  constructor() {
    let frame = 0;
    const check = (): void => {
      frame = 0;
      this.under.set((document.scrollingElement?.scrollTop ?? window.scrollY) > 0);
    };
    const onScroll = (): void => {
      if (!frame) frame = requestAnimationFrame(check);
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    frame = requestAnimationFrame(check);
    inject(DestroyRef).onDestroy(() => {
      window.removeEventListener('scroll', onScroll);
      if (frame) cancelAnimationFrame(frame);
    });
  }

  /** The wordmark of the branding, or the built-in one in the colours of the theme. */
  readonly logoSrc = this.branding.wordmarkSrc;
  /** The mark alone, for a phone, where the wordmark does not fit beside the controls. */
  readonly markSrc = this.branding.markSrc;

}
