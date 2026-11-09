import { ChangeDetectionStrategy, Component, input, model, output } from '@angular/core';
import type { Uuid } from '@core/api/models';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  ButtonComponent,
  DialogComponent,
  EmptyStateComponent,
  IconComponent,
  type IconName,
  ScrollFadeDirective,
  SearchPillComponent,
  SkeletonComponent,
} from '@stupa-makers/ui-kit';

/** One choice of the pick dialog. */
export interface PickRow {
  readonly id: Uuid;
  readonly title: string;
  readonly sub: string;
}

/**
 * A dialog that picks one row from a list: "Mit To-Do verknüpfen" (with a search) and
 * "Auf Tagesordnung setzen" (without). The rows are radios, the first one starts picked.
 * The caller reads the rows and acts on `picked`; the dialog only shows them.
 */
@Component({
  selector: 'app-todo-pick-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    TranslatePipe,
    ButtonComponent,
    DialogComponent,
    EmptyStateComponent,
    IconComponent,
    ScrollFadeDirective,
    SearchPillComponent,
    SkeletonComponent,
  ],
  templateUrl: './todo-pick-dialog.component.html',
  styleUrl: './todo-pick-dialog.component.scss',
})
export class TodoPickDialogComponent {
  readonly open = model(false);
  readonly heading = input.required<string>();
  /** The placeholder of the search; empty: no search. */
  readonly searchLabel = input('');
  readonly query = model('');
  readonly listLabel = input.required<string>();
  readonly emptyHeading = input.required<string>();
  readonly submitLabel = input.required<string>();
  readonly submitIcon = input<IconName | null>(null);
  /** `null` while the rows load. */
  readonly rows = input<readonly PickRow[] | null>(null);
  readonly pick = model<Uuid | null>(null);
  readonly busy = input(false);
  readonly picked = output<Uuid>();

  submit(): void {
    const id = this.pick();
    if (id && !this.busy()) this.picked.emit(id);
  }

  cancel(): void {
    this.open.set(false);
  }
}
