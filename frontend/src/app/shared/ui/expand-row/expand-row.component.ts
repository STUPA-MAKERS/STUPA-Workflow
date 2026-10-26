import {
  afterRenderEffect,
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  inject,
  input,
  model,
  output,
} from '@angular/core';
import { ButtonComponent, IconComponent, ListItemComponent } from '@stupa-makers/ui-kit';

let nextId = 0;

/**
 * A list row that opens its content below itself: the row of a role, a gremium, a user, an
 * audit entry or a webhook.
 *
 * The head is an `app-list-item` (title, `[status]`, `sub` / `[sub]`, `[lead]`, controls in
 * `[trail]`). The content (the default slot) shows below the head on the same surface, so the
 * open row reads as one block in its row group. The content starts at the left edge of the
 * title, also when the row has a `[lead]` (an avatar, an icon), so the open row has one text
 * column. The head and the content have the same horizontal inset (`--space-5`), which
 * matches the vertical inset of the text in the 64px head.
 *
 * `toggle="row"` (the default): a press anywhere on the head opens or closes the row, and the
 * chevron at the end only shows the state. The title button of the list item carries
 * `aria-expanded`.
 *
 * `toggle="chevron"`: a press on the head emits `activate` (for example "edit"), and the
 * chevron is its own button that opens or closes the row. The chevron button carries
 * `aria-expanded`, because the head does not open anything.
 *
 * ```html
 * <ul class="rowgroup">
 *   <li><app-expand-row [title]="r.name" [(open)]="r.open">
 *     <app-status-text status kind="muted">fest</app-status-text>
 *     <app-row-menu trail … />
 *     <div class="body">…</div>
 *   </app-expand-row></li>
 * </ul>
 * ```
 */
@Component({
  selector: 'app-expand-row',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ButtonComponent, IconComponent, ListItemComponent],
  host: { '[class.xr--open]': 'open()' },
  templateUrl: './expand-row.component.html',
  styleUrl: './expand-row.component.scss',
})
export class ExpandRowComponent {
  /** The name of the thing. */
  readonly title = input.required<string>();
  /** A plain sub line. */
  readonly sub = input<string | null>(null);
  /** What opens the row: a press on the head, or only the chevron button. */
  readonly toggle = input<'row' | 'chevron'>('row');
  /** The accessible name of the chevron button (`toggle="chevron"` only). */
  readonly toggleLabel = input('');
  /** The content shows. */
  readonly open = model(false);
  /** A press on the head with `toggle="chevron"`. */
  readonly activate = output<void>();

  protected readonly bodyId = `xr-body-${nextId++}`;

  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);

  constructor() {
    afterRenderEffect({
      earlyRead: () => {
        if (!this.open()) return null;
        const el = this.host.nativeElement;
        const text = el.querySelector('.li__body');
        return text ? Math.round(text.getBoundingClientRect().left - el.getBoundingClientRect().left) : null;
      },
      write: (inset) => {
        const x = inset();
        if (x) this.host.nativeElement.style.setProperty('--xr-inset', `${x}px`);
      },
    });
  }

  protected onHead(): void {
    if (this.toggle() === 'row') this.flip();
    else this.activate.emit();
  }

  protected flip(): void {
    this.open.update((v) => !v);
  }
}
