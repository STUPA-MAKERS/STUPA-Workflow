import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  afterRenderEffect,
  inject,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { ApiClient } from '@core/api/api-client.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { SideSheetComponent } from '@shared/ui/side-sheet/side-sheet.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';
import {
  ButtonComponent,
  CopyButtonComponent,
  IconComponent,
  MEDIA,
  mediaQuery,
  placeBelow,
  showInTopLayer,
  watchAnchoredPopover,
} from '@stupa-makers/ui-kit';
import { EmptyStateComponent } from '@shared/ui/empty-state/empty-state.component';

/** The gap between the anchor and the popover, and the least gap to the viewport edge. */
const GAP = 6;
const EDGE = 8;
let nextId = 0;

/**
 * "Kalender-Abo": the personal iCal feed of the meetings of the Gremien of the user, as
 * a popover of the meetings page (on a phone: the shared bottom sheet).
 *
 * The component has no trigger of its own. A page places it once and opens it from its
 * own controls with `toggle(anchor)` (the calendar icon of the list and of the calendar
 * view) or `open()` (the ⋮ menu of the phone header): `<app-calendar-subscribe #abo />`.
 *
 * It reads `GET /calendar/me` on the first opening. The server creates the feed token
 * only on "Abo-Link erzeugen"; until then the URL is `null`. "Neue URL erzeugen" asks
 * first, because the old URL stops working. The URL wraps and stays fully selectable;
 * "Kopieren" puts it on the clipboard.
 *
 * Desktop: a popover under the anchor, aligned to its end, inside the viewport. Escape
 * and a pointer down outside close it, and the focus goes back to the anchor. A resize
 * across the phone limit while it is open swaps the popover and the sheet, and puts the
 * new one into the top layer.
 *
 * The popover never paints in a wrong place. Right after the render that creates it
 * (`afterRenderEffect`, before the browser paints) it enters the top layer, the frame
 * measures it and writes its place, and only then the class `cs--placed` makes it
 * visible. Until then CSS keeps it hidden, also outside the top layer. A
 * `ResizeObserver` on the popover, the anchor and the containers of the anchor (up to
 * `main`) places it again when the layout changes (the feed loads, the header gets a
 * control). The page itself (`body`) is no use: on a pane page it never changes size.
 * The window events `resize` and `scroll` catch the rest.
 *
 * A failed read says "could not be loaded" and offers a new read. A failed create of
 * the link says "could not be created" (`rotateError`); the URL that shows stays valid.
 */
@Component({
  selector: 'app-calendar-subscribe',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    EmptyStateComponent,
    NgTemplateOutlet,
    TranslatePipe,
    ButtonComponent,
    CopyButtonComponent,
    IconComponent,
    SideSheetComponent,
    SkeletonComponent,
  ],
  templateUrl: './calendar-subscribe.component.html',
  styleUrl: './calendar-subscribe.component.scss',
})
export class CalendarSubscribeComponent {
  private readonly api = inject(ApiClient);

  /** A phone viewport: the bottom sheet instead of the popover. */
  readonly phone = mediaQuery(MEDIA.phone);
  readonly isOpen = signal(false);
  readonly headingId = `cs-title-${nextId++}`;

  readonly url = signal<string | null>(null);
  readonly loading = signal(false);
  readonly error = signal(false);
  /** The last create of the link ("Abo-Link erzeugen", "Neue URL erzeugen") failed. */
  readonly rotateError = signal(false);
  readonly busy = signal(false);
  /** "Neue URL erzeugen" waits for the confirmation. */
  readonly confirming = signal(false);
  private loaded = false;
  private anchor: HTMLElement | null = null;

  private readonly pop = viewChild<ElementRef<HTMLElement>>('pop');
  private readonly layer = viewChild<ElementRef<HTMLElement>>('layer');
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  /** The element that is in the top layer now (popover or sheet), else null. */
  private shownEl: HTMLElement | null = null;
  private observer: ResizeObserver | null = null;
  private readonly copyButton = viewChild(CopyButtonComponent);

  constructor() {
    watchAnchoredPopover({
      isOpen: () => this.isOpen() && !this.phone(),
      // A press on the anchor toggles by itself; closing here would reopen it.
      inside: () => [this.pop()?.nativeElement, this.anchor],
      close: () => this.close(false),
      follow: () => this.place(),
    });
    inject(DestroyRef).onDestroy(() => this.unobserve());

    // After each render that changes the open state, the mode (a resize across the phone
    // limit renders the other element) or the element itself: put the new element into
    // the top layer, and place the popover before the browser paints it.
    afterRenderEffect(() => {
      const open = this.isOpen();
      const phone = this.phone();
      const el = (phone ? this.layer() : this.pop())?.nativeElement ?? null;
      untracked(() => this.reveal(open, phone, el));
    });
  }

  /** Open under `anchor`, or close when it is open. */
  toggle(anchor: EventTarget | null = null): void {
    if (this.isOpen()) this.close(true);
    else this.open(anchor);
  }

  /** Open the popover under `anchor` (on a phone: the bottom sheet). */
  open(anchor: EventTarget | null = null): void {
    this.anchor = anchor instanceof HTMLElement ? anchor : null;
    this.confirming.set(false);
    this.copyButton()?.reset();
    this.rotateError.set(false);
    this.isOpen.set(true);
    if (!this.loaded) this.load();
  }

  /**
   * Put the sheet (phone) or the popover into the top layer, once per element. The
   * popover is placed before it shows (`cs--placed`), then it gets the focus.
   */
  private reveal(open: boolean, phone: boolean, el: HTMLElement | null): void {
    if (!open || !el) {
      this.shownEl = null;
      this.unobserve();
      return;
    }
    if (el === this.shownEl) return;
    this.shownEl = el;
    this.unobserve();
    showInTopLayer(el);
    if (phone) return;
    this.place();
    el.classList.add('cs--placed');
    el.focus();
    this.observe(el);
  }

  /**
   * Place the popover again when its size, the anchor or a container of the anchor
   * changes. An anchor moves without a change of its own size when a box around it
   * changes (a control appears beside it, the pane gets narrower), so each container up
   * to `main` is observed too.
   */
  private observe(el: HTMLElement): void {
    if (typeof ResizeObserver !== 'function') return;
    this.observer = new ResizeObserver(() => {
      if (this.isOpen() && !this.phone()) this.place();
    });
    this.observer.observe(el);
    if (!this.anchor) return;
    this.observer.observe(this.anchor);
    for (let box = this.anchor.parentElement; box && box !== document.body; box = box.parentElement) {
      this.observer.observe(box);
      if (box.tagName === 'MAIN') break;
    }
  }

  private unobserve(): void {
    this.observer?.disconnect();
    this.observer = null;
  }

  /** Close; `returnFocus` puts the focus back on the anchor. */
  close(returnFocus = true): void {
    if (!this.isOpen()) return;
    this.isOpen.set(false);
    this.confirming.set(false);
    if (returnFocus) this.anchor?.focus();
  }

  /** Escape in the popover. The sheet handles its own keys. */
  onKey(event: KeyboardEvent): void {
    if (event.key !== 'Escape') return;
    event.preventDefault();
    event.stopPropagation();
    this.close(true);
  }

  /** The sheet closed itself (Escape, scrim, close button, swipe). */
  onSheetOpen(open: boolean): void {
    if (!open) this.close(false);
  }

  /** Read the feed again after a failed read. */
  load(): void {
    this.loading.set(true);
    this.error.set(false);
    this.api.myCalendar().subscribe({
      next: (feed) => {
        this.loaded = true;
        this.url.set(feed.url);
        this.loading.set(false);
      },
      error: () => {
        this.error.set(true);
        this.loading.set(false);
      },
    });
  }

  /** "Neue URL erzeugen": ask first, the old URL stops working. */
  askRotate(): void {
    this.confirming.set(true);
  }

  cancelRotate(): void {
    this.confirming.set(false);
  }

  /** Create the feed token, or a new one. A new one makes the previous URL invalid. */
  rotate(): void {
    if (this.busy()) return;
    this.busy.set(true);
    this.rotateError.set(false);
    this.api.rotateCalendar().subscribe({
      next: (feed) => {
        this.loaded = true;
        this.url.set(feed.url);
        this.busy.set(false);
        this.confirming.set(false);
      },
      error: () => {
        this.rotateError.set(true);
        this.busy.set(false);
      },
    });
  }


  /**
   * Under the anchor, aligned to its end, inside the viewport. The place goes straight
   * to the element (no template binding, which would wait for the next change detection
   * and start at 0/0).
   */
  private place(): void {
    const pop = this.pop()?.nativeElement;
    if (!pop) return;
    const rect = (this.anchor ?? this.host.nativeElement).getBoundingClientRect();
    const { top, left } = placeBelow(rect, pop.getBoundingClientRect(), { gap: GAP, edge: EDGE, align: 'end' });
    pop.style.top = `${top}px`;
    pop.style.left = `${left}px`;
  }
}

