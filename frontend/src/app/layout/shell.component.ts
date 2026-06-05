import { UpperCasePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { ThemeService } from '@core/theme/theme.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Locale } from '@core/i18n/translations';
import { ToastComponent } from '@shared/ui/toast/toast.component';

interface NavItem {
  path: string;
  labelKey: Parameters<TranslatePipe['transform']>[0];
  /** Sichtbar, wenn der Principal mind. eine dieser Permissions hat (leer = jede Session). */
  permissions: string[];
}

/** App-Rahmen: Header (Logo/Nav/Theme/Sprache/Konto), Inhalt, Footer, Toasts. */
@Component({
  selector: 'app-shell',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterOutlet,
    RouterLink,
    RouterLinkActive,
    TranslatePipe,
    UpperCasePipe,
    ToastComponent,
  ],
  templateUrl: './shell.component.html',
  styleUrl: './shell.component.scss',
})
export class ShellComponent {
  readonly theme = inject(ThemeService);
  readonly i18n = inject(I18nService);
  readonly auth = inject(AuthService);

  private readonly nav: NavItem[] = [
    { path: '/dashboard', labelKey: 'nav.dashboard', permissions: [] },
    { path: '/applications', labelKey: 'nav.applications', permissions: ['application.read'] },
    { path: '/voting', labelKey: 'nav.voting', permissions: ['vote.cast', 'vote.manage'] },
    { path: '/meetings', labelKey: 'nav.meetings', permissions: ['meeting.manage', 'protocol.write'] },
    { path: '/budget', labelKey: 'nav.budget', permissions: ['budget.view', 'budget.manage'] },
    { path: '/admin', labelKey: 'nav.admin', permissions: ['admin.config'] },
  ];

  /**
   * RBAC-gefilterte Navigation (UX): nur bei aktiver Session, und nur Einträge,
   * deren Permission der Principal besitzt. Server bleibt autoritativ (§2).
   */
  readonly visibleNav = computed(() =>
    this.auth.isAuthenticated()
      ? this.nav.filter((item) => this.auth.canAny(...item.permissions))
      : [],
  );

  toggleTheme(): void {
    this.theme.toggle();
  }

  setLocale(value: string): void {
    this.i18n.setLocale(value as Locale);
  }

  login(): void {
    this.auth.login();
  }

  logout(): void {
    this.auth.logout();
  }
}
