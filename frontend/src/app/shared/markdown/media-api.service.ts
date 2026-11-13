import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';
import { API_BASE_URL } from '@core/api/api.config';

/** An uploaded Markdown image (`POST /api/media/images`, 201). */
export interface MediaImage {
  readonly id: string;
  /** The canonical path `/api/media/images/<id>`. Markdown stores this path. */
  readonly url: string;
  readonly mime: string;
  readonly width: number;
  readonly height: number;
  readonly size: number;
}

/** An embedded PDF (`POST /api/meetings/<id>/documents`, 201, and its info route). */
export interface MediaDocument {
  readonly id: string;
  /** The canonical path `/api/media/documents/<id>`. Markdown stores this path. */
  readonly url: string;
  readonly name: string;
  readonly size: number;
  readonly pages: number;
}

/** The type that the PDF upload accepts. */
export const MEDIA_DOCUMENT_TYPES: readonly string[] = ['application/pdf'];

/**
 * The Markdown of an embedded PDF: `[name](/api/media/documents/<id>)`. The name keeps its
 * characters: `\`, `[` and `]` are escaped, and a line break becomes a space.
 */
export function markdownDocument(name: string, id: string): string {
  const clean = name.replace(/\s+/g, ' ').trim().replace(/[\\[\]]/g, '\\$&') || 'PDF';
  return `[${clean}](/api/media/documents/${id})`;
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

  /**
   * POST /meetings/{id}/documents — upload one PDF for the protocol of a meeting.
   * Errors: 403 (no write access), 413 (over 20 MiB or 100 pages), 415 (no readable,
   * unencrypted PDF), 429, 503.
   */
  uploadDocument(meetingId: string, file: File): Observable<MediaDocument> {
    const form = new FormData();
    form.append('file', file);
    return this.http.post<MediaDocument>(`${this.base}/meetings/${meetingId}/documents`, form);
  }

  /** GET <url>/info — the name and page count of a PDF; `url` is its same-origin URL. */
  documentInfo(url: string): Observable<MediaDocument> {
    return this.http.get<MediaDocument>(`${url}/info`);
  }
}
