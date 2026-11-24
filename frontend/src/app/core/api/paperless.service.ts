/**
 * API of the entry `In Paperless öffnen` (`/api/paperless`, §F/integrations/paperless/002525):
 * the address of the document that the platform filed for an element.
 *
 * It also serves the insert from Paperless (§F/integrations/paperless/002527-002529): whether
 * the part is on, the search and the copy of a picked document into a protocol text.
 *
 * Only a person with `paperless.use` asks. The answer has no address while the element has
 * no filed document or its part of the integration is off, and the entry then does not show.
 */
import { HttpClient } from '@angular/common/http';
import { Injectable, type Signal, inject } from '@angular/core';
import { toObservable, toSignal } from '@angular/core/rxjs-interop';
import { type Observable, catchError, map, of, shareReplay, switchMap } from 'rxjs';
import { API_BASE_URL } from '@core/api/api.config';
import type { Uuid } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import { FeatureService } from '@core/features/feature.service';
import { skipLoading } from '@stupa-makers/ui-kit';

/** The kinds of element whose page links to its filed document. */
export type PaperlessElementKind = 'protocol' | 'application' | 'plan';

/** One hit of the Paperless search (§F/integrations/paperless/002534). */
export interface PaperlessHit {
  readonly documentId: number;
  readonly title: string;
  readonly documentType: string | null;
  /** The date of the document, `YYYY-MM-DD`. */
  readonly created: string | null;
}

/** The copy of a Paperless document: an embedded PDF of the Sitzung. */
export interface PaperlessCopy {
  readonly name: string;
  readonly url: string;
}

/** The parts of the integration that a person with `paperless.use` uses. */
interface PartState {
  readonly enabled: boolean;
  readonly linkEnabled?: boolean;
}

const PARTS_OFF: PartState = { enabled: false, linkEnabled: false };

interface ElementDocument {
  readonly url: string | null;
  readonly documentId: number | null;
}

@Injectable({ providedIn: 'root' })
export class PaperlessService {
  private readonly http = inject(HttpClient);
  private readonly base = inject(API_BASE_URL);
  private readonly auth = inject(AuthService);
  private readonly features = inject(FeatureService);

  /** The answer of `GET /paperless/insert`, read once per session. */
  private partState: Observable<PartState> | null = null;

  /**
   * The right to see the entry while the feature `paperless` is on
   * (§F/integrations/paperless/002762). The server checks both again.
   */
  canUse(): boolean {
    return this.features.isOn('paperless') && this.auth.can('paperless.use');
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

  /**
   * Whether the part `Aus Paperless einfügen` is on (§F/integrations/paperless/002512).
   * `false` without the right and after an error. The answer is read once.
   */
  insertOn(): Observable<boolean> {
    return this.parts().pipe(map((state) => state.enabled));
  }

  /**
   * Whether the part `Paperless-Dokumente verknüpfen` is on (§F/integrations/paperless/002767).
   * `false` without the right and after an error. The answer is read once.
   */
  linksOn(): Observable<boolean> {
    return this.parts().pipe(map((state) => state.linkEnabled === true));
  }

  private parts(): Observable<PartState> {
    if (!this.canUse()) return of(PARTS_OFF);
    this.partState ??= this.http
      .get<PartState>(`${this.base}/paperless/insert`, { context: skipLoading() })
      .pipe(
        catchError(() => of(PARTS_OFF)),
        shareReplay(1),
      );
    return this.partState;
  }

  /**
   * GET /paperless/search — at most 20 documents by title and content; without a query the
   * documents that Paperless added last. 503 `paperless_unavailable` when Paperless fails.
   */
  search(query: string): Observable<PaperlessHit[]> {
    return this.http.get<PaperlessHit[]>(`${this.base}/paperless/search`, {
      params: { q: query },
      context: skipLoading(),
    });
  }

  /**
   * POST /meetings/{id}/documents/paperless — copy the PDF version of a document into the
   * protocol of the Sitzung (§F/integrations/paperless/002528).
   */
  insert(meetingId: Uuid, documentId: number): Observable<PaperlessCopy> {
    return this.http.post<PaperlessCopy>(`${this.base}/meetings/${meetingId}/documents/paperless`, {
      documentId,
    });
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
