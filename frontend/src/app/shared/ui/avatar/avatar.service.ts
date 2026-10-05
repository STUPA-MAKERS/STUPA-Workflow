import { DestroyRef, Injectable, computed, inject, signal } from '@angular/core';
import { API_BASE_URL } from '@core/api/api.config';
import { BrandingService } from '@core/branding/branding.service';

/** The principal of an avatar: a principal id, or `'me'` for the logged-in user. */
export type AvatarPrincipal = string;

/**
 * How long a failed image stays failed, in milliseconds (10 min). After that the avatar
 * asks again. The per-user rate limit counts per hour, so a retry after a 429 does not
 * start a storm.
 */
export const AVATAR_RETRY_MS = 10 * 60 * 1000;

/**
 * The image URLs of the person avatars and the ids without an image.
 *
 * The API proxies Gravatar (`GET /principals/{id}/avatar`): the browser loads the image
 * from our own origin, so the CSP stays `img-src 'self'` and Gravatar never sees the
 * viewer. A 404 means "no Gravatar"; the avatar then keeps the initials. This service
 * remembers a failed id for `AVATAR_RETRY_MS`, so a list with the same person in many
 * rows, or a second visit of the page, asks only once in that period.
 *
 * The `<img>` error event does not tell a 404 from a 429 (rate limit) or a network
 * error. Thus the entry expires and the avatar asks again: a transient error heals
 * itself in a long-running tab, as the server cache of a failed fetch does. A repeated
 * 404 costs almost nothing, because the browser keeps the 404 (`Cache-Control`).
 * The set lives in memory only. Login and logout load the page again, so the entries
 * of one user (also `'me'`) never reach the next one.
 *
 * The admin switch `gravatarEnabled` of the public site config turns the images off.
 * Until the config is loaded no image loads, so the switch never comes too late.
 */
@Injectable({ providedIn: 'root' })
export class AvatarService {
  private readonly base = inject(API_BASE_URL);
  private readonly branding = inject(BrandingService);

  private readonly failed = signal<ReadonlySet<string>>(new Set());
  /** One timer per failed id. It removes the id when `AVATAR_RETRY_MS` is over. */
  private readonly retryTimers = new Map<string, ReturnType<typeof setTimeout>>();

  constructor() {
    inject(DestroyRef).onDestroy(() => {
      for (const timer of this.retryTimers.values()) clearTimeout(timer);
      this.retryTimers.clear();
    });
  }

  /** Images are on: the config is loaded and the admin switch is on. */
  readonly enabled = computed(() => this.branding.loaded() && this.branding.gravatarEnabled());

  /**
   * The image URL of a principal at `px` CSS pixels, or `null` for the initials.
   *
   * The request asks for twice the size, for sharp images on a high-density screen.
   */
  url(principal: AvatarPrincipal | null | undefined, px: number): string | null {
    if (!principal || !this.enabled() || this.failed().has(principal)) return null;
    return `${this.base}/principals/${encodeURIComponent(principal)}/avatar?s=${px * 2}`;
  }

  /**
   * The image of `principal` failed to load (404, 429, network): use the initials.
   *
   * After `AVATAR_RETRY_MS` the id is free again and the avatars of the person try to
   * load the image once more.
   */
  markFailed(principal: AvatarPrincipal): void {
    if (this.failed().has(principal)) return;
    this.failed.update((set) => new Set([...set, principal]));
    this.retryTimers.set(
      principal,
      setTimeout(() => this.retry(principal), AVATAR_RETRY_MS),
    );
  }

  private retry(principal: AvatarPrincipal): void {
    this.retryTimers.delete(principal);
    this.failed.update((set) => {
      const next = new Set(set);
      next.delete(principal);
      return next;
    });
  }
}
