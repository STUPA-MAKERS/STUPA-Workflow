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
 * Show rendered Markdown for long text that a user typed. Detail views use it.
 *
 * The renderer in `markdown.util` escapes the WHOLE input before it makes any markup.
 * Therefore this component can bypass the Angular sanitizer safely. The HTML holds only
 * the fixed tags of the generator. Encapsulation is off because `[innerHTML]` content
 * never carries the Angular scoping attributes. Every rule uses the `.mdv` namespace.
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
