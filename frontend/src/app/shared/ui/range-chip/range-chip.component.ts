import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  computed,
  inject,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  ButtonComponent,
  CurrencyInputComponent,
  DatepickerComponent,
  IconComponent,
  MEDIA,
} from '@stupa-makers/ui-kit';
import { mediaQuerySignal } from '../../../layout/media-query';
import { SideSheetComponent } from '../side-sheet/side-sheet.component';

/** What a range chip filters: an amount in euro or a date (ISO `YYYY-MM-DD`). */
export type RangeKind = 'amount' | 'date';

/** Space between the popover and the edge of the viewport, in px. */
const EDGE = 8;
/** Space between the chip and the popover, in px. */
const GAP = 4;

/** The two bounds of a range. An empty string is an open bound. */
export interface RangeValue {
  from: string;
  to: string;
}

/**
 * A filter chip for a range: an amount from and to, or a date from and to.
 *
 * The chip opens the two fields like `app-filter-select` opens its list: a popover under
 * the chip on a wide screen, the shared bottom sheet on a phone. The values are typed, so
 * the fields edit a draft and only "Anwenden" applies it (`applied`). "Zurücksetzen"
 * clears both bounds and applies at once. Another close (Escape, a click outside, the
 * scrim) keeps the old range.
 *
 * The chip shows the label while no bound is set. With a bound it shows the range, for
 * example "Betrag: 100,00 € – 500,00 €" or "Zeitraum: ab 01.09.2026", in the selected
 * look with a check mark.
 */
@Component({
  selector: 'app-range-chip',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ButtonComponent,
    CurrencyInputComponent,
    DatepickerComponent,
    FormsModule,
    IconComponent,
    NgTemplateOutlet,
    SideSheetComponent,
    TranslatePipe,
  ],
  templateUrl: './range-chip.component.html',
  styleUrl: './range-chip.component.scss',
})
export class RangeChipComponent {
  private readonly i18n = inject(I18nService);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);

  /** The name of the filter: the chip text without a range and the sheet heading. */
  readonly label = input.required<string>();
  readonly kind = input<RangeKind>('amount');
  readonly from = input('');
  readonly to = input('');

  /** "Anwenden" or "Zurücksetzen" set a new range. */
  readonly applied = output<RangeValue>();

  private readonly phone = mediaQuerySignal(MEDIA.phone);

  protected readonly open = signal(false);
  protected readonly popoverOpen = computed(() => this.open() && !this.phone());
  protected readonly sheetOpen = computed(() => this.open() && this.phone());
  protected readonly position = signal({ top: 0, left: 0 });

  private readonly trigger = viewChild.required<ElementRef<HTMLButtonElement>>('trigger');
  private readonly pop = viewChild<ElementRef<HTMLElement>>('pop');
  private timer: ReturnType<typeof setTimeout> | null = null;

  constructor() {
    const inside = (root: HTMLElement | undefined, target: EventTarget | null) =>
      !!root && target instanceof Node && root.contains(target);
    // The popover is a child of the host, so a click in it is no click outside.
    const onPointer = (e: Event) => {
      if (this.popoverOpen() && !inside(this.host.nativeElement, e.target)) this.close(false);
    };
    const onViewport = (e: Event) => {
      if (this.popoverOpen() && !inside(this.pop()?.nativeElement, e.target)) this.follow();
    };
    document.addEventListener('pointerdown', onPointer, true);
    window.addEventListener('scroll', onViewport, true);
    window.addEventListener('resize', onViewport);
    inject(DestroyRef).onDestroy(() => {
      document.removeEventListener('pointerdown', onPointer, true);
      window.removeEventListener('scroll', onViewport, true);
      window.removeEventListener('resize', onViewport);
      if (this.timer) clearTimeout(this.timer);
    });
  }
  protected readonly draftFrom = signal('');
  protected readonly draftTo = signal('');

  /** A bound is set. */
  readonly active = computed(() => this.from().trim() !== '' || this.to().trim() !== '');

  /** The chip text: the label, or the label with the range. */
  readonly chipText = computed(() => {
    const from = this.from().trim();
    const to = this.to().trim();
    if (!from && !to) return this.label();
    let range: string;
    if (from && to) range = `${this.format(from)} – ${this.format(to)}`;
    else if (from) range = this.i18n.translate('ui.range.fromOnly', { value: this.format(from) });
    else range = this.i18n.translate('ui.range.toOnly', { value: this.format(to) });
    return `${this.label()}: ${range}`;
  });

  /** The draft is a valid range: no bound, one bound, or a start before the end. */
  protected readonly draftValid = computed(() => {
    const from = this.draftFrom().trim();
    const to = this.draftTo().trim();
    if (!from || !to) return true;
    if (this.kind() === 'amount') return Number(from) <= Number(to);
    return from <= to;
  });

  /** A click on the chip opens the fields, or closes them when they are open. */
  protected toggle(): void {
    if (this.open()) this.close(true);
    else this.openSheet();
  }

  /** Open the fields on a copy of the current range. */
  openSheet(): void {
    this.draftFrom.set(this.from());
    this.draftTo.set(this.to());
    this.open.set(true);
    if (this.phone()) return;
    this.placeBelow();
    // The popover renders in the next change detection; then it goes to the top layer.
    this.timer = setTimeout(() => {
      this.timer = null;
      const pop = this.pop()?.nativeElement as (HTMLElement & { showPopover?: () => void }) | undefined;
      if (!pop) return;
      if (typeof pop.showPopover === 'function') pop.showPopover();
      this.fit(pop);
      (pop.querySelector<HTMLElement>('input') ?? pop).focus();
    });
  }

  apply(): void {
    if (!this.draftValid()) return;
    this.close(true);
    this.applied.emit({ from: this.draftFrom().trim(), to: this.draftTo().trim() });
  }

  reset(): void {
    this.draftFrom.set('');
    this.draftTo.set('');
    this.close(true);
    this.applied.emit({ from: '', to: '' });
  }

  /** Escape in the popover closes it and keeps the old range. */
  protected onPopKey(event: KeyboardEvent): void {
    if (event.key !== 'Escape') return;
    event.preventDefault();
    event.stopPropagation();
    this.close(true);
  }

  /** The sheet closed itself (Escape, scrim, close button). */
  protected onSheetOpen(open: boolean): void {
    if (!open) this.open.set(false);
  }

  private close(returnFocus: boolean): void {
    if (!this.open()) return;
    const wasPopover = this.popoverOpen();
    this.open.set(false);
    // The sheet returns the focus itself.
    if (returnFocus && wasPopover) this.trigger().nativeElement.focus();
  }

  /** Under the chip, aligned to its start, inside the viewport. */
  private placeBelow(): void {
    const rect = this.trigger().nativeElement.getBoundingClientRect();
    this.position.set({ top: rect.bottom + GAP, left: Math.max(EDGE, rect.left) });
  }

  /** The page scrolled or resized: keep the popover at its chip; close it when the chip leaves. */
  private follow(): void {
    const rect = this.trigger().nativeElement.getBoundingClientRect();
    if (rect.bottom < 0 || rect.top > window.innerHeight) {
      this.close(false);
      return;
    }
    this.placeBelow();
    const pop = this.pop()?.nativeElement;
    if (pop) this.fit(pop);
  }

  /** Move the popover left when it passes the right edge, and up when it does not fit below. */
  private fit(pop: HTMLElement): void {
    const pos = this.position();
    const box = pop.getBoundingClientRect();
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

  private format(value: string): string {
    if (this.kind() === 'amount') {
      const n = Number(value);
      if (!Number.isFinite(n)) return value;
      return n.toLocaleString(this.i18n.formatLocale(), { style: 'currency', currency: 'EUR' });
    }
    const [y, m, d] = value.split('-').map(Number);
    if (!y || !m || !d) return value;
    return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString(this.i18n.formatLocale(), {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      timeZone: 'UTC',
    });
  }
}
