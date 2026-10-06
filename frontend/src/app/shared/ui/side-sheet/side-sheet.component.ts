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
  signal,
  viewChild,
} from '@angular/core';
import { IconComponent } from '@stupa-makers/ui-kit';
import { TranslatePipe } from '@core/i18n/translate.pipe';

/**
 * Where the sheet comes from: `end` (the attendance sheet), `start` (the agenda drawer)
 * or `bottom` (the phone sheet: the "Mehr" sheet of the phone bar, and the pickers and
 * secondary panes of a page on a phone).
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

/** A drag down by more than this many pixels closes a bottom sheet. */
const SWIPE_CLOSE_PX = 96;
/** A quick flick down (px per ms) closes it after a shorter way too. */
const SWIPE_CLOSE_SPEED = 0.5;
/** The way down that a flick needs at least, so a tap does not close the sheet. */
const SWIPE_MIN_PX = 24;
/** Controls in the header keep their own pointer events and start no drag. */
const NO_DRAG = 'button, a, input, select, textarea';

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
 * The bottom sheet is the phone sheet: a handle above a fixed header, rounded top
 * corners, at most 85% of the viewport high. A swipe down on the handle or the header
 * closes it too. The body scrolls inside and fades at an end only where more content is
 * hidden.
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
  private readonly body = viewChild<ElementRef<HTMLElement>>('body');

  /** More content above or below the visible part of the body. */
  protected readonly fadeTop = signal(false);
  protected readonly fadeBottom = signal(false);
  /** How far a swipe pulls the bottom sheet down now, in px. */
  protected readonly dragY = signal(0);
  /** A swipe runs: the sheet follows the finger without a transition. */
  protected readonly dragging = signal(false);

  private drag: { pointerId: number; startY: number; startTime: number } | null = null;
  private bodyObserver: ResizeObserver | null = null;

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

  /** Read the scroll position of the body and set the fades. */
  protected measure(): void {
    const el = this.body()?.nativeElement;
    if (!el) return;
    // A sub-pixel layout leaves a fraction of a pixel over on a body that fits.
    const slack = 1;
    this.fadeTop.set(el.scrollTop > slack);
    this.fadeBottom.set(el.scrollTop < el.scrollHeight - el.clientHeight - slack);
  }

  /** Start a swipe on the handle or the header of a bottom sheet. */
  protected dragStart(event: PointerEvent): void {
    if (this.side() !== 'bottom' || !event.isPrimary || event.button !== 0) return;
    if ((event.target as Element | null)?.closest(NO_DRAG)) return;
    this.drag = { pointerId: event.pointerId, startY: event.clientY, startTime: event.timeStamp };
    this.dragging.set(true);
    (event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId);
  }

  protected dragMove(event: PointerEvent): void {
    if (event.pointerId !== this.drag?.pointerId) return;
    // The sheet follows the finger down, never up past its place.
    this.dragY.set(Math.max(0, event.clientY - this.drag.startY));
  }

  /** End a swipe: a long or quick way down closes the sheet, else it snaps back. */
  protected dragEnd(event: PointerEvent): void {
    const drag = this.drag;
    if (event.pointerId !== drag?.pointerId) return;
    const distance = Math.max(0, event.clientY - drag.startY);
    const speed = distance / Math.max(1, event.timeStamp - drag.startTime);
    this.drag = null;
    this.dragging.set(false);
    this.dragY.set(0);
    if (event.type === 'pointercancel') return;
    if (distance > SWIPE_CLOSE_PX || (distance > SWIPE_MIN_PX && speed > SWIPE_CLOSE_SPEED)) {
      this.close();
    }
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
      this.watchBody();
    });
  }

  /**
   * Measure the fades now and whenever the body or its content changes size. The body
   * keeps its height while the content grows inside it, so the children are watched too.
   */
  private watchBody(): void {
    const el = this.body()?.nativeElement;
    if (!el) return;
    this.bodyObserver = new ResizeObserver(() => this.measure());
    this.bodyObserver.observe(el);
    for (const child of Array.from(el.children)) this.bodyObserver.observe(child);
    this.measure();
  }

  private deactivate(): void {
    clearTimeout(this.timer ?? undefined);
    this.timer = null;
    this.bodyObserver?.disconnect();
    this.bodyObserver = null;
    this.drag = null;
    this.dragging.set(false);
    this.dragY.set(0);
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
