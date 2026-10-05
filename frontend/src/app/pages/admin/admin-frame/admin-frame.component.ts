import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { filter } from 'rxjs';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { ScrollFadeDirective } from '@shared/scroll-fade.directive';
import { SearchPillComponent } from '@shared/ui/search-pill/search-pill.component';
import { IconComponent, MEDIA } from '@stupa-makers/ui-kit';
import { mediaQuerySignal } from '../../../layout/media-query';
import { PageFrameService } from '../../../layout/page-frame.service';
import { AdminHealthComponent } from '../admin-health/admin-health.component';
import { ADMIN_GROUPS, ADMIN_PAGES, type AdminGroupKey, type AdminPage } from './admin-pages';

/** One group of the navigation with the pages the principal may open. */
interface NavGroup {
  key: AdminGroupKey;
  title: TranslationKey;
  pages: readonly AdminPage[];
}

/** The path of the admin home page. */
const HOME = '/admin';

/** The path of a URL without the query string and the fragment. */
function pathOf(url: string): string {
  return url.split(/[?#]/)[0];
}

/**
 * The frame of the admin area (board Verwaltung): the admin navigation beside every
 * admin page.
 *
 * - The navigation: the title "Verwaltung", "Einstellungen durchsuchen" (filters the
 *   entries by title and description, in the browser), and the groups of `ADMIN_GROUPS`.
 *   An entry shows only with one of its permissions, so the navigation never leads to
 *   the 403 page. The guard and the server stay authoritative.
 * - The home page `/admin`: the navigation is the overview. It shows the "Zustand" tiles
 *   and a description under each entry; the page beside it lists the gremien.
 * - Wide (`MEDIA.wide`): the navigation is a column beside the page and stays in view;
 *   the page sits on a sheet. The breadcrumbs then leave out "Verwaltung", because the
 *   navigation shows it.
 * - Narrower: an admin page fills the width and the breadcrumb "Verwaltung" leads back.
 *   The home page shows the navigation above the gremien.
 */
@Component({
  selector: 'app-admin-frame',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterOutlet,
    RouterLink,
    RouterLinkActive,
    TranslatePipe,
    IconComponent,
    SearchPillComponent,
    ScrollFadeDirective,
    AdminHealthComponent,
  ],
  templateUrl: './admin-frame.component.html',
  styleUrl: './admin-frame.component.scss',
})
export class AdminFrameComponent {
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly router = inject(Router);
  private readonly pageFrame = inject(PageFrameService);

  /** The viewport is wide: the navigation is a column beside the page. */
  readonly wide = mediaQuerySignal(MEDIA.wide);

  /** The admin home page is open. */
  readonly home = signal(pathOf(this.router.url) === HOME);

  /** The text of "Einstellungen durchsuchen". */
  readonly query = signal('');

  /**
   * The home page has a page beside the navigation: the gremien. Without a gremium
   * permission the home page is the navigation alone.
   */
  private readonly homeHasPage = computed(
    () => this.auth.can('admin.gremien') || this.auth.can('admin.gremium_roles'),
  );

  /** The navigation is a column beside the page (else it is above the page or hidden). */
  readonly split = computed(() => this.wide() && (!this.home() || this.homeHasPage()));

  /** The navigation shows: always on the home page, else only as the column. */
  readonly showNav = computed(() => this.home() || this.wide());

  /** The groups with the pages the principal may open and the search finds. */
  readonly groups = computed<NavGroup[]>(() => {
    const q = this.query().trim().toLocaleLowerCase();
    const hit = (p: AdminPage): boolean =>
      !q ||
      this.i18n.translate(p.title).toLocaleLowerCase().includes(q) ||
      this.i18n.translate(p.desc).toLocaleLowerCase().includes(q);
    return ADMIN_GROUPS.map((g) => ({
      ...g,
      pages: ADMIN_PAGES.filter(
        (p) => p.group === g.key && this.auth.canAny(...p.permissions) && hit(p),
      ),
    })).filter((g) => g.pages.length > 0);
  });

  constructor() {
    this.router.events
      .pipe(
        filter((e): e is NavigationEnd => e instanceof NavigationEnd),
        takeUntilDestroyed(),
      )
      .subscribe((e) => this.home.set(pathOf(e.urlAfterRedirects) === HOME));

    // The navigation shows "Verwaltung" beside the page, so the breadcrumbs leave it out.
    effect(() => this.pageFrame.crumbRoot.set(this.split() ? 'admin' : null));
    inject(DestroyRef).onDestroy(() => this.pageFrame.crumbRoot.set(null));
  }

  /** The full path of an entry. */
  protected path(page: AdminPage): string {
    return `${HOME}/${page.link}`;
  }
}
