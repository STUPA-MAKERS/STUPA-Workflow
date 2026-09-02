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
import { CommandPaletteComponent } from '../features/search/command-palette.component';
import { searchShortcutLabel } from '../features/search/shortcut';
import { PrefetchService } from '@core/cache/prefetch.service';
import { ThemeService } from '@core/theme/theme.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { Locale } from '@core/i18n/translations';
import { resolveI18n } from '@shared/forms/i18n-text';
import { IconComponent, LoadingOverlayComponent, ToastComponent } from '@stupa-makers/ui-kit';

interface NavItem {
  path: string;
  labelKey: Parameters<TranslatePipe['transform']>[0];
  /** Visible when the principal has at least one of these permissions (empty = any session). */
  permissions: string[];
  /** Also visible to a member of any Gremium, for example the meetings entry. */
  inAnyCommittee?: boolean;
  /** Also visible with a scoped budget view. */
  scopedBudgetView?: boolean;
  /**
   * Match the active route exactly. This is needed when the path is a prefix of
   * another nav entry, for example `/budget` before `/budget/pots`. Without it a
   * child route marks the parent and the child active at the same time.
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
    CommandPaletteComponent,
  ],
  templateUrl: './shell.component.html',
  styleUrl: './shell.component.scss',
})
export class ShellComponent {
  /** `⌘K` only where that key exists. Computed, so a language switch re-spells it. */
  readonly searchShortcut = computed(() => searchShortcutLabel(this.i18n.locale()));

  // Injected for its side effect: it warms the reference-data cache after sign-in.
  // Nothing reads it, and that is the point — the pages that need the data find it
  // in the cache rather than being coupled to a prefetch they did not ask for.
  private readonly prefetch = inject(PrefetchService);

  readonly theme = inject(ThemeService);
  readonly i18n = inject(I18nService);
  readonly auth = inject(AuthService);
  readonly branding = inject(BrandingService);
  private readonly router = inject(Router);
  private readonly location = inject(LOCATION);
  private readonly route = inject(ActivatedRoute);

  /** Full-width content from route data `wide`, for example the budget tab with two sidebars. */
  readonly wide = signal(false);

  /* Footer content comes from the BRANDING service, which loads the public site config.
     It used to come from `/admin/site-config`, which needs a session: a logged-out
     visitor on the landing page or the 404 therefore always saw the built-in defaults,
     whatever the admin had configured. It also spared every non-admin an admin request
     on each page load. */

  /** Legal links for the active locale. Empty means the default footer (imprint/privacy). */
  readonly footerLinks = computed(() =>
    this.branding
      .legalLinks()
      .map((l) => ({ url: l.url, label: resolveI18n(l.label, this.i18n.locale()) })),
  );

  /** Copyright line for the active locale. Empty means the default co-branding text. */
  readonly footerCopyright = computed(() =>
    resolveI18n(this.branding.copyright(), this.i18n.locale()),
  );

  /**
   * Theme-dependent wordmark: black type on light, white type on dark. Both are
   * official CD variants. The multicolor mark stays legible in both modes.
   */
  readonly logoSrc = computed(() => `assets/logos/stupa-wordmark-${this.theme.resolved()}.svg`);

  /** Logo click: logged in → dashboard, otherwise the public landing page. */
  readonly brandTarget = computed(() => (this.auth.isAuthenticated() ? '/dashboard' : '/'));

  constructor() {
    // Full width comes from the route data. The deepest active route wins.
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
    // Without application.read these pages show only the applications and tasks of the user.
    { path: '/applications', labelKey: 'nav.applications', permissions: [] },
    { path: '/tasks', labelKey: 'nav.tasks', permissions: [] },
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
      // A Gremium with an assigned cost center sees the tab in scoped form.
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
      path: '/admin',
      labelKey: 'nav.admin',
      permissions: ['admin.site', 'admin.gremien', 'admin.types', 'admin.roles', 'admin.notifications', 'webhook.manage', 'audit.read'],
    },
  ];

  /**
   * RBAC-filtered navigation for the UX.
   *
   * It needs an active session and shows only the entries whose permission the
   * principal holds. The server stays authoritative.
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
    // The server resolves its i18n values (state, type and transition labels, form
    // fields) in the language of the load and never updates them later. Reload the
    // current view to get a consistent language switch.
    this.reloadForLocale();
  }

  /** Reload the page after a language change. Tests override or spy on this method. */
  protected reloadForLocale(): void {
    if (typeof window !== 'undefined') {
      this.location.reload();
    }
  }

  login(): void {
    this.auth.login();
  }

  /**
   * Mobile navigation drawer. It replaces the header nav below 720px. It closes on
   * navigation, on a backdrop click and on ESC.
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

  /** Account popout. Actions such as logout live only here, not in the header. */
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
