import { NgTemplateOutlet } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  input,
  signal,
  viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { type ActivatedRouteSnapshot, NavigationEnd, Router, RouterOutlet } from '@angular/router';
import { filter } from 'rxjs';
import { AuthService } from '@core/auth/auth.service';
import { FeatureService } from '@core/features/feature.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import {
  EmptyStateComponent,
  IconComponent,
  ListDetailLayoutComponent,
  ListGroupComponent,
  ListItemComponent,
  PageHeaderComponent,
  ScrollFadeDirective,
  SearchPillComponent,
  StickyBarComponent,
} from '@stupa-makers/ui-kit';
import { injectListDetailPage } from '@stupa-makers/ui-kit/shell';
import { PageFrameService } from '../../../layout/page-frame.service';
import { AdminHealthComponent } from '../admin-health/admin-health.component';
import { FRAME_MODES, type FrameModeKey, type FramePage } from './frame-modes';

/** One group of the list with the pages the principal may open. */
interface NavGroup {
  readonly key: string;
  readonly title: TranslationKey | null;
  readonly pages: readonly FramePage[];
}

/** The path of a URL without the query string and the fragment. */
function pathOf(url: string): string {
  return url.split(/[?#]/)[0];
}

/** The route and its first children down to the deepest active route. */
function routeChain(root: ActivatedRouteSnapshot): readonly ActivatedRouteSnapshot[] {
  return [root, ...(root.firstChild ? routeChain(root.firstChild) : [])];
}

/** The nearest parent path of the active route (`data.parent`), as a URL, or null. */
function parentOf(root: ActivatedRouteSnapshot): string | null {
  const parents = routeChain(root)
    .map((node) => (node.data?.['parent'] as readonly string[] | undefined)?.at(-1))
    .filter((last): last is string => !!last);
  const last = parents.at(-1);
  return last ? `/${last}` : null;
}

/**
 * Verwaltung (`/admin`) and Konto (`/account`): an ordinary list/detail page
 * (`app-list-detail`, spec 001440), the same as the Gremien or the Tickets.
 *
 * - The list is the navigation of the area: the title, "Einstellungen durchsuchen" (filters
 *   the entries by title and description, in the browser), the "Zustand" tiles and the
 *   groups of `ADMIN_GROUPS`. An entry shows only with one of its permissions and while its
 *   feature is on, so the list never leads to the 403 page. The guard and the server stay
 *   authoritative.
 * - Each entry is an `app-list-item` with the icon, the title and the description (001441).
 * - The detail is the child route. On the home path (`/admin`, `/account`) that is the
 *   empty pane ("Keine Seite geöffnet"); one pane at a time the home path shows the list.
 * - The way back of the bar and of a swipe (both from `app-list-detail`) leads to the
 *   parent of the route (`data.parent`, the same target as the breadcrumb), else to the
 *   home path.
 * - Side by side the breadcrumbs leave out "Verwaltung", because the list shows it.
 *
 * The form editor and the flow editor are not children of this page: they take the full
 * width (001442).
 *
 * The area comes from the route data (`frame: 'admin' | 'account'`, `FRAME_MODES`); Konto
 * has no search and no tiles.
 */
@Component({
  selector: 'app-admin-list',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    NgTemplateOutlet,
    AdminHealthComponent,
    EmptyStateComponent,
    IconComponent,
    ListDetailLayoutComponent,
    ListGroupComponent,
    ListItemComponent,
    PageHeaderComponent,
    RouterOutlet,
    ScrollFadeDirective,
    SearchPillComponent,
    StickyBarComponent,
    TranslatePipe,
  ],
  host: { '[class.pane-page]': 'split()' },
  templateUrl: './admin-list.component.html',
  styleUrl: './admin-list.component.scss',
})
export class AdminListComponent {
  private readonly auth = inject(AuthService);
  private readonly features = inject(FeatureService);
  private readonly i18n = inject(I18nService);
  private readonly router = inject(Router);
  private readonly pageFrame = inject(PageFrameService);

  /**
   * The area. The route sets it with `data: { frame: 'admin' }` or `data: { frame:
   * 'account' }`, because the input binding also reads query parameters and only route
   * data wins over them. An unknown or absent value gives Verwaltung.
   */
  readonly frame = input<FrameModeKey>('admin');

  /** The settings of the area. */
  readonly mode = computed(() => FRAME_MODES[this.frame()] ?? FRAME_MODES.admin);

  private readonly layout = viewChild(ListDetailLayoutComponent);
  /** The list and the open page sit side by side. */
  readonly split = injectListDetailPage(this.layout).split;

  /** The path of the open page, without the query string and the fragment. */
  readonly path = signal(pathOf(this.router.url));

  /** The parent of the open page in the breadcrumbs (`data.parent`), else null. */
  private readonly parentPath = signal(parentOf(this.router.routerState.snapshot.root));

  /** The home path of the area is open: no page, the empty detail. */
  readonly home = computed(() => this.path() === this.mode().home);

  /** The text of "Einstellungen durchsuchen". */
  readonly query = signal('');

  /** The groups with the pages the principal may open and the search finds. */
  readonly groups = computed<NavGroup[]>(() => {
    const { groups, pages } = this.mode();
    const q = this.query().trim().toLocaleLowerCase();
    const hit = (p: FramePage): boolean =>
      !q ||
      this.i18n.translate(p.title).toLocaleLowerCase().includes(q) ||
      this.i18n.translate(p.desc).toLocaleLowerCase().includes(q);
    const allowed = (p: FramePage): boolean =>
      (!p.feature || this.features.isOn(p.feature)) &&
      (p.permissions.length === 0 || this.auth.canAny(...p.permissions));
    return groups
      .map((g) => ({
        ...g,
        pages: pages.filter((p) => p.group === g.key && allowed(p) && hit(p)),
      }))
      .filter((g) => g.pages.length > 0);
  });

  constructor() {
    this.router.events
      .pipe(
        filter((e) => e instanceof NavigationEnd),
        takeUntilDestroyed(),
      )
      .subscribe((e) => {
        this.path.set(pathOf(e.urlAfterRedirects));
        this.parentPath.set(parentOf(this.router.routerState.snapshot.root));
      });

    effect(() =>
      this.pageFrame.crumbRoot.set(this.split() ? this.mode().home.replace(/^\//, '') : null),
    );
    inject(DestroyRef).onDestroy(() => this.pageFrame.crumbRoot.set(null));
  }

  /** The full path of an entry. */
  protected linkOf(page: FramePage): string {
    return `${this.mode().home}/${page.link}`;
  }

  /** The entry is the open page, or a page below it. */
  protected isOpen(page: FramePage): boolean {
    const link = this.linkOf(page);
    const path = this.path();
    return path === link || path.startsWith(`${link}/`);
  }

  /** "Zur Liste" or a swipe back: the parent page, else the home path of the area. */
  protected goBack(): void {
    void this.router.navigateByUrl(this.parentPath() ?? this.mode().home);
  }
}
