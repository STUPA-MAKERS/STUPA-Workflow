import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { IconComponent, type IconName } from '@stupa-makers/ui-kit';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { SkeletonComponent } from '../skeleton/skeleton.component';

/** One action of a row menu. */
export interface RowMenuItem {
  /** Stable key of the action, for the caller to tell the items apart. */
  id: string;
  label: string;
  icon?: IconName;
  /** A destructive action: red text and icon. */
  danger?: boolean;
  /**
   * Set it to disable the item. The text says why the action is not possible now; it
   * shows as a tooltip and a screen reader reads it as the description of the item.
   */
  disabledReason?: string | null;
  /** Makes the item a checkbox item (for example "Nicht öffentlich") in this state. */
  checked?: boolean;
}

/** A group of items, with an optional caption. A line separates two sections. */
export interface RowMenuSection {
  label?: string | null;
  items: readonly RowMenuItem[];
}

let nextId = 0;

/** Space between the menu and the edge of the viewport, in px. */
const EDGE = 8;
/** Space between the trigger and the menu, in px. */
const GAP = 4;

/**
 * The "more" menu of a row or a header: a button that opens a list of actions.
 *
 * - Sections with an optional caption, a line between them.
 * - A disabled item stays in the list and says why (`disabledReason`): a tooltip, and
 *   `aria-disabled` with the reason as its description.
 * - A destructive item is red.
 * - Lazy content: `opened` fires once per opening. Load the items there and set
 *   `loading` until they arrive; the menu shows a placeholder and moves the focus to the
 *   first item when they are in.
 * - Keyboard (WAI-ARIA menu button): Enter, Space or Arrow Down open the menu on the
 *   first item, Arrow Up on the last. In the menu the arrows move, Home and End jump,
 *   Escape closes and returns to the button, Tab closes.
 *
 * The menu opens in the top layer (popover) where the browser has it, so a table with
 * `overflow: hidden` does not clip it. It follows its button when the page scrolls or
 * resizes, and closes when the button leaves the viewport.
 */
@Component({
  selector: 'app-row-menu',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent, TranslatePipe, SkeletonComponent],
  templateUrl: './row-menu.component.html',
  styleUrl: './row-menu.component.scss',
})
export class RowMenuComponent {
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);

  readonly sections = input<readonly RowMenuSection[]>([]);
  /** The accessible name of the button. Defaults to "Weitere Aktionen". */
  readonly label = input<string | null>(null);
  /** The icon of the button. */
  readonly icon = input<IconName>('more');
  /** The items are still loading (see `opened`). */
  readonly loading = input(false);

  /** The menu opened. Fires once per opening, so it can load the items. */
  readonly opened = output<void>();
  /** The menu closed, with or without a choice. */
  readonly closed = output<void>();
  /** An enabled item was chosen. The menu is closed by then. */
  readonly selected = output<RowMenuItem>();

  protected readonly menuId = `row-menu-${nextId++}`;
  protected readonly open = signal(false);
  protected readonly position = signal({ top: 0, right: 0 });

  /** Sections that hold at least one item. */
  protected readonly visibleSections = computed(() =>
    this.sections().filter((s) => s.items.length > 0),
  );

  private readonly trigger = viewChild.required<ElementRef<HTMLButtonElement>>('trigger');
  private readonly menu = viewChild<ElementRef<HTMLElement>>('menu');

  /** Where the focus goes once the items are rendered. */
  private pendingFocus: 'first' | 'last' | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;

  constructor() {
    // Items that arrive while the menu is open (lazy load) take the pending focus.
    effect(() => {
      this.visibleSections();
      if (this.open() && !this.loading()) this.schedule();
    });

    const inside = (root: HTMLElement | undefined, target: EventTarget | null) =>
      !!root && target instanceof Node && root.contains(target);
    const onPointer = (e: Event) => {
      if (this.open() && !inside(this.host.nativeElement, e.target)) this.close(false);
    };
    const onViewport = (e: Event) => {
      // A scroll inside the menu itself does not move the button.
      if (this.open() && !inside(this.menu()?.nativeElement, e.target)) this.follow();
    };
    document.addEventListener('pointerdown', onPointer, true);
    window.addEventListener('scroll', onViewport, true);
    window.addEventListener('resize', onViewport);
    inject(DestroyRef).onDestroy(() => {
      document.removeEventListener('pointerdown', onPointer, true);
      window.removeEventListener('scroll', onViewport, true);
      window.removeEventListener('resize', onViewport);
      this.clearTimer();
    });
  }

  protected toggle(): void {
    if (this.open()) this.close(true);
    else this.show('first');
  }

  protected onTriggerKey(event: KeyboardEvent): void {
    if (event.key === 'Escape' && this.open()) {
      event.preventDefault();
      this.close(true);
      return;
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      const where = event.key === 'ArrowDown' ? 'first' : 'last';
      if (this.open()) {
        this.pendingFocus = where;
        this.schedule();
      } else {
        this.show(where);
      }
    }
  }

  protected onMenuKey(event: KeyboardEvent): void {
    const items = this.items(event.currentTarget as HTMLElement);
    const index = items.indexOf(document.activeElement as HTMLElement);
    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault();
        items[(index + 1) % items.length]?.focus();
        break;
      case 'ArrowUp':
        event.preventDefault();
        items[(index - 1 + items.length) % items.length]?.focus();
        break;
      case 'Home':
        event.preventDefault();
        items[0]?.focus();
        break;
      case 'End':
        event.preventDefault();
        items[items.length - 1]?.focus();
        break;
      case 'Escape':
        event.preventDefault();
        event.stopPropagation();
        this.close(true);
        break;
      case 'Tab':
        this.close(false);
        break;
    }
  }

  protected choose(item: RowMenuItem): void {
    if (item.disabledReason) return;
    this.close(true);
    this.selected.emit(item);
  }

  private show(focus: 'first' | 'last'): void {
    this.placeBelow();
    this.pendingFocus = focus;
    this.open.set(true);
    this.opened.emit();
    this.schedule();
  }

  private close(returnFocus: boolean): void {
    this.open.set(false);
    this.pendingFocus = null;
    this.clearTimer();
    this.closed.emit();
    if (returnFocus) this.trigger().nativeElement.focus();
  }

  /** After the next render: show the popover, keep it in the viewport, place the focus. */
  private schedule(): void {
    this.clearTimer();
    this.timer = setTimeout(() => {
      this.timer = null;
      // The timer runs only while the menu is open (close clears it), so it is rendered.
      const menu = this.menu()!.nativeElement;
      this.showPopover(menu);
      this.flip(menu);
      const items = this.items(menu);
      if (this.pendingFocus && items.length > 0) {
        (this.pendingFocus === 'first' ? items[0] : items[items.length - 1]).focus();
        this.pendingFocus = null;
      } else if (this.pendingFocus) {
        // Nothing to focus yet (loading, or no action): hold the focus in the menu.
        menu.focus();
      }
    });
  }

  private showPopover(menu: HTMLElement): void {
    const pop = menu as HTMLElement & { showPopover?: () => void };
    if (typeof pop.showPopover === 'function' && !menu.matches(':popover-open')) {
      pop.showPopover();
    }
  }

  /** Open upwards when the menu does not fit below the trigger. */
  private placeBelow(): void {
    const rect = this.trigger().nativeElement.getBoundingClientRect();
    this.position.set({
      top: rect.bottom + GAP,
      right: Math.max(EDGE, window.innerWidth - rect.right),
    });
  }

  /**
   * The page scrolled or resized: keep the menu at its button. A phone resizes when its
   * address bar slides away, so closing here would close the menu as it opens. When the
   * button leaves the viewport, the menu closes.
   */
  private follow(): void {
    const rect = this.trigger().nativeElement.getBoundingClientRect();
    if (rect.bottom < 0 || rect.top > window.innerHeight) {
      this.close(false);
      return;
    }
    this.placeBelow();
    // Right after the opening the menu is not rendered yet; the scheduled step flips it.
    const menu = this.menu()?.nativeElement;
    if (menu) this.flip(menu);
  }

  private flip(menu: HTMLElement): void {
    const pos = this.position();
    const height = menu.getBoundingClientRect().height;
    if (pos.top + height <= window.innerHeight - EDGE) return;
    const above = this.trigger().nativeElement.getBoundingClientRect().top - GAP - height;
    if (above >= EDGE) this.position.set({ ...pos, top: above });
  }

  private items(menu: HTMLElement): HTMLElement[] {
    return Array.from(menu.querySelectorAll<HTMLElement>('[data-menu-item]'));
  }

  private clearTimer(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
  }
}
