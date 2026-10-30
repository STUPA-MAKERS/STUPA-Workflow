import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import { RouterLink } from '@angular/router';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { IconComponent, ThemeService } from '@stupa-makers/ui-kit';
import {
  AccountMenuComponent,
  type AccountMenuVariant,
  type ShellLanguage,
} from '@stupa-makers/ui-kit/shell';
import { LocaleSwitchService } from '../locale-switch.service';

/**
 * The account menu of the kit (`app-account-menu`), filled from the session of the app: the
 * name and the avatar of the principal, the account pages ("Benachrichtigungen" and, with
 * `mcp.use`, "API-Zugriff"), the languages (DE, EN and the active extra languages of the
 * admin page), the dark design and sign-out.
 *
 * A language choice goes through `LocaleSwitchService`, which reloads the view. The dark
 * switch sets an explicit preference of the `ThemeService`.
 */
@Component({
  selector: 'app-account',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [AccountMenuComponent, RouterLink, TranslatePipe, IconComponent],
  template: `
    <app-account-menu
      [variant]="variant()"
      [name]="auth.displayName()"
      avatarId="me"
      [languages]="languages()"
      [language]="i18n.uiLocale()"
      [dark]="theme.resolved() === 'dark'"
      (languageChange)="locales.switchTo($event)"
      (darkChange)="setDark($event)"
      (logout)="auth.logout()"
      (navigated)="navigated.emit()"
    >
      <ng-container accountItems>
        <a class="am__item" routerLink="/account/notifications">
          <app-icon name="bell" [size]="19" />{{ 'account.menu.notifications' | t }}
        </a>
        @if (auth.canAny('mcp.use')) {
          <a class="am__item" routerLink="/account/grants">
            <app-icon name="webhook" [size]="19" />{{ 'account.menu.apiAccess' | t }}
          </a>
        }
      </ng-container>
    </app-account-menu>
  `,
  styles: `
    :host {
      display: contents;
    }
  `,
})
export class AppAccountMenuComponent {
  protected readonly auth = inject(AuthService);
  protected readonly i18n = inject(I18nService);
  protected readonly theme = inject(ThemeService);
  protected readonly locales = inject(LocaleSwitchService);

  /** `popover` beside the rail, `sheet` inline in a sheet, `auto` by the phone media query. */
  readonly variant = input<AccountMenuVariant>('popover');

  /** A link was followed: the sheet that holds the inline menu closes. */
  readonly navigated = output<void>();

  /** The languages of the switch, each with its native name. */
  protected readonly languages = computed<ShellLanguage[]>(() =>
    this.i18n.locales().map((value) => ({ value, label: this.i18n.languageName(value) })),
  );

  protected setDark(dark: boolean): void {
    this.theme.setPreference(dark ? 'dark' : 'light');
  }
}
