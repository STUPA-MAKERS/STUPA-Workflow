import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { NavigationEnd, Router, RouterLink, type ActivatedRouteSnapshot } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { filter } from 'rxjs';
import { I18nService } from '@core/i18n/i18n.service';
import type { TranslationKey } from '@core/i18n/translations';

interface Crumb {
  label: string;
  url: string;
}

/**
 * Route-driven breadcrumbs. Resolves the current page (deepest route node with
 * ``data.title``) and — where a route has flat siblings instead of real child
 * routes — prepends the parents declared via ``data.parent`` (a list of paths).
 * No "Home"/dashboard prefix. Shown only when there is a parent level (otherwise
 * the H1 is enough). Styled like the budget crumbs: pill links, ``›`` separators.
 */
@Component({
  selector: 'app-breadcrumbs',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink],
  templateUrl: './breadcrumbs.component.html',
  styleUrl: './breadcrumbs.component.scss',
})
export class BreadcrumbsComponent {
  private readonly router = inject(Router);
  private readonly i18n = inject(I18nService);

  readonly crumbs = signal<Crumb[]>([]);

  /** Path → i18n title key, from the route config (for parent resolution). */
  private titleByPath: Map<string, TranslationKey> | null = null;

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
    this.crumbs.set(this.build());
  }

  private build(): Crumb[] {
    let node: ActivatedRouteSnapshot | null = this.router.routerState.snapshot.root;
    let url = '';
    let current: Crumb | null = null;
    let parents: string[] = [];
    while (node) {
      const seg = node.url.map((s) => s.path).join('/');
      if (seg) url += `/${seg}`;
      const title = node.data?.['title'] as TranslationKey | undefined;
      if (title && url) current = { label: this.tr(title), url };
      const parent = node.data?.['parent'] as string[] | undefined;
      if (parent) parents = parent;
      node = node.firstChild;
    }
    if (!current) return [];
    const out: Crumb[] = [];
    for (const path of parents) {
      const key = this.titleForPath(path);
      if (key) out.push({ label: this.tr(key), url: `/${path}` });
    }
    out.push(current);
    return out;
  }

  /** Look up the title key of a (static) route by its full path. */
  private titleForPath(path: string): TranslationKey | undefined {
    if (!this.titleByPath) {
      const map = new Map<string, TranslationKey>();
      const walk = (routes: typeof this.router.config, prefix: string): void => {
        for (const r of routes ?? []) {
          const full = [prefix, r.path].filter(Boolean).join('/');
          const title = r.data?.['title'] as TranslationKey | undefined;
          if (title) map.set(full, title);
          if (r.children) walk(r.children, full);
        }
      };
      walk(this.router.config, '');
      this.titleByPath = map;
    }
    return this.titleByPath.get(path);
  }

  private tr(key: TranslationKey): string {
    return this.i18n.translate(key);
  }
}
