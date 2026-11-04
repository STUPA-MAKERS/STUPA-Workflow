import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  input,
  output,
  untracked,
} from '@angular/core';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { ButtonComponent, IconComponent, ListDetailNav, type ListDetailTask } from '@stupa-makers/ui-kit';

/**
 * The head of a form that replaces a detail sheet (a booking, a transfer, an invoice, a
 * captured application): the title, a quiet subtitle, and "Schließen".
 *
 * The host is the `header` of the page, so the page keeps its frame rules (margin,
 * padding, the bottom sheet that brings its own head):
 *
 * ```html
 * <header class="ff__head" appPaneFormHead [heading]="'expenses.add' | t" headingId="bf-title"
 *         [subtitle]="subtitle()" (closed)="close()"></header>
 * ```
 *
 * In the one-view layout (`ListDetailNav.active`) the form docks in the bar of the layout:
 * the bar shows the X and the title as a task (`ListDetailTask`), and the head stays only
 * for screen readers (`pfh--docked`), so the form has no second bar under the bar.
 */
@Component({
  // eslint-disable-next-line @angular-eslint/component-selector -- the host is the header of the page, which keeps its frame rules
  selector: 'header[appPaneFormHead]',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, ButtonComponent, IconComponent],
  host: { '[class.pfh--docked]': 'docked()' },
  templateUrl: './pane-form-head.component.html',
  styleUrl: './pane-form-head.component.scss',
})
export class PaneFormHeadComponent {
  readonly heading = input.required<string>();
  /** The id of the title, for `aria-labelledby` of the form. */
  readonly headingId = input<string | null>(null);
  /** A quiet line below the title (the thing the form edits). Empty shows none. */
  readonly subtitle = input<string | null | undefined>(null);
  /** "Schließen" was pressed. */
  readonly closed = output<void>();

  private readonly nav = inject(ListDetailNav, { optional: true });
  private readonly i18n = inject(I18nService);

  /** The bar of the one-view layout shows the X and the title. */
  protected readonly docked = computed(() => !!this.nav?.active());

  constructor() {
    const nav = this.nav;
    if (!nav) return;
    let mine: ListDetailTask | null = null;
    const release = () => {
      if (mine && nav.task() === mine) nav.task.set(null);
      mine = null;
    };
    effect(() => {
      if (!this.docked()) {
        untracked(release);
        return;
      }
      const task: ListDetailTask = {
        title: this.heading(),
        cancelLabel: this.i18n.translate('action.close'),
        cancel: () => this.closed.emit(),
      };
      untracked(() => {
        mine = task;
        nav.task.set(task);
      });
    });
    inject(DestroyRef).onDestroy(release);
  }
}
