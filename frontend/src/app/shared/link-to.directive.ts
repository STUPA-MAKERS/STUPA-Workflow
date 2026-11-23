import { Directive, computed, inject, input } from '@angular/core';
import { Router } from '@angular/router';

/** Tell if an address leaves the app: a Paperless document (§002765). */
export function isExternalUrl(url: string | null | undefined): url is string {
  return !!url && /^https?:\/\//.test(url);
}

/**
 * A link to the address of a linked element (§002765).
 *
 * An address of the app ("/meetings/m-1?item=a-1") opens through the router. An address that
 * leaves the app opens in a new tab.
 */
@Directive({
  selector: 'a[appLinkTo]',
  host: {
    '[attr.href]': 'appLinkTo()',
    '[attr.target]': "external() ? '_blank' : null",
    '[attr.rel]': "external() ? 'noopener' : null",
    '(click)': 'onClick($event)',
  },
})
export class LinkToDirective {
  readonly appLinkTo = input.required<string>();
  /** The address leaves the app. */
  readonly external = computed(() => isExternalUrl(this.appLinkTo()));
  private readonly router = inject(Router);

  /** A plain click on an app address goes through the router; every other click is the browser's. */
  protected onClick(event: MouseEvent): void {
    const modified = event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey;
    if (this.external() || modified) return;
    event.preventDefault();
    void this.router.navigateByUrl(this.appLinkTo());
  }
}
