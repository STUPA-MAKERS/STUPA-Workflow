import { NgTemplateOutlet } from '@angular/common';
import { ChangeDetectionStrategy, Component, contentChild, input, output, TemplateRef } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { LoadState } from '@shared/forms/settings-form';
import { LoadErrorComponent } from '@shared/ui/load-error/load-error.component';
import {
  NoteComponent,
  SkeletonComponent,
} from '@stupa-makers/ui-kit';

/**
 * The states of a page or a section that reads its data first.
 *
 * - `loading`: skeleton lines, or the `#loading` template of the page.
 * - `forbidden`: a warning note with `forbiddenText`. Without the text it shows nothing,
 *   for a section that hides itself without the right.
 * - `error`: an error toast with `errorText` and "Erneut versuchen", which emits `retry`
 *   (`app-load-error`, § 000576). The content area stays empty.
 * - `ok`: the `#content` template.
 *
 * The content is a template, so the page builds its form only once the data is there.
 * The host has `display: contents` and adds no box to the layout of the page.
 *
 * ```html
 * <app-load-state [state]="form.state()" [lines]="3"
 *   [forbiddenText]="'admin.x.forbidden' | t" [errorText]="'admin.x.loadError' | t" (retry)="form.reload()">
 *   <ng-template #content>…</ng-template>
 * </app-load-state>
 * ```
 */
@Component({
  selector: 'app-load-state',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [NgTemplateOutlet, TranslatePipe, NoteComponent, SkeletonComponent, LoadErrorComponent],
  templateUrl: './load-state.component.html',
  styleUrl: './load-state.component.scss',
})
export class LoadStateComponent {
  readonly state = input.required<LoadState>();
  /** The number of skeleton lines while the data loads. */
  readonly lines = input(3);
  /** The text of the `forbidden` note. `null` shows nothing. */
  readonly forbiddenText = input<string | null>(null);
  /** The text of the `error` toast. */
  readonly errorText = input.required<string>();
  /** Load again: the action of the `error` toast, or the end of the offline state. */
  readonly retry = output<void>();

  protected readonly content = contentChild('content', { read: TemplateRef });
  protected readonly loadingTpl = contentChild('loading', { read: TemplateRef });
}
