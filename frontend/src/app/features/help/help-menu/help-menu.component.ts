import { NgTemplateOutlet } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  HostListener,
  Injector,
  afterNextRender,
  computed,
  inject,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { RouterLink } from '@angular/router';
import { AuthService } from '@core/auth/auth.service';
import { BrandingService } from '@core/branding/branding.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import {
  DisplaySettingsService,
  IconComponent,
  MEDIA,
  SideSheetComponent,
  SwitchComponent,
  ThemeService,
  mediaQuery,
  showInTopLayer,
  type DisplaySetting,
  type IconName,
} from '@stupa-makers/ui-kit';
import { HelpService } from '../help.service';

/**
 * `rail`: the entry "Hilfe" at the foot of the navigation rail; the menu opens beside it.
 * `header`: the button "Hilfe" of the public header; the menu opens below it, and on a
 *   phone as the shared bottom sheet, because a popover under a button near the left edge
 *   does not fit beside it.
 * `sheet`: the entries only, inline in the "Mehr" sheet of the phone bar.
 */
export type HelpMenuVariant = 'rail' | 'header' | 'sheet';

/** A switch of the group "Darstellung": `dark` is the theme, the rest are display settings. */
export type DisplayKey = 'dark' | DisplaySetting;

/** The switches of the group "Darstellung", in their order (app spec 000593). */
const DISPLAY_ROWS: readonly {
  readonly key: DisplayKey;
  readonly icon: IconName;
  readonly label: TranslationKey;
}[] = [
  { key: 'dark', icon: 'moon', label: 'help.display.dark' },
  { key: 'contrast', icon: 'half', label: 'help.display.contrast' },
  { key: 'motion', icon: 'play', label: 'help.display.motion' },
  { key: 'transparency', icon: 'square', label: 'help.display.transparency' },
  { key: 'fields', icon: 'edit', label: 'help.display.fields' },
  { key: 'veryHigh', icon: 'palette', label: 'help.display.veryHigh' },
];

/** Space between the trigger and the popover, and the least distance to the viewport edge. */
const GAP = 8;

let nextId = 0;

/**
 * The help menu: "Handbuch im Wiki" (the configured `help.wikiUrl`, a real link in a new
 * tab), "Barrierefreiheit" (the accessibility statement, on every page with and without a
 * login, spec 000496), the group "Darstellung" and "Problem melden", which opens the report
 * dialog.
 *
 * "Darstellung" (specs 000593, 000594) has one switch per display setting: the dark theme,
 * more contrast, less motion, less transparency, highlighted fields and, last, very high
 * contrast. A switch shows the
 * state in effect, which is the system setting until the person sets it. The choice holds
 * in this browser only. "Systemeinstellungen verwenden" removes every choice, the theme
 * included, and shows only while a choice exists. Very high contrast turns every other
 * setting on: their switches show on and are disabled (spec 000606). The menu stays open on a switch, so the
 * person sees the change and can set the next one.
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
  imports: [NgTemplateOutlet, RouterLink, TranslatePipe, IconComponent, SideSheetComponent, SwitchComponent],
  templateUrl: './help-menu.component.html',
  styleUrl: './help-menu.component.scss',
})
export class HelpMenuComponent {
  private readonly auth = inject(AuthService);
  private readonly help = inject(HelpService);
  readonly branding = inject(BrandingService);
  private readonly theme = inject(ThemeService);
  private readonly display = inject(DisplaySettingsService);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);

  readonly variant = input<HelpMenuVariant>('rail');

  /** An entry was used: the sheet that holds the inline menu closes. */
  readonly navigated = output<void>();

  readonly open = signal(false);
  /** The phone sheet of the `header` variant is open. */
  readonly sheetOpen = signal(false);
  private readonly phone = mediaQuery(MEDIA.phone);
  private readonly injector = inject(Injector);
  /** The top-layer box of the phone sheet, so the glass of the header does not clip it. */
  private readonly layer = viewChild<ElementRef<HTMLElement>>('layer');
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

  /**
   * The rows of the group "Darstellung", each with the state in effect. While very high
   * contrast is on, every other row is on and disabled (spec 000606).
   */
  readonly displayRows = computed(() => {
    const effective = this.display.effective();
    const dark = this.theme.resolved() === 'dark';
    const locked = effective.veryHigh;
    return DISPLAY_ROWS.map((row) => ({
      ...row,
      on: row.key === 'dark' ? dark : effective[row.key],
      locked: locked && row.key !== 'veryHigh',
    }));
  });

  /** A switch of the group overrides the system, so "Systemeinstellungen verwenden" shows. */
  readonly hasDisplayChoice = computed(
    () => this.display.hasChoice() || this.theme.preference() !== 'system',
  );

  protected readonly panelId = `help-menu-${nextId++}`;
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
    if (this.variant() === 'header' && this.phone()) {
      this.sheetOpen.set(true);
      afterNextRender(() => showInTopLayer(this.layer()?.nativeElement), {
        injector: this.injector,
      });
      return;
    }
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
      const edge = trigger.closest('nav')?.getBoundingClientRect().right ?? rect.right;
      this.position.set({
        left: edge + GAP,
        right: null,
        top: null,
        bottom: Math.max(GAP, window.innerHeight - rect.bottom),
      });
    }
    this.open.set(true);
    setTimeout(() => this.panel()?.nativeElement.querySelector<HTMLElement>('a, button')?.focus());
  }

  /** Close the popover. `restoreFocus` puts the focus back on the trigger. */
  close(restoreFocus = false): void {
    if (!this.open()) return;
    this.open.set(false);
    if (restoreFocus) this.trigger()?.nativeElement.focus();
  }

  /** Set one switch of the group "Darstellung" for this browser. */
  setDisplay(key: DisplayKey, on: boolean): void {
    if (key === 'dark') this.theme.setPreference(on ? 'dark' : 'light');
    else this.display.set(key, on);
  }

  /** Every switch of the group follows the system again. */
  resetDisplay(): void {
    this.theme.setPreference('system');
    this.display.reset();
  }

  /** The handbook link was followed (it opens in a new tab). */
  onWiki(): void {
    this.close();
    this.sheetOpen.set(false);
    this.navigated.emit();
  }

  /** The statement link was followed: the menu closes. */
  onStatement(): void {
    this.close();
    this.sheetOpen.set(false);
    this.navigated.emit();
  }

  /**
   * Open the report dialog. The focus goes to the trigger first, because the dialog stores the
   * active element to restore on close, and the popover button is gone by then.
   */
  report(): void {
    this.close(true);
    this.sheetOpen.set(false);
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
