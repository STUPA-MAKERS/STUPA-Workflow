import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';
import { API_BASE_URL } from './api.config';
import type {
  ApplicationCreate,
  ApplicationListQuery,
  ApplicationOut,
  ApplicationType,
  Page,
  Principal,
  TimelineEntry,
  Transition,
  TransitionRequest,
  Uuid,
} from './models';

/**
 * Typisierter REST-Client gegen die OpenAPI-Contracts (sds/api.md).
 * T-03-Scope: Auth/Application(-Types)/Flow — genug, damit das Skelett und der
 * Mock-Interceptor end-to-end laufen. Feature-spezifische Endpunkte folgen in
 * den jeweiligen FE-Feature-Tasks (T-30…T-36).
 */
@Injectable({ providedIn: 'root' })
export class ApiClient {
  private readonly http = inject(HttpClient);
  private readonly base = inject(API_BASE_URL);

  // --- auth ----------------------------------------------------------------
  me(): Observable<Principal> {
    return this.http.get<Principal>(`${this.base}/auth/me`);
  }

  // --- application-types (public) ------------------------------------------
  applicationTypes(): Observable<ApplicationType[]> {
    return this.http.get<ApplicationType[]>(`${this.base}/application-types`);
  }

  // --- applications --------------------------------------------------------
  listApplications(query: ApplicationListQuery = {}): Observable<Page<ApplicationOut>> {
    let params = new HttpParams();
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null) params = params.set(key, String(value));
    }
    return this.http.get<Page<ApplicationOut>>(`${this.base}/applications`, { params });
  }

  getApplication(id: Uuid): Observable<ApplicationOut> {
    return this.http.get<ApplicationOut>(`${this.base}/applications/${id}`);
  }

  createApplication(payload: ApplicationCreate): Observable<ApplicationOut> {
    return this.http.post<ApplicationOut>(`${this.base}/applications`, payload);
  }

  timeline(id: Uuid): Observable<TimelineEntry[]> {
    return this.http.get<TimelineEntry[]>(`${this.base}/applications/${id}/timeline`);
  }

  // --- flow ----------------------------------------------------------------
  transitions(id: Uuid): Observable<Transition[]> {
    return this.http.get<Transition[]>(`${this.base}/applications/${id}/transitions`);
  }

  fireTransition(id: Uuid, req: TransitionRequest): Observable<ApplicationOut> {
    return this.http.post<ApplicationOut>(`${this.base}/applications/${id}/transition`, req);
  }
}
