import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AuthService } from '@core/auth/auth.service';
import { BrandingService } from '@core/branding/branding.service';
import { PrefetchService } from '@core/cache/prefetch.service';
import { I18nService } from '@core/i18n/i18n.service';
import { KeyboardService } from '@core/pwa/keyboard.service';
import {
  CommandPalette,
  NavMarkDirective,
  ShellComponent as KitShellComponent,
  type ShellBrand,
  type ShellFrame,
  type ShellNavItem,
} from '@stupa-makers/ui-kit/shell';
import { HelpMenuComponent } from '../features/help/help-menu/help-menu.component';
import { HelpService } from '../features/help/help.service';
import { ReportDialogComponent } from '../features/help/report-dialog/report-dialog.component';
import { SearchPaletteComponent } from '../features/search/search-palette.component';
import { AppAccountMenuComponent } from './account-menu/account-menu.component';
import { NavMarkComponent } from './nav-mark/nav-mark.component';
import { BOTTOM_BAR_KEYS, NavService } from './nav.service';
import { PublicHeaderComponent } from './public-header/public-header.component';
import { SiteFooterComponent } from './site-footer/site-footer.component';

/**
 * The frame around a page: the `app-shell` of the kit, filled with the parts of STUPA.
 *
 * - The frame follows the session: `pending` until the first answer of `/auth/me`, then
 *   `rail` for a signed-in principal and `public` for nobody. A route with
 *   `chrome: false` (the beamer) gets `bare` from the kit shell.
 * - The rail and the bottom bar show the areas the principal may open
 *   ({@link NavService}), with the task count, the ticket count and the live mark of the
 *   meetings ({@link NavMarkComponent}). Start, Anträge, Sitzungen and Aufgaben sit in the
 *   phone bar; the rest go into "Mehr".
 * - The help menu sits in the rail and in "Mehr", the account menu at the foot of the rail
 *   and at the end of "Mehr". "Mehr" is also active on `/account`.
 * - The public frame has the public header and the branded footer; the rail frame has
 *   the footer only on a route with `footer: true`.
 * - The report dialog shows in every frame, the search palette only in the rail frame. The
 *   update of the app is a toast of `SwUpdateService` (kit), which the app initializer starts.
 *
 * There is ONE router outlet for every frame (in the kit shell), so a change of frame
 * (sign-in, the beamer) never destroys and recreates the page.
 */
@Component({
  selector: 'app-frame',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    KitShellComponent,
    NavMarkDirective,
    NavMarkComponent,
    HelpMenuComponent,
    AppAccountMenuComponent,
    PublicHeaderComponent,
    SiteFooterComponent,
    ReportDialogComponent,
    SearchPaletteComponent,
  ],
  template: `
    <app-shell
      #shell
      [frame]="frame()"
      [nav]="nav()"
      [barKeys]="barKeys"
      [brand]="brand()"
      [keyboardOpen]="keyboard()"
      [morePaths]="morePaths"
      (search)="palette.open()"
    >
      <ng-template appNavMark let-key let-part="part">
        <app-nav-mark [key]="key" [part]="part" />
      </ng-template>

      @if (shell.current() === 'rail') {
        <app-help-menu shellRailTools variant="rail" />
      }
      @if (shell.current() === 'rail') {
        <app-help-menu shellMore variant="sheet" />
      }
      @if (shell.current() === 'rail') {
        <app-account shellAccount variant="auto" />
      }
      @if (shell.current() === 'public') {
        <app-public-header shellPublicHeader />
      }
      <app-site-footer shellFooter />

      @if (help.reportUsed()) {
        <ng-container shellPrompts>
          @defer {
            <app-report-dialog />
          }
        </ng-container>
      }

      @if (shell.current() === 'rail') {
        <app-search-palette shellOverlays />
      }
    </app-shell>
  `,
  styles: `
    :host {
      display: contents;
    }
  `,
})
export class ShellComponent {
  /**
   * Injected for its side effect: it warms the reference-data cache after sign-in. Nothing
   * reads it, because the pages that need the data find it in the cache and must not
   * depend on a prefetch they did not ask for.
   */
  private readonly prefetch = inject(PrefetchService);

  readonly auth = inject(AuthService);
  readonly help = inject(HelpService);
  protected readonly palette = inject(CommandPalette);
  private readonly navService = inject(NavService);
  private readonly branding = inject(BrandingService);
  private readonly i18n = inject(I18nService);

  /** The on-screen keyboard is open: the bottom bar may step aside (styles.scss). */
  readonly keyboard = inject(KeyboardService).open;

  protected readonly barKeys = BOTTOM_BAR_KEYS;
  protected readonly morePaths = ['/account'];

  /** The entries the principal may open, with their labels in the active language. */
  readonly nav = computed<ShellNavItem[]>(() =>
    this.navService.visible().map((item) => ({
      key: item.key,
      path: item.path,
      label: this.i18n.translate(item.labelKey),
      icon: item.icon,
      place: item.place,
      exact: item.exact,
    })),
  );

  /** The mark without the wordmark: the upload of the branding, else the built-in one. */
  readonly brand = computed<ShellBrand>(() => ({
    home: '/dashboard',
    label: this.branding.appName(),
    mark: this.branding.markSrc(),
  }));

  /** The first answer of `/auth/me` arrived (a principal or none). */
  private readonly sessionKnown = signal(false);

  readonly frame = computed<ShellFrame>(() => {
    if (!this.sessionKnown()) return 'pending';
    return this.auth.isAuthenticated() ? 'rail' : 'public';
  });

  /** The app initializer starts the same request, and `ensureLoaded` shares it. */
  constructor() {
    this.auth
      .ensureLoaded()
      .pipe(takeUntilDestroyed())
      .subscribe(() => this.sessionKnown.set(true));
  }
}
