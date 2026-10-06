import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  computed,
  inject,
  input,
  model,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { IconComponent, MEDIA, type IconName } from '@stupa-makers/ui-kit';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { mediaQuerySignal } from '../../../layout/media-query';
import { SideSheetComponent } from '../side-sheet/side-sheet.component';

/** One choice of a filter chip. */
export interface FilterSelectOption {
  value: string;
  label: string;
}

let nextId = 0;

/** Space between the list and the edge of the viewport, in px. */
const EDGE = 8;
/** Space between the chip and the list, in px. */
const GAP = 4;
/** Time after the last key press until the type-ahead starts again, in ms. */
const TYPEAHEAD_RESET = 600;

/**
 * A filter chip that opens the app-styled list of its choices. Use it for every filter
 * and toolbar chip; a chip never opens the native list of the browser.
 *
 * - Single choice (default): `[(value)]`. A choice closes the list. A check mark shows
 *   the current value.
 * - Several choices (`multiple`): `[(values)]`. A choice toggles one value and the list
 *   stays open. `resetLabel` adds a button that clears all values.
 * - Desktop: a list under the chip (popover). Phone (< 768 px): the shared bottom sheet.
 * - The whole chip is the button. The chip shows `text`, else the label of the current
 *   value, else `label`.
 * - Keyboard (WAI-ARIA listbox): Enter, Space or Arrow Down open the list on the current
 *   value, Arrow Up on the last choice. In the list the arrows move, Home and End jump,
 *   a typed letter jumps to the next choice that starts with it, Enter and Space choose,
 *   Escape closes and returns to the chip, Tab closes.
 */
@Component({
  selector: 'app-filter-select',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent, NgTemplateOutlet, TranslatePipe, SideSheetComponent],
  templateUrl: './filter-select.component.html',
  styleUrl: './filter-select.component.scss',
})
export class FilterSelectComponent {
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);

  /** The name of the filter: the name of the list and the title of the sheet. */
  readonly label = input.required<string>();
  readonly options = input<readonly FilterSelectOption[]>([]);
  /** Several choices at once. */
  readonly multiple = input(false);
  /** The current value (single choice). */
  readonly value = model('');
  /** The current values (several choices). */
  readonly values = model<readonly string[]>([]);
  /** The text in the chip. Default: the label of the current value, else `label`. */
  readonly text = input<string | null>(null);
  /** The filter is set: the chip shows the selection colour. */
  readonly active = input(false);
  /** An icon in front of the text. */
  readonly icon = input<IconName | null>(null);
  /** The chevron after the text. */
  readonly chevron = input(true);
  /** `sm`: the filter chip (32px). `md`: a pill as high as the search pill `md` (44px). */
  readonly size = input<'sm' | 'md'>('sm');
  /** Several choices: the text of the button that clears all values. No text, no button. */
  readonly resetLabel = input<string | null>(null);
  /** The text when there is no choice. Default: "Keine Auswahl möglich". */
  readonly emptyText = input<string | null>(null);

  /** The list opened. */
  readonly opened = output<void>();

  protected readonly listId = `filter-select-${nextId++}`;
  protected readonly phone = mediaQuerySignal(MEDIA.phone);
  protected readonly open = signal(false);
  protected readonly popoverOpen = computed(() => this.open() && !this.phone());
  protected readonly sheetOpen = computed(() => this.open() && this.phone());
  protected readonly position = signal({ top: 0, left: 0 });

  protected readonly chipText = computed(() => {
    const own = this.text();
    if (own) return own;
    if (!this.multiple()) {
      const hit = this.options().find((o) => o.value === this.value());
      if (hit) return hit.label;
    }
    return this.label();
  });

  /**
   * The name of the chip: its text, with the name of the filter in front when the text
   * does not start with it ("Typ: Förderantrag", but "Archiv: Alle" as it is).
   */
  protected readonly chipName = computed(() => {
    const text = this.chipText();
    return text.startsWith(this.label()) ? text : `${this.label()}: ${text}`;
  });

  /** The option that takes the Tab stop in the list: the first chosen, else the first. */
  protected readonly tabValue = computed(() => {
    const opts = this.options();
    const hit = opts.find((o) => this.isOn(o.value));
    return (hit ?? opts[0])?.value ?? null;
  });

  private readonly trigger = viewChild.required<ElementRef<HTMLButtonElement>>('trigger');
  private readonly list = viewChild<ElementRef<HTMLElement>>('list');
  private readonly layer = viewChild<ElementRef<HTMLElement>>('layer');

  private timer: ReturnType<typeof setTimeout> | null = null;
  private typed = '';
  private typedAt = 0;

  constructor() {
    const inside = (root: HTMLElement | undefined, target: EventTarget | null) =>
      !!root && target instanceof Node && root.contains(target);
    const onPointer = (e: Event) => {
      if (this.popoverOpen() && !inside(this.host.nativeElement, e.target)) this.close(false);
    };
    const onViewport = (e: Event) => {
      // A scroll inside the list itself does not move the chip.
      if (this.popoverOpen() && !inside(this.list()?.nativeElement, e.target)) this.follow();
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

  protected isOn(value: string): boolean {
    return this.multiple() ? this.values().includes(value) : this.value() === value;
  }

  protected toggle(): void {
    if (this.open()) this.close(true);
    else this.show('current');
  }

  protected onTriggerKey(event: KeyboardEvent): void {
    if (event.key === 'Escape' && this.open()) {
      event.preventDefault();
      this.close(true);
      return;
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      const where = event.key === 'ArrowDown' ? 'current' : 'last';
      if (this.open()) this.focusItem(where);
      else this.show(where);
    }
  }

  protected onListKey(event: KeyboardEvent): void {
    const items = this.items();
    const index = items.indexOf(document.activeElement as HTMLElement);
    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault();
        items[Math.min(index + 1, items.length - 1)]?.focus();
        return;
      case 'ArrowUp':
        event.preventDefault();
        items[Math.max(index - 1, 0)]?.focus();
        return;
      case 'Home':
        event.preventDefault();
        items[0]?.focus();
        return;
      case 'End':
        event.preventDefault();
        items[items.length - 1]?.focus();
        return;
    }
    if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
      if (event.key === ' ' && this.typed === '') return; // Space chooses (native click).
      event.preventDefault();
      this.typeAhead(event.key, items, index, Date.now());
    }
  }

  /** Escape and Tab in the popover. The sheet handles both itself (close, focus trap). */
  protected onMenuKey(event: KeyboardEvent): void {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      this.close(true);
    } else if (event.key === 'Tab') {
      this.close(false);
    }
  }

  protected choose(option: FilterSelectOption): void {
    if (this.multiple()) {
      const next = this.values().filter((v) => v !== option.value);
      if (!this.values().includes(option.value)) next.push(option.value);
      this.values.set(next);
      return;
    }
    this.value.set(option.value);
    this.close(true);
  }

  protected reset(): void {
    this.values.set([]);
  }

  /** The sheet closed itself (Escape, scrim, close button). It returns the focus. */
  protected onSheetOpen(open: boolean): void {
    if (!open) this.close(false);
  }

  private show(focus: 'current' | 'last'): void {
    this.open.set(true);
    this.opened.emit();
    if (this.phone()) {
      // The sheet focuses its first control after its render; the current value goes after.
      this.later(() => {
        this.toTopLayer(this.layer()?.nativeElement);
        this.later(() => this.focusItem(focus));
      });
      return;
    }
    this.placeBelow();
    this.later(() => {
      const list = this.list()!.nativeElement;
      this.toTopLayer(list);
      this.fit(list);
      this.focusItem(focus);
    });
  }

  /** Show a popover element. It renders anew on each opening, so it is not shown yet. */
  private toTopLayer(el: HTMLElement | undefined): void {
    const pop = el as (HTMLElement & { showPopover?: () => void }) | undefined;
    if (typeof pop?.showPopover === 'function') pop.showPopover();
  }

  private close(returnFocus: boolean): void {
    if (!this.open()) return;
    this.open.set(false);
    this.clearTimer();
    this.typed = '';
    if (returnFocus) this.trigger().nativeElement.focus();
  }

  private focusItem(focus: 'current' | 'last'): void {
    if (!this.open()) return;
    const items = this.items();
    const target =
      focus === 'last'
        ? items[items.length - 1]
        : (items.find((el) => el.getAttribute('aria-selected') === 'true') ?? items[0]);
    (target ?? (this.popoverOpen() ? this.list()?.nativeElement : undefined))?.focus();
  }

  private typeAhead(key: string, items: HTMLElement[], index: number, now: number): void {
    this.typed = now - this.typedAt > TYPEAHEAD_RESET ? key : this.typed + key;
    this.typedAt = now;
    const needle = this.typed.toLocaleLowerCase();
    // One letter again and again cycles through the choices with that letter.
    const cycle = needle.length > 1 && [...needle].every((c) => c === needle[0]);
    const search = cycle ? needle[0] : needle;
    const start = cycle || needle.length === 1 ? index + 1 : Math.max(index, 0);
    for (let i = 0; i < items.length; i++) {
      const el = items[(start + i) % items.length];
      if ((el.textContent ?? '').trim().toLocaleLowerCase().startsWith(search)) {
        el.focus();
        return;
      }
    }
  }

  /** Under the chip, aligned to its start, inside the viewport. */
  private placeBelow(): void {
    const rect = this.trigger().nativeElement.getBoundingClientRect();
    this.position.set({ top: rect.bottom + GAP, left: Math.max(EDGE, rect.left) });
  }

  /** The page scrolled or resized: keep the list at its chip; close it when the chip leaves. */
  private follow(): void {
    const rect = this.trigger().nativeElement.getBoundingClientRect();
    if (rect.bottom < 0 || rect.top > window.innerHeight) {
      this.close(false);
      return;
    }
    this.placeBelow();
    const list = this.list()?.nativeElement;
    if (list) this.fit(list);
  }

  /** Move the list left when it passes the right edge, and up when it does not fit below. */
  private fit(list: HTMLElement): void {
    const pos = this.position();
    const box = list.getBoundingClientRect();
    let { top, left } = pos;
    if (left + box.width > window.innerWidth - EDGE) {
      left = Math.max(EDGE, window.innerWidth - EDGE - box.width);
    }
    if (top + box.height > window.innerHeight - EDGE) {
      const above = this.trigger().nativeElement.getBoundingClientRect().top - GAP - box.height;
      if (above >= EDGE) top = above;
    }
    if (top !== pos.top || left !== pos.left) this.position.set({ top, left });
  }

  private items(): HTMLElement[] {
    const root = document.getElementById(this.listId);
    return root ? Array.from(root.querySelectorAll<HTMLElement>('[role="option"]')) : [];
  }

  private later(fn: () => void): void {
    this.clearTimer();
    this.timer = setTimeout(() => {
      this.timer = null;
      fn();
    });
  }

  private clearTimer(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
  }
}
