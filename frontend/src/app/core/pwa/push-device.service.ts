import { DOCUMENT } from '@angular/common';
import { Injectable, inject } from '@angular/core';
import { SwPush } from '@angular/service-worker';
import { IS_INSTALLED_APP } from '@stupa-makers/ui-kit/pwa';
import { firstValueFrom } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import type { PushDevice } from '@core/api/models';

/**
 * Whether this device can take push (§F/collaboration/notifications/002500):
 * - `ready`: the browser has push and the service worker runs.
 * - `install`: an iPhone or iPad without the app on the home screen; Safari offers push
 *   only to an installed web app.
 * - `blocked`: the person blocked notifications for the site in the browser.
 * - `unsupported`: no push in this browser, or no service worker (dev build).
 */
export type PushSupport = 'ready' | 'install' | 'blocked' | 'unsupported';

/** An iPhone, iPod or iPad, also an iPad that reports itself as a Mac. */
export function isAppleMobile(nav: Navigator): boolean {
  return (
    /iPad|iPhone|iPod/.test(nav.userAgent) ||
    (nav.platform === 'MacIntel' && nav.maxTouchPoints > 1)
  );
}

/** A short device name for the device list, from the user agent. */
export function deviceLabel(userAgent: string): string {
  const os = [
    ['iPhone', 'iPhone'],
    ['iPad', 'iPad'],
    ['Android', 'Android'],
    ['Windows', 'Windows'],
    ['Mac OS', 'Mac'],
    ['CrOS', 'ChromeOS'],
    ['Linux', 'Linux'],
  ].find(([needle]) => userAgent.includes(needle))?.[1];
  const browser = [
    ['Edg/', 'Edge'],
    ['Firefox/', 'Firefox'],
    ['Chrome/', 'Chrome'],
    ['Safari/', 'Safari'],
  ].find(([needle]) => userAgent.includes(needle))?.[1];
  return [browser, os].filter((part) => !!part).join(' · ');
}

/**
 * The push subscription of this device: support, the switch and the server row.
 *
 * The Angular service worker owns the subscription (`SwPush`). Switching on asks the browser
 * for the permission (only after a tap, which iOS requires), subscribes with the public key
 * of the platform and stores the subscription on the server. Switching off unsubscribes and
 * removes the row. This device is the row whose endpoint equals the current subscription.
 */
@Injectable({ providedIn: 'root' })
export class PushDeviceService {
  /** Absent without `provideServiceWorker` (unit tests): then nothing can take push. */
  private readonly swPush = inject(SwPush, { optional: true });
  private readonly api = inject(ApiClient);
  private readonly document = inject(DOCUMENT);
  private readonly installed = inject(IS_INSTALLED_APP);

  /** What this device can do now. */
  support(): PushSupport {
    const win = this.document.defaultView;
    const hasPush = !!win && 'PushManager' in win && 'Notification' in win;
    if (!hasPush || !this.swPush?.isEnabled) {
      return win && isAppleMobile(win.navigator) && !this.installed() ? 'install' : 'unsupported';
    }
    return win.Notification.permission === 'denied' ? 'blocked' : 'ready';
  }

  /** The endpoint of the subscription of this device, or `null`. */
  async endpoint(): Promise<string | null> {
    if (!this.swPush?.isEnabled) return null;
    const sub = await firstValueFrom(this.swPush.subscription);
    return sub?.endpoint ?? null;
  }

  /** Subscribe this device and store it on the server; the browser asks first. */
  async enable(): Promise<PushDevice> {
    if (!this.swPush?.isEnabled) throw new Error('push unavailable');
    const { publicKey } = await firstValueFrom(this.api.getPushKey());
    const sub = await this.swPush.requestSubscription({ serverPublicKey: publicKey });
    const json = sub.toJSON();
    return firstValueFrom(
      this.api.addPushDevice({
        endpoint: sub.endpoint,
        keys: { p256dh: json.keys?.['p256dh'] ?? '', auth: json.keys?.['auth'] ?? '' },
        label: deviceLabel(this.document.defaultView?.navigator.userAgent ?? ''),
      }),
    );
  }

  /** Unsubscribe this device and remove its row, when there is one. */
  async disable(device: PushDevice | undefined): Promise<void> {
    if (device) await firstValueFrom(this.api.removePushDevice(device.id));
    if (this.swPush?.isEnabled) await this.swPush.unsubscribe().catch(() => undefined);
  }
}
