import { DOCUMENT } from '@angular/common';
import { DestroyRef, Injectable, InjectionToken, inject } from '@angular/core';
import { NavigationEnd, Router } from '@angular/router';
import { SwUpdate } from '@angular/service-worker';
import { PAGE_RELOAD } from '@stupa-makers/ui-kit/pwa';
import { Subscription, filter, firstValueFrom, from, race, timer } from 'rxjs';
import { APP_BUILD_ID } from './build-id';

/** The response header with the build ID of the frontend that the server serves (§ 002150). */
export const APP_VERSION_HEADER = 'X-App-Version';

/** The build ID of the running frontend. A token, so that a test can set it. */
export const APP_BUILD = new InjectionToken<string>('APP_BUILD', {
  providedIn: 'root',
  factory: () => APP_BUILD_ID,
});

/** The build ID that never reloads: a local build or `ng serve`. */
export const DEV_BUILD = 'dev';

/** The session storage key of the last reload, for the loop guard (§ui-kit:002152). */
export const RELOAD_KEY = 'appVersionReload';

/** How long the app does not reload a second time for the same server version (§ui-kit:002152). */
export const RELOAD_GUARD_MS = 10 * 60 * 1000;

/** The longest wait for the service worker before the reload runs anyway. */
export const SW_WAIT_MS = 15_000;

/** The input types that take no typed text, so their focus does not hold the reload. */
const NO_TEXT_INPUTS = new Set([
  'button',
  'checkbox',
  'color',
  'file',
  'hidden',
  'image',
  'radio',
  'range',
  'reset',
  'submit',
]);

/**
 * The reload of the app when the server serves another frontend build (§ui-kit:002151).
 *
 * `appVersionInterceptor` reports the header `X-App-Version` of each API answer. When the
 * value is not the build ID of the running app, the service loads the new version through
 * the service worker (`checkForUpdate`, `activateUpdate`) and reloads the page at once.
 * The app shows no update notice.
 *
 * While a text field has the focus, the reload waits (§ui-kit:002151): it runs at the next page
 * change or at the next reported answer while no text field has the focus, so typed text is
 * not lost.
 *
 * The loop guard (§ui-kit:002152): before a reload, the service writes the server version and the
 * time into the session storage. When the next answer after the reload still reports that
 * version within {@link RELOAD_GUARD_MS}, the service does not reload again. A missing
 * header or the build ID `dev` never reloads.
 *
 * When the cache of the running version is broken (`unrecoverable`), the service reloads at
 * once, because the page cannot load its lazy chunks.
 */
@Injectable({ providedIn: 'root' })
export class AppVersionService {
  private readonly updates = inject(SwUpdate);
  private readonly reloadPage = inject(PAGE_RELOAD);
  private readonly doc = inject(DOCUMENT);
  private readonly router = inject(Router);
  private readonly build = inject(APP_BUILD);
  private readonly subscriptions = new Subscription();
  private started = false;
  private reloading = false;
  /** The server version of a reload that waits for the end of typing. */
  private pending: string | null = null;

  constructor() {
    inject(DestroyRef).onDestroy(() => this.subscriptions.unsubscribe());
  }

  /** Starts the watch of the router and of the service worker. A second call does nothing. */
  init(): void {
    if (this.started) return;
    this.started = true;
    if (this.updates.isEnabled) {
      this.subscriptions.add(this.updates.unrecoverable.subscribe(() => this.reloadPage()));
    }
    this.subscriptions.add(
      this.router.events.pipe(filter((e) => e instanceof NavigationEnd)).subscribe(() => {
        if (this.pending !== null) void this.reload(this.pending);
      }),
    );
  }

  /** Takes the version header of one API answer. */
  report(serverVersion: string | null): void {
    if (!serverVersion || this.build === DEV_BUILD || serverVersion === this.build) return;
    if (this.triedBefore(serverVersion)) return;
    if (this.typing()) {
      this.pending = serverVersion;
      return;
    }
    void this.reload(serverVersion);
  }

  private async reload(serverVersion: string): Promise<void> {
    if (this.reloading) return;
    this.reloading = true;
    this.pending = null;
    this.remember(serverVersion);
    if (this.updates.isEnabled) {
      await withTimeout(
        (async () => {
          await this.updates.checkForUpdate();
          await this.updates.activateUpdate();
        })(),
        SW_WAIT_MS,
      ).catch(() => undefined);
    }
    this.reloadPage();
  }

  /** True while the focus is in a field that takes typed text. */
  private typing(): boolean {
    const el = this.doc.activeElement;
    if (!(el instanceof HTMLElement)) return false;
    if (
      el.isContentEditable ||
      el instanceof HTMLTextAreaElement ||
      el instanceof HTMLSelectElement
    ) {
      return true;
    }
    return el instanceof HTMLInputElement && !NO_TEXT_INPUTS.has(el.type);
  }

  private triedBefore(serverVersion: string): boolean {
    try {
      const raw = this.doc.defaultView?.sessionStorage.getItem(RELOAD_KEY);
      if (!raw) return false;
      const last = JSON.parse(raw) as { version?: unknown; at?: unknown };
      return (
        last.version === serverVersion &&
        typeof last.at === 'number' &&
        Date.now() - last.at < RELOAD_GUARD_MS
      );
    } catch {
      return false;
    }
  }

  private remember(serverVersion: string): void {
    try {
      this.doc.defaultView?.sessionStorage.setItem(
        RELOAD_KEY,
        JSON.stringify({ version: serverVersion, at: Date.now() }),
      );
    } catch {
      /* Without storage the guard is off; the reload still runs. */
    }
  }
}

/** Resolves when `work` ends or after `ms`, whichever comes first. The timer ends with it. */
function withTimeout(work: Promise<unknown>, ms: number): Promise<unknown> {
  return firstValueFrom(race(from(work), timer(ms)));
}
