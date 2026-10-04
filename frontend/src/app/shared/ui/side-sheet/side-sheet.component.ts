import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  effect,
  inject,
  input,
  model,
  output,
  viewChild,
} from '@angular/core';
import { IconComponent } from '@stupa-makers/ui-kit';
import { TranslatePipe } from '@core/i18n/translate.pipe';

/**
 * Where the sheet comes from: `end` (the attendance sheet), `start` (the agenda drawer)
 * or `bottom` (the "Mehr" sheet of the phone bar).
 */
export type SheetSide = 'end' | 'start' | 'bottom';

let nextId = 0;

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

/**
 * A modal sheet over a scrim: the attendance sheet (end), the agenda drawer (start) and
 * the "Mehr" sheet of the phone bar (bottom).
 *
 * It is a modal dialog: the focus moves into the sheet when it opens and comes back to
 * where it was when it closes, Tab stays inside, Escape and a click on the scrim close
 * it, and the page behind does not scroll.
 *
 * `open` is two-way: `[(open)]="attendanceOpen"`. `closed` fires when the sheet closes
 * itself (Escape, the scrim, the close button).
 *
 * Slots: the content, and `[sheet-actions]` for controls in the header before the close
 * button.
 *
 * `contentScrolls`: the content scrolls a list of its own and keeps its header in place
 * (the cost-centre picker). The body then only passes the height down and does not
 * scroll. The content must be a flex item that can shrink (`flex: 1 1 auto;
 * min-height: 0`).
 */
@Component({
  selector: 'app-side-sheet',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent, TranslatePipe],
  templateUrl: './side-sheet.component.html',
  styleUrl: './side-sheet.component.scss',
})
export class SideSheetComponent {
  readonly open = model(false);
  /** The title of the sheet, also its accessible name. */
  readonly heading = input.required<string>();
  readonly side = input<SheetSide>('end');
  /** The content scrolls by itself; the body does not. */
  readonly contentScrolls = input(false);

  readonly closed = output<void>();

  protected readonly id = `side-sheet-${nextId++}`;
  private readonly pane = viewChild<ElementRef<HTMLElement>>('pane');

  private returnFocus: HTMLElement | null = null;
  private bodyOverflow: string | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;

  constructor() {
    effect(() => {
      if (this.open()) this.activate();
      else this.deactivate();
    });
    inject(DestroyRef).onDestroy(() => this.deactivate());
  }

  close(): void {
    this.open.set(false);
    this.closed.emit();
  }

  protected onKey(event: KeyboardEvent): void {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      this.close();
      return;
    }
    if (event.key !== 'Tab') return;
    const pane = event.currentTarget as HTMLElement;
    const items = this.focusables(pane);
    if (items.length === 0) {
      event.preventDefault();
      pane.focus();
      return;
    }
    const first = items[0];
    const last = items[items.length - 1];
    const active = document.activeElement;
    if (event.shiftKey && (active === first || active === pane)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  }

  /** Runs once per opening: the effect reads only `open`. */
  private activate(): void {
    this.returnFocus = document.activeElement as HTMLElement | null;
    this.bodyOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    // The pane renders in this change detection; focus it right after. Closing clears
    // the timer, so the pane is there when it runs.
    this.timer = setTimeout(() => {
      this.timer = null;
      const pane = this.pane()!.nativeElement;
      (this.focusables(pane)[0] ?? pane).focus();
    });
  }

  private deactivate(): void {
    clearTimeout(this.timer ?? undefined);
    this.timer = null;
    // Closed from the start: nothing to undo.
    if (this.bodyOverflow === null) return;
    document.body.style.overflow = this.bodyOverflow;
    this.bodyOverflow = null;
    const target = this.returnFocus;
    this.returnFocus = null;
    if (target?.isConnected) target.focus();
  }

  private focusables(root: HTMLElement): HTMLElement[] {
    return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE));
  }
}
