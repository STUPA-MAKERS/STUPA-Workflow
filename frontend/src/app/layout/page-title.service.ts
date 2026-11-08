import { DestroyRef, Injectable, computed, effect, inject, signal } from '@angular/core';
import { Title } from '@angular/platform-browser';
import { type ActivatedRouteSnapshot, type RouterStateSnapshot, TitleStrategy } from '@angular/router';
import { BrandingService } from '@core/branding/branding.service';
import { I18nService } from '@core/i18n/i18n.service';
import type { TranslationKey } from '@core/i18n/translations';
import { PageFrameService } from './page-frame.service';

/** The name of the item that a detail page shows, for the URL it showed it on. */
interface ItemTitle {
  readonly url: string;
  readonly label: string;
  readonly owner: object;
}

/**
 * The document title: `<page title> – <app name>` (WCAG 2.4.2). A screen reader reads it
 * first, and the tab list shows it.
 *
 * It is the `TitleStrategy` of the router, so it reads the route after every navigation:
 * the page title is the `data.title` of the deepest route that has one, in the active
 * language. A detail page names its item instead with {@link pageItemTitle}, or with the
 * label it gives the breadcrumbs (`PageFrameService.crumbLabel`). A name applies only on
 * the URL it was given for, so a stale name never shows on another page.
 * A page without a title shows the app name alone.
 */
@Injectable({ providedIn: 'root' })
export class PageTitleService extends TitleStrategy {
  private readonly i18n = inject(I18nService);
  private readonly branding = inject(BrandingService);
  private readonly title = inject(Title);
  private readonly frame = inject(PageFrameService);

  private readonly url = signal('');
  private readonly routeKey = signal<TranslationKey | null>(null);
  private readonly item = signal<ItemTitle | null>(null);

  /** The title of the page alone, without the app name. */
  readonly page = computed(() => {
    const item = this.item();
    if (item && item.url === this.url()) return item.label;
    const crumb = this.frame.crumbLabel();
    if (crumb && crumb.url === this.url()) return crumb.label;
    const key = this.routeKey();
    return key ? this.i18n.translate(key) : '';
  });

  /** The whole document title. */
  readonly full = computed(() => {
    const app = this.branding.appName();
    const page = this.page();
    return page && page !== app ? `${page} – ${app}` : app;
  });

  constructor() {
    super();
    effect(() => this.title.setTitle(this.full()));
  }

  override updateTitle(snapshot: RouterStateSnapshot): void {
    this.url.set(pathOf(snapshot.url));
    this.routeKey.set(deepestTitle(snapshot.root));
  }

  /** Names the item of the current URL, or clears the name of `owner` with `null`. */
  setItem(owner: object, label: string | null): void {
    if (label) this.item.set({ url: this.url(), label, owner });
    else if (this.item()?.owner === owner) this.item.set(null);
  }
}

/**
 * Names the item of a detail page in the document title (call it in an injection context):
 * the title shows `label()` while it is not empty, and the route title again when the page
 * goes. It does nothing while the router has another title strategy (a test of the page).
 */
export function pageItemTitle(label: () => string | null | undefined): void {
  const titles = inject(TitleStrategy);
  if (!(titles instanceof PageTitleService)) return;
  const owner = {};
  effect(() => titles.setItem(owner, label()?.trim() || null));
  inject(DestroyRef).onDestroy(() => titles.setItem(owner, null));
}

/** The path of a router URL, without the query and the fragment. */
function pathOf(url: string): string {
  return url.split(/[?#]/)[0];
}

function deepestTitle(route: ActivatedRouteSnapshot | null): TranslationKey | null {
  if (!route) return null;
  const own = (route.data['title'] as TranslationKey | undefined) ?? null;
  return deepestTitle(route.firstChild) ?? own;
}
