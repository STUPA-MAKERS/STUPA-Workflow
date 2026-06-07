import { UpperCasePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { ThemeService } from '@core/theme/theme.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Locale } from '@core/i18n/translations';
import { resolveI18n } from '@shared/forms/i18n-text';
import { IconComponent, ToastComponent } from '@shared/ui';
import { AdminApiService } from '../pages/admin/admin-api.service';
import type { FooterLink } from '../pages/admin/admin.models';

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
    IconComponent,
    ToastComponent,
  ],
  templateUrl: './shell.component.html',
  styleUrl: './shell.component.scss',
})
export class ShellComponent {
  readonly theme = inject(ThemeService);
  readonly i18n = inject(I18nService);
  readonly auth = inject(AuthService);
  private readonly admin = inject(AdminApiService);

  /** Gepflegte Footer-Inhalte (#82): rechtliche Links + Copyright aus der aktiven Site-Config. */
  private readonly legalLinks = signal<FooterLink[]>([]);
  private readonly copyright = signal<Record<string, string> | null>(null);

  /** Rechtliche Links der aktiven Locale; leer ⇒ Default-Fußzeile (Impressum/Datenschutz). */
  readonly footerLinks = computed(() =>
    this.legalLinks().map((l) => ({ url: l.url, label: resolveI18n(l.label, this.i18n.locale()) })),
  );

  /** Gepflegte Copyright-Zeile der aktiven Locale (leer ⇒ Default-Co-Branding-Text). */
  readonly footerCopyright = computed(() => resolveI18n(this.copyright(), this.i18n.locale()));

  /**
   * Theme-abhängige Wortmarke: schwarze Schrift auf hell, weiße auf dunkel
   * (offizielle CD-Varianten). Die mehrfarbige Marke bleibt in beiden Modi lesbar.
   */
  readonly logoSrc = computed(() => `assets/logos/stupa-wordmark-${this.theme.resolved()}.svg`);

  constructor() {
    // Aktive Site-Config laden, damit die Fußzeile gepflegte rechtliche Links +
    // Copyright zeigt (#82). Fehlschlag/leer ⇒ Default-Fußzeile (Impressum/Datenschutz).
    this.admin.getSiteConfig().subscribe({
      next: (cfg) => {
        this.legalLinks.set(cfg.active.legalLinks ?? []);
        this.copyright.set(cfg.active.copyright ?? null);
      },
      error: () => {
        /* Default-Fußzeile bleibt */
      },
    });
  }

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
