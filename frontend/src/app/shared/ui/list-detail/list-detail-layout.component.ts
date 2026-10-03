import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  afterNextRender,
  computed,
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
 * The page gutter on one side of the content, in px: `--layout-gutter` (`--space-5`,
 * 1.5rem at a 16px root font size). The `.page-shell` box has it on the left and on the
 * right.
 */
export const LAYOUT_GUTTER = 24;

/**
 * The narrowest CONTENT width that shows the list and the detail side by side, in px.
 *
 * The value is the content box that the first wide viewport (`BREAKPOINTS.wideMin`,
 * 1200px) leaves in the shell: the viewport minus the navigation rail and minus the two
 * page gutters (1200 - 96 - 2 * 24 = 1056).
 *
 * The layout splits only when two conditions are true: the viewport is wide
 * (`MEDIA.wide`), and the host is at least this wide. The viewport class makes the switch
 * occur exactly at the wide breakpoint, whatever the shell adds or removes around the
 * content. The measured width collapses the layout when it is in a pane that is too
 * narrow for two panes.
 */
export const LIST_DETAIL_SPLIT_MIN = BREAKPOINTS.wideMin - NAV_RAIL_WIDTH - 2 * LAYOUT_GUTTER;

/**
 * A list with a detail sheet beside it, as on the applications page.
 *
 * Wide (a wide viewport and content of {@link LIST_DETAIL_SPLIT_MIN} or more): the list on
 * the left at a fixed width (`--ld-list-width`, default 440px), the detail sheet fills the
 * rest. Otherwise one view at a time. The list shows until `detailOpen` is set; then the
 * detail shows with a "Zur Liste" control above it that emits `back`. The list stays in the
 * DOM while hidden, so it keeps its scroll position.
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

  /** The viewport is in the wide class (`MEDIA.wide`). */
  private readonly viewportWide = signal(false);
  /** The measured width of the host. 0 means "not laid out yet" (hidden, or a test). */
  private readonly width = signal(0);

  /** True while the viewport or the content is too narrow for two panes. */
  readonly collapsed = computed(() => {
    if (!this.viewportWide()) return true;
    const width = this.width();
    return width > 0 && width < this.splitMin();
  });

  constructor() {
    const media = window.matchMedia(MEDIA.wide);
    this.viewportWide.set(media.matches);
    const onMedia = (event: MediaQueryListEvent): void => this.viewportWide.set(event.matches);
    media.addEventListener('change', onMedia);

    let observer: ResizeObserver | null = null;
    afterNextRender(() => {
      const el = this.host.nativeElement;
      this.width.set(el.getBoundingClientRect().width);
      observer = new ResizeObserver((entries) => {
        for (const entry of entries) this.width.set(entry.contentRect.width);
      });
      observer.observe(el);
    });
    inject(DestroyRef).onDestroy(() => {
      observer?.disconnect();
      media.removeEventListener('change', onMedia);
    });
  }
}
