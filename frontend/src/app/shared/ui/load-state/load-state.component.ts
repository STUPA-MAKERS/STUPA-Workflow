import { NgTemplateOutlet } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, contentChild, input, output, type Signal, TemplateRef } from '@angular/core';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { LoadState } from '@shared/forms/settings-form';
import { LoadErrorComponent } from '@shared/ui/load-error/load-error.component';
import {
  NoteComponent,
  SkeletonComponent,
} from '@stupa-makers/ui-kit';

/**
 * The state of a list page from its two signals: `loading` while the read runs, then `error`
 * after a failed read, else `ok` (§ S/frontend/angular/000632).
 */
export function loadStateOf(loading: Signal<boolean>, failed: Signal<boolean>): Signal<LoadState> {
  return computed(() => (loading() ? 'loading' : failed() ? 'error' : 'ok'));
}

/**
 * The states of a page or a section that reads its data first.
 *
 * - `loading`: skeleton lines, or the `#loading` template of the page.
 * - `forbidden`: a warning note with `forbiddenText`. Without the text it shows nothing,
 *   for a section that hides itself without the right.
 * - `error`: an error toast with `errorText` and "Erneut versuchen", which emits `retry`
 *   (`app-load-error`, § 000576). The content area stays empty. With `keepContent` the
 *   `#content` template shows too: a list keeps the rows it had, or shows its empty state.
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
  /**
   * Show `#content` in the `error` state too. For a list, which keeps the rows that it showed
   * before the error and shows its empty state without them (§ 000576). A form that needs the
   * data to build its fields leaves it off.
   */
  readonly keepContent = input(false);
  /** Load again: the action of the `error` toast, or the end of the offline state. */
  readonly retry = output<void>();

  protected readonly content = contentChild('content', { read: TemplateRef });
  protected readonly loadingTpl = contentChild('loading', { read: TemplateRef });
}
