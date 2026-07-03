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
import { BrandingService } from '@core/branding/branding.service';
import { LOCATION } from '@core/browser/location.token';
import { I18nService } from '@core/i18n/i18n.service';
import { ThemeService } from '@core/theme/theme.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Locale } from '@core/i18n/translations';
import { resolveI18n } from '@shared/forms/i18n-text';
import { IconComponent, LoadingOverlayComponent, ToastComponent } from '@stupa-makers/ui-kit';
import { BreadcrumbsComponent } from './breadcrumbs.component';
import { AdminApiService } from '../pages/admin/admin-api.service';
import type { FooterLink } from '../pages/admin/admin.models';

interface NavItem {
  path: string;
  labelKey: Parameters<TranslatePipe['transform']>[0];
  /** Visible when the principal has at least one of these permissions (empty = any session). */
  permissions: string[];
  /** Also visible to members of any committee (e.g. meetings). */
  inAnyCommittee?: boolean;
  /** Also visible with a scoped budget view. */
  scopedBudgetView?: boolean;
  /**
   * Exact active match: needed when the path is a prefix of another nav entry
   * (e.g. `/budget` before `/budget/pots`) — otherwise the child route marks both
   * parent and child active at once.
   */
  exact?: boolean;
}

/** App frame: header (logo/nav/theme/language/account), content, footer, toasts. */
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
  readonly branding = inject(BrandingService);
  private readonly admin = inject(AdminApiService);
  private readonly router = inject(Router);
  private readonly location = inject(LOCATION);
  private readonly route = inject(ActivatedRoute);

  /** Full-width content (route data `wide`) — e.g. the budget tab with two sidebars. */
  readonly wide = signal(false);

  /** Maintained footer content: legal links + copyright from the active site config. */
  private readonly legalLinks = signal<FooterLink[]>([]);
  private readonly copyright = signal<Record<string, string> | null>(null);

  /** Legal links for the active locale; empty ⇒ default footer (imprint/privacy). */
  readonly footerLinks = computed(() =>
    this.legalLinks().map((l) => ({ url: l.url, label: resolveI18n(l.label, this.i18n.locale()) })),
  );

  /** Maintained copyright line for the active locale (empty ⇒ default co-branding text). */
  readonly footerCopyright = computed(() => resolveI18n(this.copyright(), this.i18n.locale()));

  /**
   * Theme-dependent wordmark: black type on light, white on dark (official CD
   * variants). The multicolour mark stays legible in both modes.
   */
  readonly logoSrc = computed(() => `assets/logos/stupa-wordmark-${this.theme.resolved()}.svg`);

  /** Logo click: logged in → dashboard, otherwise the public landing page. */
  readonly brandTarget = computed(() => (this.auth.isAuthenticated() ? '/dashboard' : '/'));

  constructor() {
    // Load the active site config so the footer shows maintained legal links +
    // copyright. Failure/empty ⇒ default footer (imprint/privacy).
    this.admin.getSiteConfig().subscribe({
      next: (cfg) => {
        this.legalLinks.set(cfg.active.legalLinks ?? []);
        this.copyright.set(cfg.active.copyright ?? null);
      },
      error: () => {
        /* keep the default footer */
      },
    });

    // Full width per route data (deepest active route wins).
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
    // Without application.read, this shows one's own applications/tasks.
    { path: '/applications', labelKey: 'nav.applications', permissions: [] },
    { path: '/tasks', labelKey: 'nav.tasks', permissions: [] },
    // Meetings: managers/minute-takers or any committee member.
    {
      path: '/meetings',
      labelKey: 'nav.meetings',
      permissions: ['meeting.manage', 'protocol.write'],
      inAnyCommittee: true,
    },
    {
      path: '/budget',
      labelKey: 'nav.budget',
      permissions: ['budget.view', 'budget.structure', 'budget.book'],
      // Committees with an assigned cost centre see the tab scoped.
      scopedBudgetView: true,
    },
    {
      path: '/expenses',
      labelKey: 'nav.expenses',
      permissions: ['budget.view', 'budget.structure', 'budget.book'],
    },
    {
      path: '/invoices',
      labelKey: 'nav.invoices',
      permissions: ['budget.view', 'budget.structure', 'budget.book'],
    },
    {
      path: '/accounts',
      labelKey: 'nav.konten',
      permissions: ['budget.view', 'budget.structure', 'budget.book'],
    },
    {
      path: '/admin',
      labelKey: 'nav.admin',
      permissions: ['admin.site', 'admin.gremien', 'admin.types', 'admin.roles', 'admin.notifications', 'webhook.manage', 'audit.read'],
    },
  ];

  /**
   * RBAC-filtered navigation (UX): only with an active session, and only entries
   * whose permission the principal holds. The server stays authoritative.
   */
  readonly visibleNav = computed(() => {
    if (!this.auth.isAuthenticated()) return [];
    const inAnyCommittee = this.auth.gremien().length > 0;
    return this.nav.filter(
      (item) =>
        this.auth.canAny(...item.permissions) ||
        (!!item.inAnyCommittee && inAnyCommittee) ||
        (!!item.scopedBudgetView && this.auth.hasScopedBudgetView()),
    );
  });

  toggleTheme(): void {
    this.theme.toggle();
  }

  setLocale(value: string): void {
    const locale = value as Locale;
    if (locale === this.i18n.locale()) return;
    this.i18n.setLocale(locale);
    // Server-provided i18n values (state/type/transition labels, form fields) are
    // resolved in the then-current language at load time and otherwise do not
    // update. Reload the current view → a consistent language switch.
    this.reloadForLocale();
  }

  /** Page reload after a language change (overridable/spyable in tests). */
  protected reloadForLocale(): void {
    if (typeof window !== 'undefined') {
      this.location.reload();
    }
  }

  login(): void {
    this.auth.login();
  }

  /**
   * Mobile navigation (hamburger drawer): replaces the header nav below 720px.
   * Closes on navigation, backdrop click and ESC.
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

  /** Account popout: actions like logout live only here, not directly in the header. */
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
