import {
  ChangeDetectionStrategy,
  Component,
  ViewEncapsulation,
  computed,
  inject,
  input,
} from '@angular/core';
import { DomSanitizer, type SafeHtml } from '@angular/platform-browser';
import { Router } from '@angular/router';
import { routeInternalLink } from './internal-link';
import { defaultImageSrc, markdownToSafeHtml } from './markdown.util';

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
  host: { '(click)': 'onClick($event)' },
  template: `<div class="mdv" [innerHTML]="html()"></div>`,
  styleUrl: './markdown-view.component.scss',
})
export class MarkdownViewComponent {
  private readonly sanitizer = inject(DomSanitizer);
  private readonly router = inject(Router, { optional: true });
  readonly src = input('');
  /** The number of levels that a heading moves down (3: `#` renders as h4). */
  readonly headingOffset = input(3);
  /** The URL of an image from its uuid. `null` shows the alt text (anonymous views). */
  readonly imageSrc = input<((id: string) => string) | null>(defaultImageSrc);
  protected readonly html = computed<SafeHtml>(() =>
    this.sanitizer.bypassSecurityTrustHtml(
      markdownToSafeHtml(this.src(), {
        headingOffset: this.headingOffset(),
        imageSrc: this.imageSrc(),
      }),
    ),
  );

  /** An internal link navigates through the router, without a reload. */
  protected onClick(event: MouseEvent): void {
    routeInternalLink(event, this.router);
  }
}
