import { ChangeDetectionStrategy, Component, Directive, contentChild, input } from '@angular/core';

/**
 * Marks the element that a page projects as the kicker of `app-sheet-bar`, for a kicker
 * that is more than text (the cost-centre breadcrumb of the budget page). The bar gives
 * it the place, the size, the weight and the colour of the text kicker.
 */
@Directive({
  selector: '[appSheetBarKicker]',
  standalone: true,
})
export class SheetBarKickerDirective {}

/**
 * The top bar of a detail sheet: the kicker (the context line above the title) and the
 * header actions of the sheet.
 *
 * Every right pane of a list/detail page starts with this bar (applications, tasks,
 * votes, the meeting detail, the calendar panel, bookings, invoices, the budget). One component owns
 * the size, weight, colour and placement of the kicker, so it looks the same on every
 * page: one line with an ellipsis, centred on the axis of the icon buttons, in a bar of
 * the height of the header controls. The Verwaltung pages use `app-page-header` instead.
 *
 * ```html
 * <app-sheet-bar [kicker]="metaLine()" [bleed]="split()">
 *   <app-button variant="text" [iconOnly]="true">…</app-button>
 *   <app-row-menu … />
 * </app-sheet-bar>
 * ```
 *
 * Give `kickerId` when the kicker is the heading of a section (the calendar panel names
 * the selected day); the kicker is then an `h2` with that id, so a section can point at
 * it with `aria-labelledby`.
 *
 * A kicker with controls in it (the budget breadcrumb) is projected with
 * `appSheetBarKicker` instead of `[kicker]`. It takes the same place and font:
 *
 * ```html
 * <app-sheet-bar>
 *   <nav appSheetBarKicker aria-label="…">…</nav>
 *   <app-button …>…</app-button>
 * </app-sheet-bar>
 * ```
 */
@Component({
  selector: 'app-sheet-bar',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    class: 'sheet-bar',
    '[class.sheet-bar--bleed]': 'bleed()',
  },
  templateUrl: './sheet-bar.component.html',
  styleUrl: './sheet-bar.component.scss',
})
export class SheetBarComponent {
  /** The context line, for example "Studierendenparlament · Di, 29.09.2026". */
  readonly kicker = input<string | null>(null);

  /** Show the kicker as an `h2` with this id (a section heading) instead of a `span`. */
  readonly kickerId = input<string | null>(null);

  /**
   * Let the icon buttons reach into the padding of the sheet, so the glyph of the last
   * button lines up with the end edge of the content. Set it only on a sheet with side
   * padding: without one the bar would make the pane scroll sideways.
   */
  readonly bleed = input(false);

  /** The projected kicker (`appSheetBarKicker`), which replaces the text kicker. */
  protected readonly slotKicker = contentChild(SheetBarKickerDirective);
}
