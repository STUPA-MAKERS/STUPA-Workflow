import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  afterNextRender,
  inject,
  input,
  signal,
} from '@angular/core';
import { IconComponent } from '@stupa-makers/ui-kit';

/** Where the overlay sits on the screen, in px. */
interface Box {
  top: number;
  left: number;
  width: number;
  height: number;
}

/**
 * The drop target that shows while files hover over an element (`appFileDrop`): a dashed
 * accent frame with the upload icon and one line, in the look of the invoices page.
 *
 * - `fit="box"`: it covers its parent, which needs `position: relative`. For an element
 *   that does not scroll as a whole (the chat, the attachments panel).
 * - `fit="view"`: it covers the part of its parent that is on the screen, also when the
 *   parent is taller than its scroll pane (an application page).
 *
 * It only shows; it never takes a pointer event, so the drop lands on the element below.
 */
@Component({
  selector: 'app-drop-overlay',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent],
  templateUrl: './drop-overlay.component.html',
  styleUrl: './drop-overlay.component.scss',
  host: {
    'aria-hidden': 'true',
    '[class.drop--view]': "fit() === 'view'",
    '[style.top.px]': 'box()?.top',
    '[style.left.px]': 'box()?.left',
    '[style.width.px]': 'box()?.width',
    '[style.height.px]': 'box()?.height',
  },
})
export class DropOverlayComponent {
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);

  readonly label = input.required<string>();
  readonly fit = input<'box' | 'view'>('box');

  protected readonly box = signal<Box | null>(null);

  constructor() {
    afterNextRender(() => {
      const parent = this.host.nativeElement.parentElement;
      if (this.fit() !== 'view' || !parent) return;
      const r = parent.getBoundingClientRect();
      const top = Math.max(r.top, 0);
      const left = Math.max(r.left, 0);
      const bottom = Math.min(r.bottom, window.innerHeight);
      const right = Math.min(r.right, window.innerWidth);
      this.box.set({ top, left, width: Math.max(0, right - left), height: Math.max(0, bottom - top) });
    });
  }
}
