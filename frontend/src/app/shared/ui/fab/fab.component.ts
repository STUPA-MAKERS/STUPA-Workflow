import { ChangeDetectionStrategy, Component, inject, input, output } from '@angular/core';
import { Router } from '@angular/router';
import { ButtonComponent, IconComponent, type IconName } from '@stupa-makers/ui-kit';

/**
 * The floating main action of a page: one per page, at the bottom end of the content, on
 * every width. It is the "new" action, or
 * "Speichern" (`icon="check"`, `[loading]` while the save runs) on an editor or a settings
 * page. "Speichern" shows only while the page has unsaved changes, and it replaces the
 * "new" action of the page then, so a page never shows two floating buttons.
 *
 * The look is the ui-kit button `variant="fab"`: 56px high, accent surface, the elevated
 * shadow, the icon and the label in one row. The label always shows, also on a phone,
 * because every floating button of the app had its text there too.
 *
 * Position:
 *
 * - Default: fixed at the end edge of the content column, 16px above the bottom of the
 *   window or above the phone bottom bar (`--app-bottom-inset` already holds the bar and
 *   the safe area). The content column is the page column of the shell: its end edge is
 *   the gutter beside a centred column, or the gutter of a wide page.
 * - `contained`: absolute at the bottom end of the nearest positioned ancestor, for a list
 *   pane beside a detail pane (`.ld-pane` is positioned).
 *
 * The button floats over the content, so the end of what scrolls below it keeps room
 * for it: a list pane pads its end by `calc(56px + var(--space-6))`, the admin frame pads
 * a page that holds a fab (`:has(app-fab)`), and a phone page that scrolls as a whole
 * with a footer sets the route data `fab: true` (the shell pads it below the footer).
 *
 * It sits below dialogs, sheets and drawers (`--z-sticky`). A page hides it while a
 * selection bar or a form with its own primary action is open.
 */
@Component({
  selector: 'app-fab',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ButtonComponent, IconComponent],
  host: {
    class: 'fab',
    '[class.fab--contained]': 'contained()',
  },
  template: `<app-button
    variant="fab"
    [ariaLabel]="label()"
    [loading]="loading()"
    [disabled]="disabled()"
    (click)="onClick()"
  >
    <app-icon [name]="icon()" />{{ label() }}
  </app-button>`,
  styleUrl: './fab.component.scss',
})
export class FabComponent {
  private readonly router = inject(Router);

  /** The visible text and the accessible name, for example "Gremium anlegen". */
  readonly label = input.required<string>();
  readonly icon = input<IconName>('plus');
  /** A route to open instead of emitting `activate`. */
  readonly link = input<string | null>(null);
  /** Absolute in the nearest positioned ancestor instead of fixed in the window. */
  readonly contained = input(false);
  /** The action runs, for example a save: the button shows the spinner and takes no click. */
  readonly loading = input(false);
  /** The action cannot run now, for example a save of a form with an error. */
  readonly disabled = input(false);

  /** The button was pressed and it has no `link`. */
  readonly activate = output<void>();

  protected onClick(): void {
    if (this.loading() || this.disabled()) return;
    const link = this.link();
    if (link) void this.router.navigateByUrl(link);
    else this.activate.emit();
  }
}
