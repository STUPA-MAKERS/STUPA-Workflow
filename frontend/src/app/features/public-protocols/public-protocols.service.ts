import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';
import { API_BASE_URL } from '@core/api/api.config';
import { skipLoading } from '@core/loading/loading.interceptor';
import type {
  PublicGremium,
  PublicProtocolDetail,
  PublicProtocolPage,
  PublicProtocolQuery,
  PublicSemester,
} from './public-protocols.models';

/** Build the query of the list and the semester routes. Empty filters stay out. */
export function protocolParams(query: PublicProtocolQuery): HttpParams {
  let params = new HttpParams();
  for (const id of query.gremium ?? []) params = params.append('gremium', id);
  if (query.semester) params = params.set('semester', query.semester);
  const q = query.q?.trim();
  if (q) params = params.set('q', q.slice(0, 100));
  if (query.limit !== undefined) params = params.set('limit', String(query.limit));
  if (query.offset) params = params.set('offset', String(query.offset));
  return params;
}

/**
 * The public protocol routes (`/api/public/…`, no login). The pages show their own
 * loading state, so no request starts the global loading overlay.
 */
@Injectable({ providedIn: 'root' })
export class PublicProtocolsService {
  private readonly http = inject(HttpClient);
  private readonly base = inject(API_BASE_URL);

  /** GET /public/gremien — the gremien that publish their protocols. */
  gremien(): Observable<PublicGremium[]> {
    return this.http.get<PublicGremium[]>(`${this.base}/public/gremien`, {
      context: skipLoading(),
    });
  }

  /** GET /public/protocols — one page of protocols, newest first. */
  list(query: PublicProtocolQuery = {}): Observable<PublicProtocolPage> {
    return this.http.get<PublicProtocolPage>(`${this.base}/public/protocols`, {
      params: protocolParams(query),
      context: skipLoading(),
    });
  }

  /** GET /public/protocols/semesters — the semesters with protocols for the filters. */
  semesters(query: PublicProtocolQuery = {}): Observable<PublicSemester[]> {
    return this.http.get<PublicSemester[]>(`${this.base}/public/protocols/semesters`, {
      params: protocolParams({ gremium: query.gremium, q: query.q }),
      context: skipLoading(),
    });
  }

  /** GET /public/protocols/{id} — the public version of one protocol. */
  detail(id: string): Observable<PublicProtocolDetail> {
    return this.http.get<PublicProtocolDetail>(
      `${this.base}/public/protocols/${encodeURIComponent(id)}`,
      { context: skipLoading() },
    );
  }

  /** The download link of the public PDF. The API streams it; never a bucket link. */
  pdfUrl(id: string): string {
    return `${this.base}/public/protocols/${encodeURIComponent(id)}/pdf`;
  }
}
