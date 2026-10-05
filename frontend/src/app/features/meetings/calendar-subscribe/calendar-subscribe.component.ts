import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { ApiClient } from '@core/api/api-client.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { SideSheetComponent } from '@shared/ui/side-sheet/side-sheet.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';
import { ButtonComponent, IconComponent, MEDIA } from '@stupa-makers/ui-kit';
import { mediaQuerySignal } from '../../../layout/media-query';

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
 * and a pointer down outside close it, and the focus goes back to the anchor.
 */
@Component({
  selector: 'app-calendar-subscribe',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    NgTemplateOutlet,
    TranslatePipe,
    ButtonComponent,
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
  readonly phone = mediaQuerySignal(MEDIA.phone);
  readonly isOpen = signal(false);
  readonly position = signal({ top: 0, left: 0 });
  readonly headingId = `cs-title-${nextId++}`;

  readonly url = signal<string | null>(null);
  readonly loading = signal(false);
  readonly error = signal(false);
  readonly busy = signal(false);
  readonly copied = signal(false);
  /** "Neue URL erzeugen" waits for the confirmation. */
  readonly confirming = signal(false);
  private loaded = false;
  private anchor: HTMLElement | null = null;

  private readonly pop = viewChild<ElementRef<HTMLElement>>('pop');
  private readonly layer = viewChild<ElementRef<HTMLElement>>('layer');
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private timer: ReturnType<typeof setTimeout> | null = null;

  constructor() {
    const onPointer = (e: Event) => {
      if (!this.isOpen() || this.phone()) return;
      const target = e.target as Node;
      const inPop = !!this.pop()?.nativeElement.contains(target);
      const onAnchor = !!this.anchor?.contains(target);
      // A press on the anchor toggles by itself; closing here would reopen it.
      if (!inPop && !onAnchor) this.close(false);
    };
    const onResize = () => {
      if (this.isOpen() && !this.phone()) this.place();
    };
    document.addEventListener('pointerdown', onPointer, true);
    window.addEventListener('resize', onResize);
    window.addEventListener('scroll', onResize, true);
    inject(DestroyRef).onDestroy(() => {
      document.removeEventListener('pointerdown', onPointer, true);
      window.removeEventListener('resize', onResize);
      window.removeEventListener('scroll', onResize, true);
      if (this.timer !== null) clearTimeout(this.timer);
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
    this.copied.set(false);
    this.isOpen.set(true);
    if (!this.loaded) this.load();
    this.later(() => {
      if (this.phone()) {
        showPopover(this.layer()?.nativeElement);
        return;
      }
      const pop = this.pop()?.nativeElement;
      showPopover(pop);
      this.place();
      pop?.focus();
    });
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
    this.error.set(false);
    this.copied.set(false);
    this.api.rotateCalendar().subscribe({
      next: (feed) => {
        this.loaded = true;
        this.url.set(feed.url);
        this.busy.set(false);
        this.confirming.set(false);
      },
      error: () => {
        this.error.set(true);
        this.busy.set(false);
      },
    });
  }

  /** Copy the subscription URL to the clipboard. The Clipboard API can be absent. */
  copy(): void {
    const url = this.url();
    if (!url) return;
    void navigator.clipboard?.writeText(url)?.then(
      () => this.copied.set(true),
      () => this.copied.set(false),
    );
  }

  /** Under the anchor, aligned to its end, inside the viewport. */
  private place(): void {
    const pop = this.pop()?.nativeElement;
    if (!pop) return;
    const rect = (this.anchor ?? this.host.nativeElement).getBoundingClientRect();
    const box = pop.getBoundingClientRect();
    const left = Math.min(
      Math.max(EDGE, rect.right - box.width),
      Math.max(EDGE, window.innerWidth - EDGE - box.width),
    );
    let top = rect.bottom + GAP;
    if (top + box.height > window.innerHeight - EDGE && rect.top - GAP - box.height >= EDGE) {
      top = rect.top - GAP - box.height;
    }
    this.position.set({ top, left });
  }

  private later(fn: () => void): void {
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = setTimeout(() => {
      this.timer = null;
      fn();
    });
  }
}

/** Put a popover element into the top layer. It renders anew on each opening. */
function showPopover(el: HTMLElement | undefined): void {
  const pop = el as (HTMLElement & { showPopover?: () => void }) | undefined;
  if (typeof pop?.showPopover === 'function') pop.showPopover();
}
