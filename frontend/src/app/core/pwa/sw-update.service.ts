import { DOCUMENT } from '@angular/common';
import { Injectable, InjectionToken, inject, signal } from '@angular/core';
import { SwUpdate, type VersionEvent } from '@angular/service-worker';
import { type Observable, catchError, concatMap, defer, fromEvent, interval, of } from 'rxjs';

/** Reloads the page. A token, so that a test can replace the reload. */
export const PAGE_RELOAD = new InjectionToken<() => void>('PAGE_RELOAD', {
  providedIn: 'root',
  factory: pageReloadFactory,
});

/** The default `PAGE_RELOAD`: `document.location.reload()` of the injected document. */
export function pageReloadFactory(): () => void {
  const doc = inject(DOCUMENT);
  return () => doc.location.reload();
}

/**
 * PWA update flow. Without a service worker (dev mode, old browsers) `isEnabled` is
 * false and nothing happens.
 *
 * - `VERSION_READY`: the new version is in the cache. The service does NOT call
 *   `activateUpdate()`. Activation without a reload lets the old JS run against the new
 *   cache, and a lazy chunk of the old build is then missing (the flow editor showed new
 *   ops as unknown). The service sets `updateReady`, and `SwUpdatePromptComponent` shows
 *   a persistent prompt with a reload button. `reload()` activates the update directly
 *   before the reload, so the reload loads the new version. The app
 *   has no global record of unsaved work (no dirty or CanDeactivate guard), so the
 *   service never reloads without the consent of the user.
 * - `VERSION_INSTALLATION_FAILED`: the service ignores it. The next check tries again.
 * - `unrecoverable`: the cache of the running version is broken, so the page cannot load
 *   its lazy chunks. The service reloads the page at once.
 *
 * The service looks for updates at three moments.
 * - After a short delay at app start. This breaks the bootstrap deadlock.
 * - Every 5 minutes.
 * - When the app comes to the foreground, on the focus event.
 *
 * A failed check (offline, a server error) is ignored. Each check catches its own error,
 * so the polling stream and the focus stream never complete because of one failure.
 *
 * BOOTSTRAP DEADLOCK FIX: old versions do not have the new polling logic. Without an
 * update check at start they never load the new version, and so they never get the
 * polling logic. The service calls checkForUpdate() after a short delay, when the
 * service worker is already registered.
 */
@Injectable({ providedIn: 'root' })
export class SwUpdateService {
  private readonly updates = inject(SwUpdate);
  private readonly reloadPage = inject(PAGE_RELOAD);

  private readonly _updateReady = signal(false);
  /** True when a new version is in the cache and a reload loads it. */
  readonly updateReady = this._updateReady.asReadonly();

  /**
   * The first update check waits 1 second, so the service worker has time to register
   * (registerWhenStable registers after 30 seconds or once the app is stable).
   */
  init(): void {
    if (!this.updates.isEnabled) return;

    this.updates.versionUpdates.subscribe((e) => this.onVersionEvent(e));
    this.updates.unrecoverable.subscribe(() => void this.reload());

    setTimeout(() => {
      this.safeCheck().subscribe();
      interval(5 * 60 * 1000)
        .pipe(concatMap(() => this.safeCheck()))
        .subscribe();
      fromEvent(window, 'focus')
        .pipe(concatMap(() => this.safeCheck()))
        .subscribe();
    }, 1000);
  }

  /**
   * Reload the page, so the browser loads the version that the service worker holds.
   * When an update is ready, the service first activates it (the documented Angular
   * pattern), so the reload is sure to get the new version. A failed activation is
   * ignored: the reload still runs.
   */
  async reload(): Promise<void> {
    if (this._updateReady()) {
      try {
        await this.updates.activateUpdate();
      } catch {
        // Reload anyway: the service worker serves the version it holds.
      }
    }
    this.reloadPage();
  }

  /**
   * Other version events need no action, because after a failed installation the next check tries
   * again.
   */
  private onVersionEvent(e: VersionEvent): void {
    if (e.type === 'VERSION_READY') this._updateReady.set(true);
  }

  /**
   * One update check that never errors. `defer` also catches a synchronous throw. A
   * rejected check gives `false`, so the stream that runs the checks stays alive.
   */
  private safeCheck(): Observable<boolean> {
    return defer(() => this.updates.checkForUpdate()).pipe(catchError(() => of(false)));
  }
}
