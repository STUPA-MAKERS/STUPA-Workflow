import { NgTemplateOutlet } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  HostListener,
  inject,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { RouterLink } from '@angular/router';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { ThemeService } from '@core/theme/theme.service';
import { AvatarComponent, IconComponent, SwitchComponent, TruncatedDirective } from '@stupa-makers/ui-kit';
import { LanguageSelectComponent } from '../language-select/language-select.component';

/**
 * `popover`: the avatar at the foot of the rail, which opens the menu beside the rail.
 * `sheet`: the menu content only, inline in the "Mehr" sheet of the phone bar.
 */
export type AccountMenuVariant = 'popover' | 'sheet';

/** Space between the rail and the popover, and the least distance to the viewport edge. */
const GAP = 8;

let nextId = 0;

/**
 * The account menu: who is signed in, the account pages, language, dark design and
 * sign-out. Language and appearance are settings, not navigation, so they live here at
 * every width.
 *
 * The popover is a disclosure (a button with `aria-expanded` and a panel), not an ARIA
 * menu: it holds a select and a switch, which a `role="menu"` cannot contain. Tab moves
 * through it. Escape closes it and gives the focus back to the avatar. A click outside,
 * focus that leaves it (Tab past the last control) and a resize of the window also close
 * it, so the fixed panel never covers the focused control and never keeps a stale position.
 */
@Component({
  selector: 'app-account-menu',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    TruncatedDirective,
    NgTemplateOutlet,
    RouterLink,
    TranslatePipe,
    IconComponent,
    SwitchComponent,
    AvatarComponent,
    LanguageSelectComponent,
  ],
  templateUrl: './account-menu.component.html',
  styleUrl: './account-menu.component.scss',
})
export class AccountMenuComponent {
  readonly auth = inject(AuthService);
  readonly theme = inject(ThemeService);
  readonly i18n = inject(I18nService);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);

  readonly variant = input<AccountMenuVariant>('popover');

  /** A link was followed: the sheet that holds the inline menu closes. */
  readonly navigated = output<void>();

  readonly open = signal(false);
  /** Fixed position of the popover: beside the rail, bottom-aligned with the avatar. */
  readonly position = signal({ left: 0, bottom: 0 });

  protected readonly panelId = `account-menu-${nextId++}`;
  private readonly trigger = viewChild<ElementRef<HTMLButtonElement>>('trigger');
  private readonly panel = viewChild<ElementRef<HTMLElement>>('panel');

  toggle(): void {
    if (this.open()) this.close();
    else this.show();
  }

  /**
   * The panel renders in this change detection, so its first control gets the focus right after.
   */
  show(): void {
    const trigger = this.trigger()!.nativeElement;
    const rect = trigger.getBoundingClientRect();
    const edge = trigger.closest('nav')?.getBoundingClientRect().right ?? rect.right;
    this.position.set({
      left: edge + GAP,
      bottom: Math.max(GAP, window.innerHeight - rect.bottom),
    });
    this.open.set(true);
    setTimeout(() => this.panel()?.nativeElement.querySelector<HTMLElement>('a, button')?.focus());
  }

  /** Close the popover. `restoreFocus` puts the focus back on the avatar. */
  close(restoreFocus = false): void {
    if (!this.open()) return;
    this.open.set(false);
    if (restoreFocus) this.trigger()?.nativeElement.focus();
  }

  /** A link in the menu was followed. */
  onNavigate(): void {
    this.close();
    this.navigated.emit();
  }

  setDark(dark: boolean): void {
    this.theme.setPreference(dark ? 'dark' : 'light');
  }

  logout(): void {
    this.close();
    this.auth.logout();
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    this.close(true);
  }

  @HostListener('document:pointerdown', ['$event'])
  onPointerDown(event: Event): void {
    if (!this.open()) return;
    if (!this.host.nativeElement.contains(event.target as Node)) this.close();
  }

  /** The focus moved out of the menu: close it, and leave the focus where it went. */
  @HostListener('document:focusin', ['$event'])
  onFocusIn(event: FocusEvent): void {
    if (!this.open()) return;
    if (!this.host.nativeElement.contains(event.target as Node)) this.close();
  }

  /** The popover keeps the position from when it opened; after a resize that is stale. */
  @HostListener('window:resize')
  onResize(): void {
    this.close();
  }
}
