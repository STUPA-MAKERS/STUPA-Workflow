/**
 * API of the entry `In Paperless öffnen` (`/api/paperless`, §F/integrations/paperless/002525):
 * the address of the document that the platform filed for an element.
 *
 * Only a person with `paperless.use` asks. The answer has no address while the element has
 * no filed document or its part of the integration is off, and the entry then does not show.
 */
import { HttpClient } from '@angular/common/http';
import { Injectable, type Signal, inject } from '@angular/core';
import { toObservable, toSignal } from '@angular/core/rxjs-interop';
import { type Observable, catchError, map, of, switchMap } from 'rxjs';
import { API_BASE_URL } from '@core/api/api.config';
import type { Uuid } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import { skipLoading } from '@stupa-makers/ui-kit';

/** The kinds of element whose page links to its filed document. */
export type PaperlessElementKind = 'protocol' | 'application' | 'plan';

interface ElementDocument {
  readonly url: string | null;
  readonly documentId: number | null;
}

@Injectable({ providedIn: 'root' })
export class PaperlessService {
  private readonly http = inject(HttpClient);
  private readonly base = inject(API_BASE_URL);
  private readonly auth = inject(AuthService);

  /** The right to see the entry. The server checks it again. */
  canUse(): boolean {
    return this.auth.can('paperless.use');
  }

  /**
   * The address of the filed document of an element. `null` without the right, without a
   * document, and after an error: an outage of the integration never breaks a detail page.
   */
  documentUrl(kind: PaperlessElementKind, id: Uuid): Observable<string | null> {
    if (!this.canUse()) return of(null);
    return this.http
      .get<ElementDocument>(`${this.base}/paperless/documents/${kind}/${id}`, {
        context: skipLoading(),
      })
      .pipe(
        map((doc) => doc.url),
        catchError(() => of(null)),
      );
  }
}

/**
 * The address of the filed document of the element that `id` names, as a signal. It reads
 * again when the id changes. Call it in an injection context.
 */
export function paperlessLink(
  kind: PaperlessElementKind,
  id: Signal<Uuid | null | undefined>,
): Signal<string | null> {
  const api = inject(PaperlessService);
  return toSignal(
    toObservable(id).pipe(switchMap((value) => (value ? api.documentUrl(kind, value) : of(null)))),
    { initialValue: null },
  );
}

/** Open a filed document in Paperless in a new tab. */
export function openInPaperless(url: string): void {
  window.open(url, '_blank', 'noopener');
}
