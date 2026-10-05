import {
  ChangeDetectionStrategy,
  Component,
  computed,
  type ElementRef,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { RouterLink, type QueryParamsHandling } from '@angular/router';

/**
 * One row of a list: a lead, a title with a sub line, and a trailing slot.
 *
 * The whole row is the target, but only the title is the control: a link when `link` is
 * set, else a button that emits `activate`. The control stretches over the row, so a
 * click anywhere on the row opens it. Enter (and Space for the button) open it from the
 * keyboard. Controls in the trailing slot (a row menu, a delete button) sit above the
 * stretched area and keep their own click.
 *
 * The title is one line with an ellipsis and always carries the full text as `title`. The
 * sub line is also one line with an ellipsis, from the `sub` input and from the `[sub]`
 * slot (a status in the slot is inline text). The stretched title covers the sub line, so
 * a tooltip on the sub line would never show. When the sub line is cut, the title tooltip
 * shows the full sub line as a second line.
 *
 * ```html
 * <app-list-item [title]="a.title" [selected]="a.id === selectedId()" (activate)="open(a)">
 *   <span sub><app-status-text kind="warn">In Prüfung</app-status-text> · Förderantrag</span>
 *   <span trail class="mono">1.250,00 €</span>
 * </app-list-item>
 * ```
 *
 * Slots: `[lead]` (an avatar for a person, an icon or a date block; never initials for a
 * thing), `[status]` (a status right after the title, on the title line; the title gets
 * the ellipsis first), `[sub]` and `[trail]`. Set `--li-hover` on the host to change the
 * hover surface (for example in a row group on surface 2), `--li-color` to change the
 * text colour (for example a muted row of the past), `--li-sub-color` to change the colour
 * of the sub line and `--li-radius` to match the corners of a row group.
 */
@Component({
  selector: 'app-list-item',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink],
  templateUrl: './list-item.component.html',
  styleUrl: './list-item.component.scss',
})
export class ListItemComponent {
  /**
   * The name of the thing. Shown on one line (two with `wrap`); the full text is in the
   * `title` attribute.
   */
  readonly title = input.required<string>();
  /** A plain sub line. Use the `[sub]` slot for a sub line with a status or markup. */
  readonly sub = input<string | null>(null);
  /** A router link. Without it the title is a button that emits `activate`. */
  readonly link = input<string | readonly unknown[] | null>(null);
  /**
   * What the link does with the current query params. `preserve` keeps them, for
   * example the filters of a list whose rows open a detail beside it.
   */
  readonly linkQueryParamsHandling = input<QueryParamsHandling>('');
  /** The row is the one open in the detail pane. */
  readonly selected = input(false);
  /**
   * The title may take two lines before it gets the ellipsis. For a narrow list where
   * the end of a long title tells the rows apart (meetings on a phone).
   */
  readonly wrap = input(false);

  /** The row was opened by a click, Enter or Space. Also emitted for a link. */
  readonly activate = output<void>();

  private readonly subLine = viewChild.required<ElementRef<HTMLElement>>('subLine');
  /** The full text of the sub line while it is cut, else null. */
  protected readonly subTip = signal<string | null>(null);
  /** The `title` of the control: the title, and the sub line when it is cut. */
  protected readonly tooltip = computed(() => {
    const sub = this.subTip();
    return sub ? `${this.title()}\n${sub}` : this.title();
  });

  /** Measures the sub line when the pointer enters the row, before the tooltip shows. */
  protected measureSub(): void {
    const el = this.subLine().nativeElement;
    const cut = el.scrollWidth > el.clientWidth;
    this.subTip.set(cut ? (el.textContent ?? '').replace(/\s+/g, ' ').trim() || null : null);
  }
}
