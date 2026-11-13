import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  Injector,
  ViewEncapsulation,
  computed,
  effect,
  inject,
  input,
  signal,
  untracked,
} from '@angular/core';
import { DomSanitizer, type SafeHtml } from '@angular/platform-browser';
import { Router } from '@angular/router';
import { I18nService } from '../../core/i18n/i18n.service';
import { DocumentViewerComponent, type ShownDocument } from './document-viewer.component';
import { routeInternalLink } from './internal-link';
import { MediaApiService } from './media-api.service';
import { defaultImageSrc, documentIdsIn, markdownToSafeHtml } from './markdown.util';

/** The default PDF URL: the canonical path, served to any authenticated session. */
export const defaultDocumentSrc = (id: string): string => `/api/media/documents/${id}`;

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
  imports: [DocumentViewerComponent],
  host: { '(click)': 'onClick($event)' },
  template: `<div class="mdv" [innerHTML]="html()"></div>
    @if (shown()) {
      <app-document-viewer [(doc)]="shown" />
    }`,
  styleUrl: './markdown-view.component.scss',
})
export class MarkdownViewComponent {
  private readonly sanitizer = inject(DomSanitizer);
  private readonly router = inject(Router, { optional: true });
  private readonly i18n = inject(I18nService);
  readonly src = input('');
  /** The number of levels that a heading moves down (3: `#` renders as h4). */
  readonly headingOffset = input(3);
  /** The URL of an image from its uuid. `null` shows the alt text (anonymous views). */
  readonly imageSrc = input<((id: string) => string) | null>(defaultImageSrc);
  /**
   * The URL of an embedded PDF from its uuid (spec 000863). The reference then shows as a
   * file badge that opens the PDF in the overlay. `null` shows the plain name.
   */
  readonly documentSrc = input<((id: string) => string) | null>(defaultDocumentSrc);

  /** The page counts of the shown PDFs, by uuid, as their info routes answer. */
  private readonly pages = signal<Readonly<Record<string, number>>>({});
  /** The PDF in the overlay. */
  protected readonly shown = signal<ShownDocument | null>(null);
  private readonly injector = inject(Injector);
  private readonly destroyRef = inject(DestroyRef);

  constructor() {
    effect(() => {
      const src = this.documentSrc();
      const ids = src ? documentIdsIn(this.src()) : [];
      const known = untracked(this.pages);
      ids.filter((id) => !(id in known)).forEach((id) => this.loadPages(id, src!(id)));
    });
  }

  private loadPages(id: string, url: string): void {
    const sub = this.injector
      .get(MediaApiService)
      .documentInfo(url)
      .subscribe({
        next: (info) => this.pages.update((p) => ({ ...p, [id]: info.pages })),
        error: () => undefined,
      });
    this.destroyRef.onDestroy(() => sub.unsubscribe());
  }

  protected readonly html = computed<SafeHtml>(() =>
    this.sanitizer.bypassSecurityTrustHtml(
      markdownToSafeHtml(this.src(), {
        headingOffset: this.headingOffset(),
        imageSrc: this.imageSrc(),
        blackout: {
          mark: this.i18n.translate('markdown.blackout.mark'),
          bar: this.i18n.translate('markdown.blackout.bar'),
        },
        documents: this.documentSrc()
          ? {
              pages: this.pages(),
              pagesText: (n) =>
                n === 1
                  ? this.i18n.translate('markdown.document.page')
                  : this.i18n.translate('markdown.document.pages', { n }),
              label: (name) => this.i18n.translate('markdown.document.open', { name }),
            }
          : null,
      }),
    ),
  );

  /** A PDF badge opens the overlay; an internal link navigates through the router. */
  protected onClick(event: MouseEvent): void {
    const badge = (event.target as Element | null)?.closest?.('button.mdv__doc');
    const src = this.documentSrc();
    const id = badge?.getAttribute('data-doc');
    if (badge && src && id) {
      event.preventDefault();
      const name = badge.querySelector('.mdv__doc-name')?.textContent ?? 'PDF';
      this.shown.set({ name, url: src(id) });
      return;
    }
    routeInternalLink(event, this.router);
  }
}
