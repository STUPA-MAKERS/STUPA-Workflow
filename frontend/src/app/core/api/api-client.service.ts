import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';
import { API_BASE_URL } from './api.config';
import type {
  ApplicationComment,
  ApplicationCreate,
  ApplicationListQuery,
  ApplicationOut,
  ApplicationType,
  EffectiveForm,
  LogoutOut,
  MagicLinkVerifyResult,
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

  logout(): Observable<LogoutOut> {
    return this.http.post<LogoutOut>(`${this.base}/auth/logout`, {});
  }

  /**
   * POST /auth/magic-link/verify — Magic-Link-Token (aus der Mail-URL) gegen eine
   * **HttpOnly-Applicant-Session-Cookie** eintauschen (api.md §1, security.md §1).
   * Der Server setzt das Cookie; die Antwort trägt **keinen** Session-Token —
   * Folge-Requests authentisieren über `withCredentials` (kein JS-Storage).
   */
  verifyMagicLink(token: string): Observable<MagicLinkVerifyResult> {
    return this.http.post<MagicLinkVerifyResult>(`${this.base}/auth/magic-link/verify`, {
      token,
    });
  }

  // --- application-types (public) ------------------------------------------
  applicationTypes(): Observable<ApplicationType[]> {
    return this.http.get<ApplicationType[]>(`${this.base}/application-types`);
  }

  /** Effektive Form-Definition (Typ-Felder + ggf. Topf-Extra-Felder, forms §5.7). */
  effectiveForm(typeId: Uuid, budgetPotId?: Uuid | null): Observable<EffectiveForm> {
    let params = new HttpParams();
    if (budgetPotId) params = params.set('pot', budgetPotId);
    return this.http.get<EffectiveForm>(`${this.base}/application-types/${typeId}/form`, {
      params,
    });
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

  /** PATCH /applications/{id} — `data` aktualisieren (nur wenn state.editAllowed). */
  updateApplication(id: Uuid, data: Record<string, unknown>): Observable<ApplicationOut> {
    return this.http.patch<ApplicationOut>(`${this.base}/applications/${id}`, { data });
  }

  timeline(id: Uuid): Observable<TimelineEntry[]> {
    return this.http.get<TimelineEntry[]>(`${this.base}/applications/${id}/timeline`);
  }

  // --- comments (applicant: nur public) ------------------------------------
  comments(id: Uuid): Observable<ApplicationComment[]> {
    return this.http.get<ApplicationComment[]>(`${this.base}/applications/${id}/comments`);
  }

  addComment(id: Uuid, body: string): Observable<ApplicationComment> {
    return this.http.post<ApplicationComment>(`${this.base}/applications/${id}/comments`, {
      body,
    });
  }

  // --- flow ----------------------------------------------------------------
  transitions(id: Uuid): Observable<Transition[]> {
    return this.http.get<Transition[]>(`${this.base}/applications/${id}/transitions`);
  }

  fireTransition(id: Uuid, req: TransitionRequest): Observable<ApplicationOut> {
    return this.http.post<ApplicationOut>(`${this.base}/applications/${id}/transition`, req);
  }
}
