import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { type Observable, map } from 'rxjs';
import { I18nService } from '@core/i18n/i18n.service';
import { API_BASE_URL } from './api.config';
import {
  mapApplication,
  mapApplicationCreated,
  mapApplicationListItem,
  mapApplicationType,
  mapComment,
  mapTimelineEvent,
  mapTransition,
  toApplicationCreateBody,
} from './mappers';
import type {
  Application,
  ApplicationComment,
  ApplicationCreated,
  ApplicationCreatedWire,
  ApplicationListItem,
  ApplicationListItemWire,
  ApplicationListQuery,
  ApplicationOutWire,
  ApplicationType,
  ApplicationTypeListItemWire,
  CommentCreateBody,
  CommentOutWire,
  CommentVisibility,
  EffectiveForm,
  LogoutOut,
  MagicLinkVerifyResult,
  NewApplication,
  Page,
  Principal,
  TimelineEntry,
  TimelineEventOutWire,
  Transition,
  TransitionOutWire,
  TransitionRequestBody,
  TransitionResult,
  Uuid,
} from './models';

/**
 * Typisierter REST-Client gegen die OpenAPI-Contracts (sds/api.md).
 *
 * Antworten kommen in der Backend-Wire-Form (`*Wire`, camelCase via T-12
 * `_CamelModel`) herein und werden hier über `mappers.ts` in die FE-View-Modelle
 * übersetzt (i18n-Labels für die aktuelle `lang` aufgelöst). Components sehen
 * **nur** die View-Modelle.
 */
@Injectable({ providedIn: 'root' })
export class ApiClient {
  private readonly http = inject(HttpClient);
  private readonly base = inject(API_BASE_URL);
  private readonly i18n = inject(I18nService);

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
   * `MagicLinkVerifyOut` ist ein reines `BaseModel` → `application_id` snake_case.
   */
  verifyMagicLink(token: string): Observable<MagicLinkVerifyResult> {
    return this.http.post<MagicLinkVerifyResult>(`${this.base}/auth/magic-link/verify`, {
      token,
    });
  }

  // --- application-types (public) ------------------------------------------
  /** GET /application-types — Backend liefert eine **Page**; FE will die Liste. */
  applicationTypes(): Observable<ApplicationType[]> {
    return this.http
      .get<Page<ApplicationTypeListItemWire>>(`${this.base}/application-types`)
      .pipe(map((page) => page.items.map(mapApplicationType)));
  }

  /** Effektive Form-Definition (Typ-Felder + ggf. Topf-Extra-Felder, forms §5.7). */
  effectiveForm(typeId: Uuid, budgetPotId?: Uuid | null): Observable<EffectiveForm> {
    let params = new HttpParams();
    // Backend erwartet `?budgetPotId=` (forms/router.py), **nicht** `?pot=`.
    if (budgetPotId) params = params.set('budgetPotId', budgetPotId);
    return this.http.get<EffectiveForm>(`${this.base}/application-types/${typeId}/form`, {
      params,
    });
  }

  // --- applications --------------------------------------------------------
  listApplications(query: ApplicationListQuery = {}): Observable<Page<ApplicationListItem>> {
    let params = new HttpParams();
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null) params = params.set(key, String(value));
    }
    const lang = this.i18n.locale();
    return this.http
      .get<Page<ApplicationListItemWire>>(`${this.base}/applications`, { params })
      .pipe(
        map((page) => ({
          ...page,
          items: page.items.map((item) => mapApplicationListItem(item, lang)),
        })),
      );
  }

  getApplication(id: Uuid): Observable<Application> {
    const lang = this.i18n.locale();
    return this.http
      .get<ApplicationOutWire>(`${this.base}/applications/${id}`)
      .pipe(map((wire) => mapApplication(wire, lang)));
  }

  /** POST /applications — Body camelCase; Antwort ist `{ applicationId }` (kein Voll-DTO). */
  createApplication(input: NewApplication): Observable<ApplicationCreated> {
    return this.http
      .post<ApplicationCreatedWire>(
        `${this.base}/applications`,
        toApplicationCreateBody(input),
      )
      .pipe(map(mapApplicationCreated));
  }

  /** PATCH /applications/{id} — `data` aktualisieren (nur wenn state.editAllowed). */
  updateApplication(id: Uuid, data: Record<string, unknown>): Observable<Application> {
    const lang = this.i18n.locale();
    return this.http
      .patch<ApplicationOutWire>(`${this.base}/applications/${id}`, { data })
      .pipe(map((wire) => mapApplication(wire, lang)));
  }

  timeline(id: Uuid): Observable<TimelineEntry[]> {
    const lang = this.i18n.locale();
    return this.http
      .get<TimelineEventOutWire[]>(`${this.base}/applications/${id}/timeline`)
      .pipe(map((events) => events.map((e) => mapTimelineEvent(e, lang))));
  }

  // --- comments (applicant: nur public) ------------------------------------
  comments(id: Uuid): Observable<ApplicationComment[]> {
    return this.http
      .get<CommentOutWire[]>(`${this.base}/applications/${id}/comments`)
      .pipe(map((comments) => comments.map(mapComment)));
  }

  /** Antragsteller dürfen nur `public` schreiben (Backend lehnt `internal` mit 403 ab). */
  addComment(
    id: Uuid,
    body: string,
    visibility: CommentVisibility = 'public',
  ): Observable<ApplicationComment> {
    const payload: CommentCreateBody = { body, visibility };
    return this.http
      .post<CommentOutWire>(`${this.base}/applications/${id}/comments`, payload)
      .pipe(map(mapComment));
  }

  // --- flow ----------------------------------------------------------------
  transitions(id: Uuid): Observable<Transition[]> {
    const lang = this.i18n.locale();
    return this.http
      .get<TransitionOutWire[]>(`${this.base}/applications/${id}/transitions`)
      .pipe(map((items) => items.map((t) => mapTransition(t, lang))));
  }

  fireTransition(id: Uuid, req: TransitionRequestBody): Observable<TransitionResult> {
    return this.http.post<TransitionResult>(`${this.base}/applications/${id}/transition`, req);
  }
}
