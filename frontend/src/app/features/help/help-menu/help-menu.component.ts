import { NgTemplateOutlet } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  HostListener,
  computed,
  inject,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { AuthService } from '@core/auth/auth.service';
import { BrandingService } from '@core/branding/branding.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { IconComponent } from '@stupa-makers/ui-kit';
import { HelpService } from '../help.service';

/**
 * `rail`: the entry "Hilfe" at the foot of the navigation rail; the menu opens beside it.
 * `header`: the button "Hilfe" of the public header; the menu opens below it.
 * `sheet`: the entries only, inline in the "Mehr" sheet of the phone bar.
 */
export type HelpMenuVariant = 'rail' | 'header' | 'sheet';

/** Space between the trigger and the popover, and the least distance to the viewport edge. */
const GAP = 8;

let nextId = 0;

/**
 * The help menu: "Handbuch im Wiki" (the configured `help.wikiUrl`, a real link in a new
 * tab) and "Problem melden", which opens the report dialog.
 *
 * A signed-in person always gets "Problem melden". A visitor gets it only while the
 * admin allows tickets without an account (`tickets.publicEnabled`).
 *
 * Like the account menu, the popover is a disclosure, not an ARIA menu. Escape closes it
 * and gives the focus back to the trigger. A press outside, a focus that leaves it and a
 * resize close it too.
 */
@Component({
  selector: 'app-help-menu',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [NgTemplateOutlet, TranslatePipe, IconComponent],
  templateUrl: './help-menu.component.html',
  styleUrl: './help-menu.component.scss',
})
export class HelpMenuComponent {
  private readonly auth = inject(AuthService);
  private readonly help = inject(HelpService);
  readonly branding = inject(BrandingService);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);

  readonly variant = input<HelpMenuVariant>('rail');

  /** An entry was used: the sheet that holds the inline menu closes. */
  readonly navigated = output<void>();

  readonly open = signal(false);
  /** Fixed position of the popover. */
  readonly position = signal<{ left: number | null; right: number | null; top: number | null; bottom: number | null }>({
    left: null,
    right: null,
    top: null,
    bottom: null,
  });

  /** "Problem melden" shows with a session, or for a visitor while the admin allows it. */
  readonly canReport = computed(() => this.auth.isAuthenticated() || this.branding.ticketsPublic());

  /** The link without the scheme, as the second line: it wraps, it is never cut. */
  readonly wikiLabel = computed(() => this.branding.wikiUrl().replace(/^https?:\/\//, ''));

  protected readonly panelId = `help-menu-${nextId++}`;
  private readonly trigger = viewChild<ElementRef<HTMLButtonElement>>('trigger');
  private readonly panel = viewChild<ElementRef<HTMLElement>>('panel');

  toggle(): void {
    if (this.open()) this.close();
    else this.show();
  }

  show(): void {
    // Only the popover variants have a trigger, and only the trigger calls this.
    const trigger = this.trigger()!.nativeElement;
    const rect = trigger.getBoundingClientRect();
    if (this.variant() === 'header') {
      this.position.set({
        left: null,
        right: Math.max(GAP, window.innerWidth - rect.right),
        top: rect.bottom + GAP,
        bottom: null,
      });
    } else {
      // Beside the navigation that holds the trigger, bottom-aligned with it.
      const edge = trigger.closest('nav')?.getBoundingClientRect().right ?? rect.right;
      this.position.set({
        left: edge + GAP,
        right: null,
        top: null,
        bottom: Math.max(GAP, window.innerHeight - rect.bottom),
      });
    }
    this.open.set(true);
    // The panel renders in this change detection; focus its first control right after.
    setTimeout(() => this.panel()?.nativeElement.querySelector<HTMLElement>('a, button')?.focus());
  }

  /** Close the popover. `restoreFocus` puts the focus back on the trigger. */
  close(restoreFocus = false): void {
    if (!this.open()) return;
    this.open.set(false);
    if (restoreFocus) this.trigger()?.nativeElement.focus();
  }

  /** The handbook link was followed (it opens in a new tab). */
  onWiki(): void {
    this.close();
    this.navigated.emit();
  }

  /**
   * Open the report dialog. The focus goes to the trigger first, because the dialog stores the
   * active element to restore on close, and the popover button is gone by then.
   */
  report(): void {
    this.close(true);
    this.navigated.emit();
    this.help.openReport();
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

  @HostListener('document:focusin', ['$event'])
  onFocusIn(event: FocusEvent): void {
    if (!this.open()) return;
    if (!this.host.nativeElement.contains(event.target as Node)) this.close();
  }

  @HostListener('window:resize')
  onResize(): void {
    this.close();
  }
}
