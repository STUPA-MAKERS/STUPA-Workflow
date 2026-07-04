import {
  ChangeDetectionStrategy,
  Component,
  ViewEncapsulation,
  computed,
  inject,
  input,
} from '@angular/core';
import { DomSanitizer, type SafeHtml } from '@angular/platform-browser';
import { markdownToSafeHtml } from './markdown.util';

/**
 * Rendered Markdown display for user-entered long text (detail views).
 *
 * The renderer escapes the ENTIRE input before generating any markup
 * (`markdown.util`), so bypassing Angular's sanitizer here is safe — the HTML
 * can only contain the generator's fixed tags. Encapsulation is off because
 * `[innerHTML]` content never carries Angular's scoping attributes; all rules
 * are namespaced under `.mdv`.
 */
@Component({
  selector: 'app-markdown-view',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  encapsulation: ViewEncapsulation.None,
  template: `<div class="mdv" [innerHTML]="html()"></div>`,
  styleUrl: './markdown-view.component.scss',
})
export class MarkdownViewComponent {
  private readonly sanitizer = inject(DomSanitizer);
  readonly src = input('');
  protected readonly html = computed<SafeHtml>(() =>
    this.sanitizer.bypassSecurityTrustHtml(markdownToSafeHtml(this.src())),
  );
}
