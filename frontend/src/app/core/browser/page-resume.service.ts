import { DOCUMENT } from '@angular/common';
import { DestroyRef, Injectable, inject } from '@angular/core';
import { Observable, Subject } from 'rxjs';

/** Events of one return (visible, pageshow, online) within this time count once. */
export const RESUME_FOLD_MS = 500;

/**
 * The page comes back to the user: the tab or the PWA was in the background and is visible
 * again (`visibilitychange`), the browser restored it from the back-forward cache
 * (`pageshow` with `persisted`), or the device is online again (`online`).
 *
 * iOS freezes a background PWA and drops its sockets, often without a `close` event, and
 * a socket that comes back delivers none of the events of the gap. A live page therefore
 * opens its socket again and reads its state again on `resume$` (§F/meetings/meetings/001441).
 */
@Injectable({ providedIn: 'root' })
export class PageResumeService {
  private readonly doc = inject(DOCUMENT);
  private readonly resumes = new Subject<void>();
  private hidden: boolean;
  private lastAt = 0;

  /** One value per return of the page. */
  readonly resume$: Observable<void> = this.resumes.asObservable();

  constructor() {
    this.hidden = this.doc.visibilityState === 'hidden';
    const win = this.doc.defaultView;
    const onVisibility = (): void => {
      if (this.doc.visibilityState === 'hidden') {
        this.hidden = true;
        return;
      }
      if (!this.hidden) return;
      this.hidden = false;
      this.emit();
    };
    const onPageShow = (ev: PageTransitionEvent): void => {
      if (ev.persisted) this.emit();
    };
    const onOnline = (): void => this.emit();
    this.doc.addEventListener('visibilitychange', onVisibility);
    win?.addEventListener('pageshow', onPageShow);
    win?.addEventListener('online', onOnline);
    inject(DestroyRef).onDestroy(() => {
      this.doc.removeEventListener('visibilitychange', onVisibility);
      win?.removeEventListener('pageshow', onPageShow);
      win?.removeEventListener('online', onOnline);
    });
  }

  private emit(): void {
    const now = Date.now();
    if (now - this.lastAt < RESUME_FOLD_MS) return;
    this.lastAt = now;
    this.resumes.next();
  }
}
