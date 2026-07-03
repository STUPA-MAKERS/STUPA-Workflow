import { Injectable, inject } from '@angular/core';
import { SwUpdate, type VersionReadyEvent } from '@angular/service-worker';
import { filter, concatMap } from 'rxjs';
import { interval, fromEvent } from 'rxjs';
import { I18nService } from '@core/i18n/i18n.service';
import { ToastService } from '@stupa-makers/ui-kit';

/**
 * PWA update flow: when the service worker reports a new app version
 * (`VERSION_READY`), it is activated and a persistent toast prompts the required
 * reload. Without a SW (dev mode, old browsers) `isEnabled` is false and nothing
 * happens.
 *
 * Active update detection: the service checks for updates:
 * - after a short delay at app start (to break the bootstrap deadlock)
 * - at regular intervals (every 5 minutes)
 * - when the app comes to the foreground (focus event)
 * → users see the "new version available" toast promptly after deployments.
 *
 * BOOTSTRAP DEADLOCK FIX: old versions do not have the new polling logic.
 * Without an initial update check at start they would never load the new version
 * and thus never get the polling logic. So checkForUpdate() is called after a
 * short delay to ensure the service worker is already registered.
 */
@Injectable({ providedIn: 'root' })
export class SwUpdateService {
  private readonly updates = inject(SwUpdate);
  private readonly toast = inject(ToastService);
  private readonly i18n = inject(I18nService);

  init(): void {
    if (!this.updates.isEnabled) return;

    // Listen for updates ready to activate.
    this.updates.versionUpdates
      .pipe(filter((e): e is VersionReadyEvent => e.type === 'VERSION_READY'))
      .subscribe(() => {
        void this.updates.activateUpdate().then(() => {
          this.toast.show(this.i18n.translate('pwa.updateReady'), 'info', 0);
        });
      });

    // BOOTSTRAP FIX: wait a short while (1 second) so the service worker has time
    // to register before we run the first update check. The registerWhenStable
    // strategy registers the SW after 30s or once the app is stable; this delay
    // gives the SW time to register before we call checkForUpdate().
    setTimeout(() => {
      this.checkForUpdatesOnce();
      this.setupPeriodicPolling();
      this.setupFocusListener();
    }, 1000);
  }

  private checkForUpdatesOnce(): void {
    // Try an update check IMMEDIATELY (once the SW is registered). This breaks
    // the deadlock where old versions without polling would never load the new
    // version that has the polling logic.
    void this.updates.checkForUpdate().catch(() => {
      // Ignore errors and carry on.
    });
  }

  private setupPeriodicPolling(): void {
    // Check for updates every 5 minutes (300,000 ms).
    interval(5 * 60 * 1000)
      .pipe(concatMap(() => this.updates.checkForUpdate()))
      .subscribe();
  }

  private setupFocusListener(): void {
    // Check for updates when the app comes to the foreground.
    if (typeof window !== 'undefined') {
      fromEvent(window, 'focus')
        .pipe(concatMap(() => this.updates.checkForUpdate()))
        .subscribe();
    }
  }
}
