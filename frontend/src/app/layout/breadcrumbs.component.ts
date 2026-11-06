import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import {
  NavigationEnd,
  Router,
  RouterLink,
  type ActivatedRouteSnapshot,
  type Routes,
} from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { filter } from 'rxjs';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { IconComponent, TruncatedDirective } from '@stupa-makers/ui-kit';
import type { TranslationKey } from '@core/i18n/translations';
import { PageFrameService } from './page-frame.service';

interface Crumb {
  readonly label: string;
  readonly url: string;
}

/** A route node of the active chain and the URL up to it. */
interface RouteStep {
  readonly node: ActivatedRouteSnapshot;
  readonly url: string;
}

/** The active route nodes from `node` down the first-child chain, each with its URL. */
function routeSteps(node: ActivatedRouteSnapshot | null, prefix = ''): readonly RouteStep[] {
  if (!node) return [];
  const seg = node.url.map((s) => s.path).join('/');
  const url = seg ? `${prefix}/${seg}` : prefix;
  return [{ node, url }, ...routeSteps(node.firstChild, url)];
}

/** The title key of every static route with a title, by its full path. */
function routeTitles(
  routes: Routes | undefined,
  prefix: string,
): readonly (readonly [string, TranslationKey])[] {
  return (routes ?? []).flatMap((r) => {
    const full = [prefix, r.path].filter(Boolean).join('/');
    const title = r.data?.['title'] as TranslationKey | undefined;
    const own = title ? [[full, title] as const] : [];
    return [...own, ...(r.children ? routeTitles(r.children, full) : [])];
  });
}

/**
 * Route-driven breadcrumbs.
 *
 * The component takes the current page from the deepest route node with
 * `data.title`. Where a route has flat siblings instead of real child routes, it
 * prepends the parents declared in `data.parent`, a list of paths. There is no
 * "Home" or dashboard prefix. The bar appears only when a parent level exists,
 * because the H1 is otherwise enough. The parents are accent links with a chevron
 * between them; the current page is muted text with `aria-current`.
 */
@Component({
  selector: 'app-breadcrumbs',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TruncatedDirective, RouterLink, TranslatePipe, IconComponent],
  templateUrl: './breadcrumbs.component.html',
  styleUrl: './breadcrumbs.component.scss',
})
export class BreadcrumbsComponent {
  private readonly router = inject(Router);
  private readonly i18n = inject(I18nService);
  private readonly frame = inject(PageFrameService);

  /** The crumbs of the route, the parent that a frame shows included. */
  private readonly all = signal<readonly Crumb[]>([]);

  /**
   * The crumbs to show. A parent that the frame around the page shows already is left
   * out: the root of the frame and every page below it (the admin navigation shows
   * "Verwaltung" and marks "Gremien" on a gremium sub-page), so every page in the frame
   * starts its title at the same place. A label that the page gives for its own URL
   * replaces the label of the current crumb.
   */
  readonly crumbs = computed<readonly Crumb[]>(() => {
    const root = this.frame.crumbRoot();
    const own = this.frame.crumbLabel();
    const all = this.all();
    const last = all.at(-1);
    const list =
      own && last && own.url === last.url
        ? [...all.slice(0, -1), { ...last, label: own.label }]
        : all;
    if (!root) return list;
    const inFrame = (url: string): boolean => url === `/${root}` || url.startsWith(`/${root}/`);
    return list.filter((c, i) => i === list.length - 1 || !inFrame(c.url));
  });

  /** Path to i18n title key, taken from the route config to resolve parents. */
  private titleByPath: ReadonlyMap<string, TranslationKey> | null = null;

  constructor() {
    this.router.events
      .pipe(
        filter((e): e is NavigationEnd => e instanceof NavigationEnd),
        takeUntilDestroyed(),
      )
      .subscribe(() => this.refresh());
    this.refresh();
  }

  private refresh(): void {
    this.all.set(this.build());
  }

  private build(): readonly Crumb[] {
    const steps = routeSteps(this.router.routerState.snapshot.root);
    const titleOf = (s: RouteStep) => s.node.data?.['title'] as TranslationKey | undefined;
    const current = steps.filter((s) => titleOf(s) && s.url).at(-1);
    if (!current) return [];
    const parents =
      steps
        .map((s) => s.node.data?.['parent'] as readonly string[] | undefined)
        .filter((p): p is readonly string[] => !!p)
        .at(-1) ?? [];
    const parentCrumbs = parents.flatMap((path) => {
      const key = this.titleForPath(path);
      return key ? [{ label: this.tr(key), url: `/${path}` }] : [];
    });
    return [
      ...parentCrumbs,
      { label: this.tr(titleOf(current) as TranslationKey), url: current.url },
    ];
  }

  /** Return the title key of a static route, found by its full path. */
  private titleForPath(path: string): TranslationKey | undefined {
    this.titleByPath ??= new Map(routeTitles(this.router.config, ''));
    return this.titleByPath.get(path);
  }

  private tr(key: TranslationKey): string {
    return this.i18n.translate(key);
  }
}
