import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  afterNextRender,
  inject,
  input,
  output,
  signal,
} from '@angular/core';
import { BREAKPOINTS, IconComponent, MEDIA } from '@stupa-makers/ui-kit';
import { TranslatePipe } from '@core/i18n/translate.pipe';

/** The width of the navigation rail of the shell, in px. */
export const NAV_RAIL_WIDTH = 96;

/**
 * The narrowest CONTENT width that shows the list and the detail side by side, in px.
 *
 * The layout measures its own width, not the viewport, so it also works in a pane. The
 * value is the content width that the first wide viewport (`BREAKPOINTS.wideMin`, 1200px)
 * leaves beside the navigation rail. A narrow viewport (the 960px boards) is below it, so
 * there the list and the detail are separate views.
 */
export const LIST_DETAIL_SPLIT_MIN = BREAKPOINTS.wideMin - NAV_RAIL_WIDTH;

/**
 * A list with a detail sheet beside it, as on the applications page.
 *
 * Wide: the list on the left at a fixed width (`--ld-list-width`, default 440px), the
 * detail sheet fills the rest. Narrow (content below {@link LIST_DETAIL_SPLIT_MIN}): one
 * view at a time. The list shows until `detailOpen` is set; then the detail shows with a
 * "Zur Liste" control above it that emits `back`. The list stays in the DOM while hidden,
 * so it keeps its scroll position.
 *
 * Slots: `[list]` and `[detail]`. In the wide layout with no detail open the page puts its
 * own empty state into the detail slot.
 */
@Component({
  selector: 'app-list-detail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent, TranslatePipe],
  host: {
    '[class.ld--split]': '!collapsed()',
    '[class.ld--collapsed]': 'collapsed()',
  },
  templateUrl: './list-detail-layout.component.html',
  styleUrl: './list-detail-layout.component.scss',
})
export class ListDetailLayoutComponent {
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);

  /** A row is open, so the narrow layout shows the detail. */
  readonly detailOpen = input(false);
  /** The content width from which the panes sit side by side. */
  readonly splitMin = input(LIST_DETAIL_SPLIT_MIN);

  /** "Zur Liste" was pressed (narrow layout). The page clears its selection. */
  readonly back = output<void>();

  /** True while the content is too narrow for two panes. */
  readonly collapsed = signal(!window.matchMedia(MEDIA.wide).matches);

  constructor() {
    let observer: ResizeObserver | null = null;
    afterNextRender(() => {
      const el = this.host.nativeElement;
      this.measure(el.getBoundingClientRect().width);
      observer = new ResizeObserver((entries) => {
        for (const entry of entries) this.measure(entry.contentRect.width);
      });
      observer.observe(el);
    });
    inject(DestroyRef).onDestroy(() => observer?.disconnect());
  }

  /** A width of 0 means "not laid out yet" (hidden, or a test): keep the media query guess. */
  private measure(width: number): void {
    if (width > 0) this.collapsed.set(width < this.splitMin());
  }
}
