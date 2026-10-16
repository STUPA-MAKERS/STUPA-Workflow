import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  booleanAttribute,
  computed,
  effect,
  inject,
  input,
  model,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { NG_VALUE_ACCESSOR, type ControlValueAccessor } from '@angular/forms';
import { IconComponent, MEDIA } from '@stupa-makers/ui-kit';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { mediaQuerySignal } from '../../../layout/media-query';
import { SideSheetComponent } from '../side-sheet/side-sheet.component';

/** One choice of {@link SelectFieldComponent}. The shape of the ui-kit `SelectOption`. */
export interface SelectFieldOption {
  value: string;
  label: string;
  disabled?: boolean;
  /** The heading of the group. Consecutive options with the same group form one group. */
  group?: string;
}

/** One row of the list: an option, or the placeholder row that clears the value. */
interface Row {
  value: string;
  label: string;
  disabled: boolean;
  placeholder: boolean;
  index: number;
}

/** Consecutive rows with the same group (or none). */
interface Section {
  group: string | null;
  rows: Row[];
}

let nextId = 0;

/** Space between the list and the edge of the viewport, in px. */
const EDGE = 8;
/** Space between the field and the list, in px. */
const GAP = 4;
/** The list is never higher than this, in px (24rem). */
const MAX_HEIGHT = 384;
/** Time after the last key press until the type-ahead starts again, in ms. */
const TYPEAHEAD_RESET = 600;
/** Rows that Page Up and Page Down move. */
const PAGE = 10;

/**
 * The select field of the app: a filled field (the look of `app-input`) with a chevron
 * that opens the app's option list, never the native list of the browser. It replaces
 * the ui-kit `app-select` with the same inputs, so a template keeps its bindings.
 *
 * - Value: `ControlValueAccessor` (`ngModel`, `formControl`) or `[(value)]` with a signal.
 *   A choice reports a change only when the value changes, like the native `change`.
 * - `placeholder`: the text while no option is chosen. While the field is not `required`
 *   and `clearable`, the list starts with a row of this text that clears the value.
 * - Desktop: a popover under the field, at least as wide as the field, in the top layer,
 *   so a dialog, a sheet or a scrolling container does not clip it. It flips above the
 *   field when the room below is too small. Phone (< 768 px): the shared bottom sheet.
 * - ARIA: the field is a `combobox` with a `listbox` popup. On a desktop the focus stays
 *   on the field and `aria-activedescendant` names the active option; in the sheet the
 *   listbox takes the focus.
 * - Keyboard: Arrow Down/Up, Enter, Space, Home, End and a typed letter open the list.
 *   In the list the arrows, Page Up/Down, Home and End move, a typed text jumps to the
 *   next option that starts with it, Enter and Space choose, Escape closes without a
 *   choice, Tab closes and moves on. Disabled options are skipped.
 */
@Component({
  selector: 'app-select',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent, NgTemplateOutlet, SideSheetComponent, TranslatePipe],
  providers: [{ provide: NG_VALUE_ACCESSOR, useExisting: SelectFieldComponent, multi: true }],
  templateUrl: './select.component.html',
  styleUrl: './select.component.scss',
})
export class SelectFieldComponent implements ControlValueAccessor {
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);

  /** The visible label inside the field. */
  readonly label = input('');
  /** The accessible name when the field has no visible label. */
  readonly ariaLabel = input('');
  readonly placeholder = input('');
  readonly hint = input('');
  /** An error text: the field shows the error state and the text below it. */
  readonly error = input('');
  readonly required = input(false, { transform: booleanAttribute });
  /** The placeholder row in the list clears the value (only while not `required`). */
  readonly clearable = input(true, { transform: booleanAttribute });
  readonly disabled = input(false, { transform: booleanAttribute });
  readonly options = input<readonly SelectFieldOption[]>([]);
  readonly id = input(`app-select-${nextId++}`);
  /** The chosen value. Two-way for a signal; a form control writes it too. */
  readonly value = model('');

  protected readonly phone = mediaQuerySignal(MEDIA.phone);
  protected readonly open = signal(false);
  protected readonly popoverOpen = computed(() => this.open() && !this.phone());
  protected readonly sheetOpen = computed(() => this.open() && this.phone());
  /** The index of the active row (the visual focus in the list), or -1. */
  protected readonly active = signal(-1);
  protected readonly position = signal({ top: 0, left: 0, width: 0, maxHeight: MAX_HEIGHT });
  /** The keyboard moved the active row last: it shows; after a pointer move it does not. */
  protected readonly viaKeys = signal(false);
  /** The popover has its place: before that it stays invisible. */
  protected readonly placed = signal(false);

  private readonly formDisabled = signal(false);
  protected readonly isDisabled = computed(() => this.disabled() || this.formDisabled());

  protected readonly listId = computed(() => `${this.id()}-list`);
  protected readonly labelId = computed(() => `${this.id()}-label`);

  protected readonly rows = computed<Row[]>(() => {
    const rows: Row[] = [];
    const text = this.placeholder();
    if (text && this.clearable() && !this.required()) {
      rows.push({ value: '', label: text, disabled: false, placeholder: true, index: 0 });
    }
    for (const opt of this.options()) {
      rows.push({
        value: opt.value,
        label: opt.label,
        disabled: !!opt.disabled,
        placeholder: false,
        index: rows.length,
      });
    }
    return rows;
  });

  protected readonly sections = computed<Section[]>(() => {
    const groups = this.options().map((o) => o.group ?? null);
    const offset = this.rows().length - groups.length;
    const sections: Section[] = [];
    this.rows().forEach((row, i) => {
      const group = i < offset ? null : groups[i - offset];
      const last = sections[sections.length - 1];
      if (last && last.group === group) last.rows.push(row);
      else sections.push({ group, rows: [row] });
    });
    return sections;
  });

  /** The option of the current value, if there is one. */
  protected readonly chosen = computed(
    () => this.options().find((o) => o.value === this.value()) ?? null,
  );

  /** The text in the field: the chosen label, else the placeholder. */
  protected readonly display = computed(() => this.chosen()?.label ?? this.placeholder());

  protected readonly activeId = computed(() => {
    const i = this.active();
    return this.open() && i >= 0 ? this.optionId(i) : null;
  });

  /** The name of the list and the title of the sheet. */
  protected readonly heading = computed(
    () => this.label() || this.ariaLabel() || this.placeholder(),
  );

  private readonly trigger = viewChild.required<ElementRef<HTMLButtonElement>>('trigger');
  private readonly box = viewChild.required<ElementRef<HTMLElement>>('box');
  private readonly menu = viewChild<ElementRef<HTMLElement>>('menu');
  private readonly layer = viewChild<ElementRef<HTMLElement>>('layer');

  private onChange: (value: string) => void = () => undefined;
  private onTouched: () => void = () => undefined;
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
      // A scroll inside the list itself does not move the field.
      if (this.popoverOpen() && !inside(this.menu()?.nativeElement, e.target)) this.follow();
    };
    // A resize across the phone limit swaps the popover and the sheet: close the list,
    // so no list stays open that never reached the top layer.
    effect(() => {
      this.phone();
      untracked(() => this.close(false));
    });
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

  // --- ControlValueAccessor ---------------------------------------------------------

  writeValue(value: string | null): void {
    this.value.set(value ?? '');
  }
  registerOnChange(fn: (value: string) => void): void {
    this.onChange = fn;
  }
  registerOnTouched(fn: () => void): void {
    this.onTouched = fn;
  }
  setDisabledState(isDisabled: boolean): void {
    this.formDisabled.set(isDisabled);
    if (isDisabled) this.close(false);
  }

  // --- Template ---------------------------------------------------------------------

  protected optionId(index: number): string {
    return `${this.id()}-opt-${index}`;
  }

  protected groupId(index: number): string {
    return `${this.id()}-grp-${index}`;
  }

  protected isChosen(row: Row): boolean {
    // The placeholder row is the choice while the value matches no option.
    return row.placeholder ? !this.chosen() : row.value === this.value();
  }

  protected toggle(): void {
    if (this.isDisabled()) return;
    if (this.open()) this.close(true);
    else this.show(this.startIndex(), false);
  }

  protected onBlur(): void {
    // While the list is open the field is still in use; the close marks it touched.
    if (!this.open()) this.onTouched();
  }

  /** Keys on the field: open the list, and on a desktop move in it. */
  protected onTriggerKey(event: KeyboardEvent): void {
    if (this.isDisabled()) return;
    if (!this.open()) {
      this.onClosedKey(event);
      return;
    }
    this.onOpenKey(event);
  }

  /**
   * A button activates on the keyup of Space (Firefox does so even after a prevented
   * keydown), so the click would toggle the list right back. The keydown handles Space.
   */
  protected onTriggerKeyUp(event: KeyboardEvent): void {
    if (event.key === ' ') event.preventDefault();
  }

  /** Keys on the listbox in the phone sheet. Escape and Tab belong to the sheet. */
  protected onSheetKey(event: KeyboardEvent): void {
    if (event.key === 'Escape' || event.key === 'Tab') return;
    this.onOpenKey(event);
  }

  protected pick(row: Row): void {
    if (row.disabled) return;
    this.commit(row.value);
    this.close(true);
  }

  protected hover(row: Row): void {
    this.viaKeys.set(false);
    if (!row.disabled && this.active() !== row.index) this.active.set(row.index);
  }

  /** The sheet closed itself (Escape, scrim, close button). It returns the focus. */
  protected onSheetOpen(open: boolean): void {
    if (!open) this.close(false);
  }

  // --- Keys -------------------------------------------------------------------------

  private onClosedKey(event: KeyboardEvent): void {
    const rows = this.rows();
    switch (event.key) {
      case 'ArrowDown':
      case 'ArrowUp':
      case 'Enter':
      case ' ':
        event.preventDefault();
        this.show(this.startIndex());
        return;
      case 'Home':
        event.preventDefault();
        this.show(this.step(-1, 1));
        return;
      case 'End':
        event.preventDefault();
        this.show(this.step(rows.length, -1));
        return;
    }
    if (this.printable(event)) {
      event.preventDefault();
      const hit = this.typeAhead(event.key, this.startIndex(), Date.now());
      this.show(hit >= 0 ? hit : this.startIndex());
    }
  }

  private onOpenKey(event: KeyboardEvent): void {
    const rows = this.rows();
    const i = this.active();
    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault();
        if (event.altKey) return;
        this.moveTo(this.step(i, 1));
        return;
      case 'ArrowUp':
        event.preventDefault();
        if (event.altKey) {
          this.pickActive();
          return;
        }
        this.moveTo(this.step(i, -1));
        return;
      case 'PageDown':
        event.preventDefault();
        this.moveTo(this.step(Math.min(i + PAGE - 1, rows.length - 1), 1, true));
        return;
      case 'PageUp':
        event.preventDefault();
        this.moveTo(this.step(Math.max(i - PAGE + 1, 0), -1, true));
        return;
      case 'Home':
        event.preventDefault();
        this.moveTo(this.step(-1, 1));
        return;
      case 'End':
        event.preventDefault();
        this.moveTo(this.step(rows.length, -1));
        return;
      case 'Enter':
        event.preventDefault();
        this.pickActive();
        return;
      case 'Escape':
        // The field takes the Escape: a dialog or a sheet around it stays open.
        event.preventDefault();
        event.stopPropagation();
        this.close(true);
        return;
      case 'Tab':
        this.close(false);
        return;
    }
    if (event.key === ' ' && !this.typing(Date.now())) {
      event.preventDefault();
      this.pickActive();
      return;
    }
    if (this.printable(event)) {
      event.preventDefault();
      const hit = this.typeAhead(event.key, i, Date.now());
      if (hit >= 0) this.moveTo(hit);
    }
  }

  private printable(event: KeyboardEvent): boolean {
    return event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey;
  }

  /**
   * The next enabled row from `from` in direction `dir`. `inclusive` checks `from` itself
   * first. Without one, the row stays where it is.
   */
  private step(from: number, dir: 1 | -1, inclusive = false): number {
    const rows = this.rows();
    for (let i = inclusive ? from : from + dir; i >= 0 && i < rows.length; i += dir) {
      if (!rows[i].disabled) return i;
    }
    if (inclusive) return this.step(from, dir === 1 ? -1 : 1);
    return from >= 0 && from < rows.length ? from : -1;
  }

  /** The row that opens active: the chosen one (or the placeholder row), else the first enabled one. */
  private startIndex(): number {
    const rows = this.rows();
    const hit = rows.findIndex((r) => !r.disabled && this.isChosen(r));
    return hit >= 0 ? hit : this.step(-1, 1);
  }

  /** A type-ahead text is still in progress: a Space then belongs to it. */
  private typing(now: number): boolean {
    return this.typed !== '' && now - this.typedAt <= TYPEAHEAD_RESET;
  }

  private typeAhead(key: string, index: number, now: number): number {
    this.typed = now - this.typedAt > TYPEAHEAD_RESET ? key : this.typed + key;
    this.typedAt = now;
    const needle = this.typed.toLocaleLowerCase();
    // One letter again and again cycles through the options with that letter.
    const cycle = needle.length > 1 && [...needle].every((c) => c === needle[0]);
    const search = cycle ? needle[0] : needle;
    const rows = this.rows();
    const start = cycle || needle.length === 1 ? index + 1 : Math.max(index, 0);
    for (let n = 0; n < rows.length; n++) {
      const row = rows[(start + n) % rows.length];
      if (!row.disabled && !row.placeholder && row.label.toLocaleLowerCase().startsWith(search)) {
        return row.index;
      }
    }
    return -1;
  }

  private moveTo(index: number): void {
    if (index < 0) return;
    this.active.set(index);
    this.viaKeys.set(true);
    this.reveal(index);
  }

  private pickActive(): void {
    const row = this.rows()[this.active()];
    if (row) this.pick(row);
    else this.close(true);
  }

  private commit(value: string): void {
    if (value === this.value()) return;
    this.value.set(value);
    this.onChange(value);
  }

  // --- Open and close ---------------------------------------------------------------

  private show(active: number, viaKeys = true): void {
    this.active.set(active);
    this.viaKeys.set(viaKeys);
    this.open.set(true);
    if (this.phone()) {
      // The sheet focuses its first control after its render; the listbox goes after.
      this.later(() => {
        this.toTopLayer(this.layer()?.nativeElement);
        this.later(() => {
          document.getElementById(this.listId())?.focus();
          this.reveal(this.active());
        });
      });
      return;
    }
    this.placed.set(false);
    this.later(() => {
      const menu = this.menu()?.nativeElement;
      if (!menu) return;
      this.toTopLayer(menu);
      this.place(menu);
      this.placed.set(true);
      this.reveal(this.active());
    });
  }

  private close(returnFocus: boolean): void {
    if (!this.open()) return;
    this.open.set(false);
    this.placed.set(false);
    this.active.set(-1);
    this.clearTimer();
    this.typed = '';
    this.onTouched();
    if (returnFocus) this.trigger().nativeElement.focus();
  }

  /** Show a popover element. It renders anew on each opening, so it is not shown yet. */
  private toTopLayer(el: HTMLElement | undefined): void {
    const pop = el as (HTMLElement & { showPopover?: () => void }) | undefined;
    if (typeof pop?.showPopover === 'function') pop.showPopover();
  }

  /** Scroll the active row into the visible part of the list. */
  private reveal(index: number): void {
    const el = index >= 0 ? document.getElementById(this.optionId(index)) : null;
    if (el && typeof el.scrollIntoView === 'function') el.scrollIntoView({ block: 'nearest' });
  }

  /**
   * Under the field, as wide as the field at least, inside the viewport. Above the field
   * when the room below is too small and the room above is larger.
   */
  private place(menu: HTMLElement): void {
    const field = this.box().nativeElement.getBoundingClientRect();
    const below = window.innerHeight - field.bottom - GAP - EDGE;
    const above = field.top - GAP - EDGE;
    const natural = Math.min(menu.scrollHeight, MAX_HEIGHT);
    const up = natural > below && above > below;
    const maxHeight = Math.max(0, Math.min(MAX_HEIGHT, up ? above : below));
    const height = Math.min(natural, maxHeight);
    const width = Math.min(field.width, window.innerWidth - 2 * EDGE);
    const own = Math.max(width, menu.getBoundingClientRect().width);
    const left = Math.max(EDGE, Math.min(field.left, window.innerWidth - EDGE - own));
    const top = up ? field.top - GAP - height : field.bottom + GAP;
    this.position.set({ top, left, width, maxHeight });
  }

  /** The page scrolled or resized: keep the list at its field; close it when it leaves. */
  private follow(): void {
    const rect = this.box().nativeElement.getBoundingClientRect();
    if (rect.bottom < 0 || rect.top > window.innerHeight) {
      this.close(false);
      return;
    }
    const menu = this.menu()?.nativeElement;
    if (menu) this.place(menu);
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
