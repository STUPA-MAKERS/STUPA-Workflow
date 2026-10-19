import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';
import { API_BASE_URL } from '@core/api/api.config';

/** An uploaded Markdown image (`POST /api/media/images`, 201). */
export interface MediaImage {
  id: string;
  /** The canonical path `/api/media/images/<id>`. Markdown stores this path. */
  url: string;
  mime: string;
  width: number;
  height: number;
  size: number;
}

/** The raster types that the media upload accepts. SVG is never one of them. */
export const MEDIA_IMAGE_TYPES: readonly string[] = [
  'image/png',
  'image/jpeg',
  'image/gif',
  'image/webp',
];

/**
 * The Markdown of an uploaded image: `![alt](/api/media/images/<id>)`. The alt text
 * loses the characters that would end the label (`[`, `]`) and its line breaks, so the
 * reference stays one valid image token.
 */
export function markdownImage(alt: string, id: string): string {
  const clean = alt
    .replace(/[[\]\\]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
  return `![${clean}](/api/media/images/${id})`;
}

/**
 * Client of the media module. It uploads an image for Markdown text. The server
 * re-encodes the image and answers with its canonical path. Errors: 401 (no principal
 * session), 413 (too large), 415 (type), 429 (rate limit), 503 (storage off).
 */
@Injectable({ providedIn: 'root' })
export class MediaApiService {
  private readonly http = inject(HttpClient);
  private readonly base = inject(API_BASE_URL);

  /** POST /media/images — multipart upload, field `file`. */
  uploadImage(file: File): Observable<MediaImage> {
    const form = new FormData();
    form.append('file', file);
    return this.http.post<MediaImage>(`${this.base}/media/images`, form);
  }
}
