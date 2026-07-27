import { Injectable, inject } from '@angular/core';
import { SwUpdate, type VersionReadyEvent } from '@angular/service-worker';
import { filter, concatMap } from 'rxjs';
import { interval, fromEvent } from 'rxjs';
import { I18nService } from '@core/i18n/i18n.service';
import { ToastService } from '@stupa-makers/ui-kit';

/**
 * PWA update flow. When the service worker reports a new app version
 * (`VERSION_READY`), the service activates it. A persistent toast then asks for the
 * necessary reload. Without a service worker (dev mode, old browsers) `isEnabled` is
 * false and nothing happens.
 *
 * The service looks for updates at three moments.
 * - After a short delay at app start. This breaks the bootstrap deadlock.
 * - Every 5 minutes.
 * - When the app comes to the foreground, on the focus event.
 *
 * Users therefore see the "new version available" toast soon after a deployment.
 *
 * BOOTSTRAP DEADLOCK FIX: old versions do not have the new polling logic. Without an
 * update check at start they never load the new version, and so they never get the
 * polling logic. The service calls checkForUpdate() after a short delay, when the
 * service worker is already registered.
 */
@Injectable({ providedIn: 'root' })
export class SwUpdateService {
  private readonly updates = inject(SwUpdate);
  private readonly toast = inject(ToastService);
  private readonly i18n = inject(I18nService);

  init(): void {
    if (!this.updates.isEnabled) return;

    this.updates.versionUpdates
      .pipe(filter((e): e is VersionReadyEvent => e.type === 'VERSION_READY'))
      .subscribe(() => {
        void this.updates.activateUpdate().then(() => {
          this.toast.show(this.i18n.translate('pwa.updateReady'), 'info', 0);
        });
      });

    // BOOTSTRAP FIX: wait 1 second, so the service worker has time to register before
    // the first update check. The registerWhenStable strategy registers the service
    // worker after 30 seconds or once the app is stable. This delay gives it time to
    // register before the call to checkForUpdate().
    setTimeout(() => {
      this.checkForUpdatesOnce();
      this.setupPeriodicPolling();
      this.setupFocusListener();
    }, 1000);
  }

  private checkForUpdatesOnce(): void {
    // Run an update check as soon as the service worker is registered. This breaks the
    // deadlock where an old version without polling never loads the new version that
    // carries the polling logic.
    void this.updates.checkForUpdate().catch(() => {
      // Ignore the error and carry on.
    });
  }

  private setupPeriodicPolling(): void {
    interval(5 * 60 * 1000)
      .pipe(concatMap(() => this.updates.checkForUpdate()))
      .subscribe();
  }

  private setupFocusListener(): void {
    if (typeof window !== 'undefined') {
      fromEvent(window, 'focus')
        .pipe(concatMap(() => this.updates.checkForUpdate()))
        .subscribe();
    }
  }
}
