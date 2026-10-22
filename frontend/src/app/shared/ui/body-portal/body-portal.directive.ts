import { DOCUMENT } from '@angular/common';
import { Directive, ElementRef, OnDestroy, OnInit, inject } from '@angular/core';

/**
 * Moves its host to the end of `document.body` while it lives, and removes it there when
 * Angular destroys it.
 *
 * Use it on a dialog that a component renders inside a scroll container. `appScrollFade`
 * puts a `mask-image` on a container that overflows, and a mask clips every descendant,
 * also a `position: fixed` one. The backdrop and the pane of a dialog inside such a
 * container then paint only inside the container: the agenda of a long meeting turned
 * dark and "To-Do anlegen" showed no dialog.
 *
 * ```html
 * <app-confirm-dialog appBodyPortal [open]="…" />
 * ```
 */
@Directive({
  selector: '[appBodyPortal]',
  standalone: true,
})
export class BodyPortalDirective implements OnInit, OnDestroy {
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly doc = inject(DOCUMENT);

  ngOnInit(): void {
    this.doc.body.appendChild(this.host.nativeElement);
  }

  /** The view that declared the host may not remove it: it is no longer its child. */
  ngOnDestroy(): void {
    this.host.nativeElement.remove();
  }
}
