import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { BrandingService } from '@core/branding/branding.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { IconComponent } from '@stupa-makers/ui-kit';
import { CommandPaletteService } from '../../features/search/command-palette.service';
import { searchShortcutKeys } from '../../features/search/shortcut';
import { AccountMenuComponent } from '../account-menu/account-menu.component';
import { NavMarkComponent } from '../nav-mark/nav-mark.component';
import { NavService } from '../nav.service';

/**
 * The navigation rail: 96px at the start edge of every signed-in page above the phone
 * width. The mark leads to the start page. Below it the search opens the palette, so the
 * search is in reach on every page also without a keyboard. Then come the areas the principal may open
 * (RBAC filter in {@link NavService}), a spacer, the administration and the account.
 *
 * The task count and the live mark come from `RailStatusService` through `app-nav-mark`.
 */
@Component({
  selector: 'app-nav-rail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, RouterLinkActive, TranslatePipe, IconComponent, AccountMenuComponent, NavMarkComponent],
  templateUrl: './nav-rail.component.html',
  styleUrl: './nav-rail.component.scss',
})
export class NavRailComponent {
  private readonly nav = inject(NavService);
  readonly branding = inject(BrandingService);
  readonly palette = inject(CommandPaletteService);

  /** The palette shortcut, for `aria-keyshortcuts`. */
  readonly searchKeys = searchShortcutKeys();

  readonly mainItems = computed(() => this.nav.visible().filter((i) => i.place === 'main'));
  readonly endItems = computed(() => this.nav.visible().filter((i) => i.place === 'end'));

  /** The mark without the wordmark: one file for both themes. */
  readonly markSrc = 'assets/logos/stupa-mark.svg';
}
