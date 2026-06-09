import { HttpClient, HttpErrorResponse, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { type Observable, catchError, map, of, throwError } from 'rxjs';
import { I18nService } from '@core/i18n/i18n.service';
import { API_BASE_URL } from './api.config';
import {
  mapApplication,
  mapApplicationCreated,
  mapApplicationListItem,
  mapApplicationType,
  mapAttachment,
  mapBudgetPotInfo,
  mapBudgetStats,
  mapComment,
  mapMeeting,
  mapProtocol,
  mapSignedUrl,
  mapTimelineEvent,
  mapTransition,
  mapVersion,
  toApplicationCreateBody,
} from './mappers';
import type {
  BudgetPotCreateBody,
  BudgetPotInfo,
  BudgetPotOutWire,
  BudgetPotUpdateBody,
  BudgetStats,
  BudgetStatsOutWire,
  BudgetStatsQuery,
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
  ApplicationVersion,
  Attachment,
  AttachmentOutWire,
  CommentCreateBody,
  CommentOutWire,
  CommentVisibility,
  EffectiveForm,
  LogoutOut,
  MagicLinkVerifyResult,
  Meeting,
  MeetingCreateBody,
  AgendaItem,
  AltchaChallenge,
  AssignableApplication,
  Attendance,
  AttendanceStatus,
  MeetingOutWire,
  MeetingPatchBody,
  NewApplication,
  Page,
  Principal,
  Protocol,
  ProtocolOutWire,
  ProtocolVotesBody,
  SignedUrl,
  SignedUrlOutWire,
  TimelineEntry,
  TimelineEventOutWire,
  Transition,
  TransitionOutWire,
  TransitionRequestBody,
  TransitionResult,
  Uuid,
  VersionOutWire,
  Vote,
  BallotResult,
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

  /** GET /applications/tasks — offene Entscheidungen für die eigene Rolle (#64). */
  listTasks(): Observable<ApplicationListItem[]> {
    const lang = this.i18n.locale();
    return this.http
      .get<ApplicationListItemWire[]>(`${this.base}/applications/tasks`)
      .pipe(map((items) => items.map((item) => mapApplicationListItem(item, lang))));
  }

  getApplication(id: Uuid): Observable<Application> {
    const lang = this.i18n.locale();
    return this.http
      .get<ApplicationOutWire>(`${this.base}/applications/${id}`)
      .pipe(map((wire) => mapApplication(wire, lang)));
  }

  /**
   * GET /altcha/challenge — frische, server-signierte PoW-Challenge (Issue #23).
   * Liefert `null`, wenn Altcha serverseitig deaktiviert ist (404 → kein Captcha).
   */
  altchaChallenge(): Observable<AltchaChallenge | null> {
    return this.http.get<AltchaChallenge>(`${this.base}/altcha/challenge`).pipe(
      catchError((err: HttpErrorResponse) =>
        err.status === 404 ? of(null) : throwError(() => err),
      ),
    );
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

  /** DELETE /applications/{id} — Verwalter:in oder Ersteller:in (#24). */
  deleteApplication(id: Uuid): Observable<void> {
    return this.http.delete<void>(`${this.base}/applications/${id}`);
  }

  timeline(id: Uuid): Observable<TimelineEntry[]> {
    const lang = this.i18n.locale();
    return this.http
      .get<TimelineEventOutWire[]>(`${this.base}/applications/${id}/timeline`)
      .pipe(map((events) => events.map((e) => mapTimelineEvent(e, lang))));
  }

  /**
   * GET /applications/{id}/versions — Versionshistorie + Diff (Principal-only).
   * Der Diff ist sprach-neutral (rohe Feldwerte) → kein `lang`-Mapping nötig.
   */
  versions(id: Uuid): Observable<ApplicationVersion[]> {
    return this.http
      .get<VersionOutWire[]>(`${this.base}/applications/${id}/versions`)
      .pipe(map((items) => items.map(mapVersion)));
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

  /** POST /applications/{id}/approval — Approval-State entscheiden (#28). */
  submitApproval(id: Uuid, decision: 'accept' | 'reject'): Observable<TransitionResult> {
    return this.http.post<TransitionResult>(`${this.base}/applications/${id}/approval`, { decision });
  }

  // --- files / attachments (T-13) ------------------------------------------
  /**
   * POST /applications/{id}/attachments — Multipart-Upload (≤10 MB, A(edit)/P).
   * Der Server scannt asynchron (ClamAV); die Antwort trägt `scanned=false` bis
   * der Worker durch ist. Fehler: 413 (zu groß), 415 (Typ), 429 (Rate-Limit),
   * 503 (Storage aus).
   */
  uploadAttachment(
    id: Uuid,
    file: File,
    opts: { fieldKey?: string | null; isComparisonOffer?: boolean } = {},
  ): Observable<Attachment> {
    const form = new FormData();
    form.append('file', file);
    if (opts.fieldKey) form.append('field_key', opts.fieldKey);
    if (opts.isComparisonOffer) form.append('is_comparison_offer', 'true');
    return this.http
      .post<AttachmentOutWire>(`${this.base}/applications/${id}/attachments`, form)
      .pipe(map(mapAttachment));
  }

  /** GET /applications/{id}/attachments — bestehende Anhänge (Panel-Hydration). */
  listAttachments(id: Uuid): Observable<Attachment[]> {
    return this.http
      .get<AttachmentOutWire[]>(`${this.base}/applications/${id}/attachments`)
      .pipe(map((list) => list.map(mapAttachment)));
  }

  /**
   * GET /attachments/{id} — kurzlebige signierte MinIO-URL. 409 = noch nicht
   * sauber gescannt / Quarantäne, 410 = abgelaufen/verbraucht (api.md §files).
   */
  attachmentUrl(attachmentId: Uuid): Observable<SignedUrl> {
    return this.http
      .get<SignedUrlOutWire>(`${this.base}/attachments/${attachmentId}`)
      .pipe(map(mapSignedUrl));
  }

  // --- voting (api.md »voting«) --------------------------------------------
  /**
   * GET /votes/{id} — Vote-State + Tally. `VoteOut` ist ein `_CamelModel`
   * (camelCase) und braucht keine Mapper-Schicht; bei `secret` liefert der
   * Server in `tally` nur `counts`.
   */
  getVote(id: Uuid): Observable<Vote> {
    return this.http.get<Vote>(`${this.base}/votes/${id}`);
  }

  /**
   * POST /votes/{id}/ballot — Stimme abgeben (`choice` ∈ config.options).
   * Idempotent: erneuter Cast mit gleicher Wahl bleibt `cast`; ein Wechsel
   * liefert `changed` (nur wenn `config.allowChange`). 409 = Doppel/geschlossen,
   * 403 = nicht stimmberechtigt — Components werten den Status aus.
   */
  castBallot(id: Uuid, choice: string): Observable<BallotResult> {
    return this.http.post<BallotResult>(`${this.base}/votes/${id}/ballot`, { choice });
  }

  // --- meetings (Sitzungssteuerung, T-33) ----------------------------------
  /** POST /meetings — Sitzung anlegen (P(meeting.manage)). */
  createMeeting(body: MeetingCreateBody): Observable<Meeting> {
    return this.http
      .post<MeetingOutWire>(`${this.base}/meetings`, body)
      .pipe(map(mapMeeting));
  }

  /** GET /meetings — Sitzungen auflisten (neueste zuerst), optional Gremium-gefiltert (#104). */
  listMeetings(gremiumId?: Uuid): Observable<Meeting[]> {
    let params = new HttpParams();
    if (gremiumId) params = params.set('gremiumId', gremiumId);
    return this.http
      .get<MeetingOutWire[]>(`${this.base}/meetings`, { params })
      .pipe(map((items) => items.map(mapMeeting)));
  }

  /** GET /meetings/{id} — Sitzungs-State + Votes. */
  getMeeting(id: Uuid): Observable<Meeting> {
    return this.http.get<MeetingOutWire>(`${this.base}/meetings/${id}`).pipe(map(mapMeeting));
  }

  /** PATCH /meetings/{id} — Status und/oder aktiven Antrag setzen. */
  patchMeeting(id: Uuid, body: MeetingPatchBody): Observable<Meeting> {
    return this.http
      .patch<MeetingOutWire>(`${this.base}/meetings/${id}`, body)
      .pipe(map(mapMeeting));
  }

  // --- attendance (#Meetings/#55/#56) --------------------------------------
  /** GET /meetings/{id}/attendance — Roster der aktuellen Mitglieder + Status. */
  listAttendance(meetingId: Uuid): Observable<Attendance[]> {
    return this.http.get<Attendance[]>(`${this.base}/meetings/${meetingId}/attendance`);
  }

  /** PUT /meetings/{id}/attendance/me — eigene Anwesenheit markieren. */
  setOwnAttendance(meetingId: Uuid, status: AttendanceStatus): Observable<Attendance[]> {
    return this.http.put<Attendance[]>(
      `${this.base}/meetings/${meetingId}/attendance/me`,
      { status },
    );
  }

  /** PUT /meetings/{id}/attendance/{principalId} — Mitglied setzen (Sitzungsleitung). */
  setMemberAttendance(
    meetingId: Uuid,
    principalId: Uuid,
    status: AttendanceStatus,
  ): Observable<Attendance[]> {
    return this.http.put<Attendance[]>(
      `${this.base}/meetings/${meetingId}/attendance/${principalId}`,
      { status },
    );
  }

  // --- agenda / Tagesordnung (#10/#58) -------------------------------------
  /** GET /meetings/{id}/agenda — zugewiesene Anträge (geordnet). */
  listAgenda(meetingId: Uuid): Observable<AgendaItem[]> {
    return this.http.get<AgendaItem[]>(`${this.base}/meetings/${meetingId}/agenda`);
  }

  /** GET /meetings/{id}/agenda/assignable — Abstimmungs-Anträge, noch nicht auf der TO. */
  listAssignableApplications(meetingId: Uuid): Observable<AssignableApplication[]> {
    return this.http.get<AssignableApplication[]>(
      `${this.base}/meetings/${meetingId}/agenda/assignable`,
    );
  }

  /** POST /meetings/{id}/agenda — Antrag auf die Tagesordnung setzen (Sitzungsleitung). */
  addAgendaItem(meetingId: Uuid, applicationId: Uuid): Observable<AgendaItem[]> {
    return this.http.post<AgendaItem[]>(`${this.base}/meetings/${meetingId}/agenda`, {
      applicationId,
    });
  }

  /** POST /meetings/{id}/agenda — Freitext-TOP (ohne Antrag) anlegen. */
  addAgendaFreetext(meetingId: Uuid, title: string): Observable<AgendaItem[]> {
    return this.http.post<AgendaItem[]>(`${this.base}/meetings/${meetingId}/agenda`, {
      title,
    });
  }

  /** DELETE /meetings/{id}/agenda/{itemId} — TOP von der Tagesordnung entfernen. */
  removeAgendaItem(meetingId: Uuid, itemId: Uuid): Observable<AgendaItem[]> {
    return this.http.delete<AgendaItem[]>(
      `${this.base}/meetings/${meetingId}/agenda/${itemId}`,
    );
  }

  /**
   * POST /meetings/{id}/votes — Live-Abstimmung für einen Antrag anlegen + öffnen,
   * mit Beschlussfrage (fürs Protokoll). Antwort = aktualisierte Sitzung (#Meetings).
   */
  openMeetingVote(
    meetingId: Uuid,
    body: {
      applicationId: Uuid;
      question?: string | null;
      options: string[];
      majorityRule?: 'simple' | 'absolute' | 'two_thirds';
      secret?: boolean;
    },
  ): Observable<Meeting> {
    return this.http
      .post<MeetingOutWire>(`${this.base}/meetings/${meetingId}/votes`, body)
      .pipe(map(mapMeeting));
  }

  /** POST /votes/{id}/open — Vote öffnen (auch live; P(vote.manage)). */
  openVote(voteId: Uuid): Observable<void> {
    return this.http.post<void>(`${this.base}/votes/${voteId}/open`, {});
  }

  /** POST /votes/{id}/close — Vote schließen → Ergebnis → Flow-Branch. */
  closeVote(voteId: Uuid): Observable<void> {
    return this.http.post<void>(`${this.base}/votes/${voteId}/close`, {});
  }

  // --- protocol (Protokoll-Editor, T-33) -----------------------------------
  /** POST /meetings/{id}/protocol — Protokoll anlegen **oder** laden (idempotent). */
  loadProtocol(meetingId: Uuid): Observable<Protocol> {
    return this.http
      .post<ProtocolOutWire>(`${this.base}/meetings/${meetingId}/protocol`, {})
      .pipe(map(mapProtocol));
  }

  /** PATCH /protocols/{id} — Markdown aktualisieren. */
  updateProtocol(protocolId: Uuid, markdown: string): Observable<Protocol> {
    return this.http
      .patch<ProtocolOutWire>(`${this.base}/protocols/${protocolId}`, { markdown })
      .pipe(map(mapProtocol));
  }

  /** POST /protocols/{id}/votes — Abstimmungs-Snippets serverseitig einbetten. */
  embedVotes(protocolId: Uuid, voteIds: Uuid[]): Observable<Protocol> {
    const body: ProtocolVotesBody = { voteIds };
    return this.http
      .post<ProtocolOutWire>(`${this.base}/protocols/${protocolId}/votes`, body)
      .pipe(map(mapProtocol));
  }

  /** POST /protocols/{id}/finalize — →PDF (pytex) → MAIL_LIST + Nextcloud. */
  finalizeProtocol(protocolId: Uuid): Observable<Protocol> {
    return this.http
      .post<ProtocolOutWire>(`${this.base}/protocols/${protocolId}/finalize`, {})
      .pipe(map(mapProtocol));
  }

  // --- budget (api.md »budget«, T-17/T-35) ---------------------------------
  /**
   * GET /budget/stats — Rollup-Statistik (P(budget.view)). Filter `pot`/`gremium`/
   * `period` werden 1:1 als Query-Param durchgereicht (Backend-Aliase). `names`
   * (id → Topf-Name aus {@link listBudgetPots}) reicht der Aufrufer optional durch,
   * damit Töpfe im Diagramm statt mit roher UUID benannt erscheinen.
   */
  budgetStats(
    query: BudgetStatsQuery = {},
    names?: ReadonlyMap<Uuid, string>,
  ): Observable<BudgetStats> {
    let params = new HttpParams();
    if (query.pot) params = params.set('pot', query.pot);
    if (query.gremium) params = params.set('gremium', query.gremium);
    if (query.period) params = params.set('period', query.period);
    return this.http
      .get<BudgetStatsOutWire>(`${this.base}/budget/stats`, { params })
      .pipe(map((wire) => mapBudgetStats(wire, names)));
  }

  /**
   * GET /budget-pots — Topf-Stammdaten (P(budget.manage)). Dient dem Dashboard
   * **nur** zur Namens-/Stammdaten-Anreicherung; ohne `budget.manage` antwortet
   * der Server 403 → der Aufrufer fängt das ab und zeigt gekürzte IDs.
   */
  budgetPots(
    opts: { gremium?: Uuid; period?: string; active?: boolean } = {},
  ): Observable<BudgetPotInfo[]> {
    let params = new HttpParams();
    if (opts.gremium) params = params.set('gremium', opts.gremium);
    if (opts.period) params = params.set('period', opts.period);
    if (opts.active !== undefined) params = params.set('active', String(opts.active));
    return this.http
      .get<BudgetPotOutWire[]>(`${this.base}/budget-pots`, { params })
      .pipe(map((pots) => pots.map(mapBudgetPotInfo)));
  }

  /** POST /budget-pots — neuen Topf anlegen (P(budget.manage), #76). */
  createBudgetPot(body: BudgetPotCreateBody): Observable<BudgetPotInfo> {
    return this.http
      .post<BudgetPotOutWire>(`${this.base}/budget-pots`, body)
      .pipe(map(mapBudgetPotInfo));
  }

  /** PATCH /budget-pots/{id} — Topf-Stammdaten ändern (P(budget.manage), #76). */
  updateBudgetPot(id: Uuid, body: BudgetPotUpdateBody): Observable<BudgetPotInfo> {
    return this.http
      .patch<BudgetPotOutWire>(`${this.base}/budget-pots/${id}`, body)
      .pipe(map(mapBudgetPotInfo));
  }
}
