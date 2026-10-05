import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  type ElementRef,
  Injector,
  afterNextRender,
  computed,
  effect,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
  type ActivatedRouteSnapshot,
  NavigationEnd,
  Router,
  RouterLink,
  RouterLinkActive,
  RouterOutlet,
} from '@angular/router';
import { filter } from 'rxjs';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { ScrollFadeDirective } from '@shared/scroll-fade.directive';
import { SearchPillComponent } from '@shared/ui/search-pill/search-pill.component';
import { StickyBarComponent } from '@shared/ui/sticky-bar/sticky-bar.component';
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
 * The `data.adminNav` value of the deepest active route:
 *
 * - `false`: the page needs the full width at every size (the flow editor, the form
 *   editor), so the frame leaves out the navigation column.
 * - `'xl'`: the page fits beside the navigation only from {@link XL} on (the cost
 *   centres). Below that it takes the full width.
 * - anything else: the navigation column shows on a wide viewport.
 */
type AdminNavMode = 'always' | 'xl' | 'never';

function navMode(root: ActivatedRouteSnapshot): AdminNavMode {
  let r: ActivatedRouteSnapshot = root;
  while (r.firstChild) r = r.firstChild;
  const v: unknown = r.data['adminNav'];
  return v === false ? 'never' : v === 'xl' ? 'xl' : 'always';
}

/** From this width on, a page with `adminNav: 'xl'` fits beside the navigation. */
const XL = '(min-width: 1440px)';

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
 * - A route with `data: { adminNav: false }` (the flow editor, the form editor) fills
 *   the width at every size, the same as the narrow mode. A route with
 *   `data: { adminNav: 'xl' }` (the cost centres) does so below 1440 px.
 * - The "Zustand" tiles stay while the search hides them, so a cleared search does not
 *   load them again.
 * - The entries of the column scroll on their own. After each navigation the column
 *   scrolls the active entry into view; the window does not move.
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
    StickyBarComponent,
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
  private readonly injector = inject(Injector);

  /** The scrolling part of the navigation column (absent while the navigation is hidden). */
  private readonly navBody = viewChild<ElementRef<HTMLElement>>('navBody');

  /** The viewport is wide: the navigation is a column beside the page. */
  readonly wide = mediaQuerySignal(MEDIA.wide);

  /** The admin home page is open. */
  readonly home = signal(pathOf(this.router.url) === HOME);

  /** The viewport is wide enough for a page with `adminNav: 'xl'` beside the navigation. */
  private readonly xl = mediaQuerySignal(XL);

  /** The `data.adminNav` mode of the active page. */
  private readonly navMode = signal(navMode(this.router.routerState.snapshot.root));

  /** The active page takes the full width, without the navigation column. */
  readonly fullWidth = computed(() => {
    const mode = this.navMode();
    return mode === 'never' || (mode === 'xl' && !this.xl());
  });

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
  readonly split = computed(
    () => this.wide() && !this.fullWidth() && (!this.home() || this.homeHasPage()),
  );

  /** The navigation shows: always on the home page, else only as the column. */
  readonly showNav = computed(() => this.home() || (this.wide() && !this.fullWidth()));

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
      .subscribe((e) => {
        this.home.set(pathOf(e.urlAfterRedirects) === HOME);
        this.navMode.set(navMode(this.router.routerState.snapshot.root));
        afterNextRender(() => this.revealActive(), { injector: this.injector });
      });
    afterNextRender(() => this.revealActive());

    // The navigation shows "Verwaltung" beside the page, so the breadcrumbs leave it out.
    effect(() => this.pageFrame.crumbRoot.set(this.split() ? 'admin' : null));
    inject(DestroyRef).onDestroy(() => this.pageFrame.crumbRoot.set(null));
  }

  /**
   * Scroll the column so that the active entry is fully visible. The column only moves
   * when the entry is out of view, and then puts it in the middle, clear of the fades.
   * The method sets `scrollTop` of the column, so the window never scrolls.
   *
   * The active entry comes from the URL, with the prefix match of `routerLinkActive`.
   * `aria-current` is no help here: `RouterLinkActive` sets it in a microtask, after
   * this hook.
   */
  private revealActive(): void {
    if (!this.split()) return;
    const body = this.navBody()?.nativeElement;
    if (!body) return;
    const url = pathOf(this.router.url);
    const link = [...body.querySelectorAll<HTMLAnchorElement>('a.af__item')].find((a) => {
      const href = a.getAttribute('href');
      return !!href && (url === href || url.startsWith(`${href}/`));
    });
    if (!link) return;
    const box = body.getBoundingClientRect();
    const item = link.getBoundingClientRect();
    if (item.top >= box.top && item.bottom <= box.bottom) return;
    const top = item.top - box.top + body.scrollTop;
    body.scrollTop = Math.max(0, top - (body.clientHeight - item.height) / 2);
  }

  /** The full path of an entry. */
  protected path(page: AdminPage): string {
    return `${HOME}/${page.link}`;
  }
}
