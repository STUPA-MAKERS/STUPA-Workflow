import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterLink, RouterLinkActive } from '@angular/router';
import { filter } from 'rxjs';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { SideSheetComponent } from '@shared/ui';
import { IconComponent } from '@stupa-makers/ui-kit';
import { CommandPaletteService } from '../../features/search/command-palette.service';
import { AccountMenuComponent } from '../account-menu/account-menu.component';
import { NavMarkComponent } from '../nav-mark/nav-mark.component';
import { BOTTOM_BAR_KEYS, NavService, type NavItem } from '../nav.service';

/**
 * The phone navigation (viewport <= 768px): Start, Anträge, Sitzungen and Aufgaben, then
 * "Mehr". "Mehr" opens a bottom sheet with the other areas the principal may open, the
 * search and the account menu. It replaces the hamburger drawer of the old header.
 *
 * The shell shows the bar only under the phone media query (`MEDIA.phone`).
 */
@Component({
  selector: 'app-bottom-bar',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    RouterLinkActive,
    TranslatePipe,
    IconComponent,
    SideSheetComponent,
    AccountMenuComponent,
    NavMarkComponent,
  ],
  templateUrl: './bottom-bar.component.html',
  styleUrl: './bottom-bar.component.scss',
})
export class BottomBarComponent {
  private readonly nav = inject(NavService);
  private readonly palette = inject(CommandPaletteService);
  private readonly router = inject(Router);

  readonly moreOpen = signal(false);
  private readonly url = signal(this.router.url);

  /** The bar entries, in bar order, that the principal may open. */
  readonly barItems = computed<NavItem[]>(() => {
    const visible = this.nav.visible();
    return BOTTOM_BAR_KEYS.map((key) => visible.find((i) => i.key === key)).filter(
      (i): i is NavItem => !!i,
    );
  });

  /** The other visible entries, in rail order: they go into the "Mehr" sheet. */
  readonly moreItems = computed<NavItem[]>(() =>
    this.nav.visible().filter((i) => !BOTTOM_BAR_KEYS.includes(i.key)),
  );

  /** "Mehr" is the active entry while the page belongs to one of its areas or the account. */
  readonly moreActive = computed(() => {
    const path = this.url().split(/[?#]/)[0];
    const inside = (base: string): boolean => path === base || path.startsWith(`${base}/`);
    return inside('/account') || this.moreItems().some((i) => inside(i.path));
  });

  constructor() {
    this.router.events
      .pipe(
        filter((e): e is NavigationEnd => e instanceof NavigationEnd),
        takeUntilDestroyed(),
      )
      .subscribe((e) => {
        this.url.set(e.urlAfterRedirects);
        this.moreOpen.set(false);
      });
  }

  openMore(): void {
    this.moreOpen.set(true);
  }

  closeMore(): void {
    this.moreOpen.set(false);
  }

  search(): void {
    this.moreOpen.set(false);
    this.palette.open();
  }
}
