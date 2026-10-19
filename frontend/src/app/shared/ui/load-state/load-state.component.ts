import { NgTemplateOutlet } from '@angular/common';
import { ChangeDetectionStrategy, Component, contentChild, input, TemplateRef } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { LoadState } from '@shared/forms/settings-form';
import { NoteComponent } from '../note/note.component';
import { SkeletonComponent } from '../skeleton/skeleton.component';

/**
 * The states of a page or a section that reads its data first.
 *
 * - `loading`: skeleton lines, or the `#loading` template of the page.
 * - `forbidden`: a warning note with `forbiddenText`. Without the text it shows nothing,
 *   for a section that hides itself without the right.
 * - `error`: an error note with `errorText`.
 * - `ok`: the `#content` template.
 *
 * The content is a template, so the page builds its form only once the data is there.
 * The host has `display: contents` and adds no box to the layout of the page.
 *
 * ```html
 * <app-load-state [state]="form.state()" [lines]="3"
 *   [forbiddenText]="'admin.x.forbidden' | t" [errorText]="'admin.x.loadError' | t">
 *   <ng-template #content>…</ng-template>
 * </app-load-state>
 * ```
 */
@Component({
  selector: 'app-load-state',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [NgTemplateOutlet, TranslatePipe, NoteComponent, SkeletonComponent],
  templateUrl: './load-state.component.html',
  styleUrl: './load-state.component.scss',
})
export class LoadStateComponent {
  readonly state = input.required<LoadState>();
  /** The number of skeleton lines while the data loads. */
  readonly lines = input(3);
  /** The text of the `forbidden` note. `null` shows nothing. */
  readonly forbiddenText = input<string | null>(null);
  /** The text of the `error` note. */
  readonly errorText = input.required<string>();

  protected readonly content = contentChild('content', { read: TemplateRef });
  protected readonly loadingTpl = contentChild('loading', { read: TemplateRef });
}
