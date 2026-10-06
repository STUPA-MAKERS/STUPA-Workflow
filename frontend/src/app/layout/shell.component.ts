import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, NavigationEnd, Router, RouterOutlet } from '@angular/router';
import { filter } from 'rxjs';
import { AuthService } from '@core/auth/auth.service';
import { PrefetchService } from '@core/cache/prefetch.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { LoadingOverlayComponent, MEDIA, ToastComponent } from '@stupa-makers/ui-kit';
import { CommandPaletteComponent } from '../features/search/command-palette.component';
import { BottomBarComponent } from './bottom-bar/bottom-bar.component';
import { mediaQuerySignal } from './media-query';
import { NavRailComponent } from './nav-rail/nav-rail.component';
import { PageFrameService } from './page-frame.service';
import { PublicHeaderComponent } from './public-header/public-header.component';
import { SiteFooterComponent } from './site-footer/site-footer.component';

/**
 * The frame around a page.
 *
 * - `rail`: a signed-in principal. The navigation rail at the start edge, or the bottom
 *   bar on a phone. The branded footer shows only on a route with `footer: true` (the
 *   start page and the public pages).
 * - `public`: nobody signed in. The public top bar and the branded footer, always.
 * - `bare`: route data `chrome: false` (the beamer). Only the page.
 * - `pending`: the session is not known yet. Only the page, so no frame flashes up
 *   and changes a moment later.
 */
export type ShellFrame = 'rail' | 'public' | 'bare' | 'pending';

/**
 * App frame: the chrome around the router outlet, the toasts, the loading overlay and
 * the search palette.
 *
 * There is ONE router outlet for every frame. The frame only adds or removes the chrome
 * around it, so a change of frame (sign-in, the beamer) never destroys and recreates the
 * page.
 */
@Component({
  selector: 'app-shell',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterOutlet,
    TranslatePipe,
    ToastComponent,
    LoadingOverlayComponent,
    CommandPaletteComponent,
    NavRailComponent,
    BottomBarComponent,
    PublicHeaderComponent,
    SiteFooterComponent,
  ],
  templateUrl: './shell.component.html',
  styleUrl: './shell.component.scss',
})
export class ShellComponent {
  // Injected for its side effect: it warms the reference-data cache after sign-in.
  // Nothing reads it, and that is the point — the pages that need the data find it
  // in the cache rather than being coupled to a prefetch they did not ask for.
  private readonly prefetch = inject(PrefetchService);

  readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  /** The page fills the viewport (see `PageFrameService`): no footer, a small foot gap. */
  readonly fill = inject(PageFrameService).fill;

  /**
   * Route data `footer: true`: the branded footer (copyright, Impressum, Datenschutz)
   * shows at the end of the page. Only the start page and the public pages have it. A
   * work page (a list, a list with a detail, a meeting, the administration) has no
   * footer, so a page that fills the viewport ends at the bottom edge of the window.
   */
  private readonly footerRoute = signal(false);

  /** The footer shows: always in the public frame, else only where the route asks for it. */
  readonly footer = computed(() => {
    const frame = this.frame();
    if (frame === 'public') return true;
    return frame === 'rail' && this.footerRoute() && !this.fill();
  });

  /** The viewport is a phone (<= 768px): bottom bar instead of the rail. */
  readonly phone = mediaQuerySignal(MEDIA.phone);

  /** Full-width content from route data `wide`, for example the budget tab with two sidebars. */
  readonly wide = signal(false);
  /**
   * Route data `fab: true`: on a phone the page shows a floating action button above the
   * bottom bar (the start page). The frame then keeps the foot of the body free for it, so
   * the button never covers the footer and its legal links.
   */
  readonly fab = signal(false);
  /** Route data `chrome: false` turns the frame off, for example for the beamer. */
  private readonly chrome = signal(true);
  /** The first answer of `/auth/me` arrived (a principal or none). */
  private readonly sessionKnown = signal(false);

  readonly frame = computed<ShellFrame>(() => {
    if (!this.chrome()) return 'bare';
    if (!this.sessionKnown()) return 'pending';
    return this.auth.isAuthenticated() ? 'rail' : 'public';
  });

  constructor() {
    // The app initializer starts the same request; `ensureLoaded` shares it.
    this.auth
      .ensureLoaded()
      .pipe(takeUntilDestroyed())
      .subscribe(() => this.sessionKnown.set(true));

    // `wide`, `fab`, `footer` and `chrome` come from the route data. The deepest active route wins.
    this.router.events
      .pipe(
        filter((e) => e instanceof NavigationEnd),
        takeUntilDestroyed(),
      )
      .subscribe(() => {
        let r = this.route.firstChild;
        let wide = false;
        let fab = false;
        let footer = false;
        let chrome = true;
        while (r) {
          wide = r.snapshot.data['wide'] === true || wide;
          fab = r.snapshot.data['fab'] === true || fab;
          footer = r.snapshot.data['footer'] === true || footer;
          if (r.snapshot.data['chrome'] === false) chrome = false;
          r = r.firstChild;
        }
        this.wide.set(wide);
        this.fab.set(fab);
        this.footerRoute.set(footer);
        this.chrome.set(chrome);
      });
  }
}
