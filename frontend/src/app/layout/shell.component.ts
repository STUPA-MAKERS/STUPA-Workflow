import { UpperCasePipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  HostListener,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
  ActivatedRoute,
  NavigationEnd,
  Router,
  RouterLink,
  RouterLinkActive,
  RouterOutlet,
} from '@angular/router';
import { filter } from 'rxjs';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { ThemeService } from '@core/theme/theme.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Locale } from '@core/i18n/translations';
import { resolveI18n } from '@shared/forms/i18n-text';
import { IconComponent, LoadingOverlayComponent, ToastComponent } from '@shared/ui';
import { BreadcrumbsComponent } from './breadcrumbs.component';
import { AdminApiService } from '../pages/admin/admin-api.service';
import type { FooterLink } from '../pages/admin/admin.models';

interface NavItem {
  path: string;
  labelKey: Parameters<TranslatePipe['transform']>[0];
  /** Sichtbar, wenn der Principal mind. eine dieser Permissions hat (leer = jede Session). */
  permissions: string[];
  /** Zusätzlich sichtbar für Mitglieder **irgendeines** Gremiums (z. B. Sitzungen, #sessions). */
  inAnyCommittee?: boolean;
  /**
   * Exakter Aktiv-Abgleich (#106): nötig, wenn der Pfad Präfix eines anderen
   * Nav-Eintrags ist (z. B. `/budget` vor `/budget/pots`) — sonst markiert die
   * Kind-Route Eltern **und** Kind gleichzeitig aktiv.
   */
  exact?: boolean;
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
    LoadingOverlayComponent,
    BreadcrumbsComponent,
  ],
  templateUrl: './shell.component.html',
  styleUrl: './shell.component.scss',
})
export class ShellComponent {
  readonly theme = inject(ThemeService);
  readonly i18n = inject(I18nService);
  readonly auth = inject(AuthService);
  private readonly admin = inject(AdminApiService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  /** Inhalt volle Breite (Route-Data `wide`) — z. B. Budget-Tab mit zwei Sidebars. */
  readonly wide = signal(false);

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

  /** Logo-Klick: angemeldet → Dashboard, sonst öffentliche Startseite. */
  readonly brandTarget = computed(() => (this.auth.isAuthenticated() ? '/dashboard' : '/'));

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

    // Volle Breite je Route-Data (tiefste aktive Route gewinnt).
    this.router.events
      .pipe(
        filter((e) => e instanceof NavigationEnd),
        takeUntilDestroyed(),
      )
      .subscribe(() => {
        let r = this.route.firstChild;
        let wide = false;
        while (r) {
          wide = r.snapshot.data['wide'] === true || wide;
          r = r.firstChild;
        }
        this.wide.set(wide);
        this.closeMobileNav();
      });
  }

  private readonly nav: NavItem[] = [
    { path: '/dashboard', labelKey: 'nav.dashboard', permissions: [] },
    // Ohne application.read sieht man hier die eigenen Anträge/Aufgaben (#24).
    { path: '/applications', labelKey: 'nav.applications', permissions: [] },
    { path: '/tasks', labelKey: 'nav.tasks', permissions: [] },
    // Sitzungen: Verwalter/Protokollanten **oder** jedes Gremium-Mitglied (#sessions).
    {
      path: '/meetings',
      labelKey: 'nav.meetings',
      permissions: ['meeting.manage', 'protocol.write'],
      inAnyCommittee: true,
    },
    {
      path: '/budget',
      labelKey: 'nav.budget',
      permissions: ['budget.view', 'budget.manage'],
    },
    {
      path: '/expenses',
      labelKey: 'nav.expenses',
      permissions: ['budget.view', 'budget.manage'],
    },
    { path: '/admin', labelKey: 'nav.admin', permissions: ['admin.config'] },
  ];

  /**
   * RBAC-gefilterte Navigation (UX): nur bei aktiver Session, und nur Einträge,
   * deren Permission der Principal besitzt. Server bleibt autoritativ (§2).
   */
  readonly visibleNav = computed(() => {
    if (!this.auth.isAuthenticated()) return [];
    const inAnyCommittee = this.auth.gremien().length > 0;
    return this.nav.filter(
      (item) =>
        this.auth.canAny(...item.permissions) || (!!item.inAnyCommittee && inAnyCommittee),
    );
  });

  toggleTheme(): void {
    this.theme.toggle();
  }

  setLocale(value: string): void {
    const locale = value as Locale;
    if (locale === this.i18n.locale()) return;
    this.i18n.setLocale(locale);
    // Server-gelieferte i18n-Werte (State-/Typ-/Transition-Labels, Formularfelder)
    // werden beim Laden in der damaligen Sprache aufgelöst und aktualisieren sich
    // sonst nicht. Aktuelle Ansicht neu laden → durchgängiger Sprachwechsel (#i18n).
    this.reloadForLocale();
  }

  /** Seiten-Reload nach Sprachwechsel (in Tests überschreib-/spionierbar). */
  protected reloadForLocale(): void {
    if (typeof window !== 'undefined') {
      window.location.reload();
    }
  }

  login(): void {
    this.auth.login();
  }

  /**
   * Mobile-Navigation (Hamburger-Drawer): ersetzt unterhalb von 720px die
   * Header-Nav. Schließt bei Navigation, Backdrop-Klick und ESC.
   */
  readonly mobileNavOpen = signal(false);

  toggleMobileNav(): void {
    this.mobileNavOpen.update((v) => !v);
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    this.closeMobileNav();
    this.closeAccountMenu();
  }

  closeMobileNav(): void {
    this.mobileNavOpen.set(false);
  }

  /** Konto-Popout (#51): Aktionen wie Abmelden liegen nur hier, nicht direkt im Header. */
  readonly accountMenuOpen = signal(false);

  toggleAccountMenu(): void {
    this.accountMenuOpen.update((v) => !v);
  }

  closeAccountMenu(): void {
    this.accountMenuOpen.set(false);
  }

  logout(): void {
    this.closeAccountMenu();
    this.auth.logout();
  }
}
