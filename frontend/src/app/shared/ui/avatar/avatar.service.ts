import { Injectable, computed, inject, signal } from '@angular/core';
import { API_BASE_URL } from '@core/api/api.config';
import { BrandingService } from '@core/branding/branding.service';

/** The principal of an avatar: a principal id, or `'me'` for the logged-in user. */
export type AvatarPrincipal = string;

/**
 * The image URLs of the person avatars and the ids without an image.
 *
 * The API proxies Gravatar (`GET /principals/{id}/avatar`): the browser loads the image
 * from our own origin, so the CSP stays `img-src 'self'` and Gravatar never sees the
 * viewer. A 404 means "no Gravatar"; the avatar then keeps the initials. This service
 * remembers such an id for the session, so a list with the same person in many rows,
 * or a second visit of the page, asks only once.
 *
 * The admin switch `gravatarEnabled` of the public site config turns the images off.
 * Until the config is loaded no image loads, so the switch never comes too late.
 */
@Injectable({ providedIn: 'root' })
export class AvatarService {
  private readonly base = inject(API_BASE_URL);
  private readonly branding = inject(BrandingService);

  private readonly failed = signal<ReadonlySet<string>>(new Set());

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

  /** The image of `principal` failed to load (404, 429, network): use the initials. */
  markFailed(principal: AvatarPrincipal): void {
    if (this.failed().has(principal)) return;
    this.failed.update((set) => new Set([...set, principal]));
  }
}
