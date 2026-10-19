import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { ButtonComponent, IconComponent } from '@stupa-makers/ui-kit';

/**
 * The head of a form that replaces a detail sheet (a booking, a transfer, an invoice, a
 * captured application): the title, a quiet subtitle, and "Schließen".
 *
 * The host is the `header` of the page, so the page keeps its frame rules (margin,
 * padding, the rule below it, the bottom sheet that brings its own head):
 *
 * ```html
 * <header class="ff__head" appPaneFormHead [heading]="'expenses.add' | t" headingId="bf-title"
 *         [subtitle]="subtitle()" (closed)="close()"></header>
 * ```
 */
@Component({
  // eslint-disable-next-line @angular-eslint/component-selector -- the host is the header of the page, which keeps its frame rules
  selector: 'header[appPaneFormHead]',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslatePipe, ButtonComponent, IconComponent],
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
}
