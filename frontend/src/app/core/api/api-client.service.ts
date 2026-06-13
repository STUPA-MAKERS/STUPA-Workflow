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
  mapComment,
  mapMeeting,
  mapMeetingPage,
  mapProtocol,
  mapSignedUrl,
  mapTimelineEvent,
  mapTransition,
  mapVersion,
  toApplicationCreateBody,
} from './mappers';
import type {
  ConsentRequest,
  McpSetup,
  NotificationPreference,
  OAuthGrant,
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
  MeetingMember,
  AgendaItem,
  AltchaChallenge,
  AssignableApplication,
  Attendance,
  AttendanceStatus,
  MeetingOutWire,
  MeetingPage,
  MeetingPageWire,
  MeetingPatchBody,
  NewApplication,
  Page,
  Principal,
  Protocol,
  PublicSiteConfig,
  ProtocolOutWire,
  ProtocolVotesBody,
  SignedUrl,
  SignedUrlOutWire,
  TimelineDirection,
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

  /**
   * Effektive Form eines **bestehenden** Antrags aus seiner **gepinnten** Version
   * (forms §5.7, data-model §1). Liefert dieselben Felder, gegen die der Server
   * validiert — auch wenn die aktive Form-Version inzwischen geändert wurde.
   */
  applicationForm(applicationId: Uuid): Observable<EffectiveForm> {
    return this.http.get<EffectiveForm>(`${this.base}/applications/${applicationId}/form`);
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

  /** GET /applications/export.xlsx — gefilterte Antragsliste als Excel (P(`application.export`)). */
  exportApplicationsXlsx(query: ApplicationListQuery = {}): Observable<Blob> {
    let params = new HttpParams();
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && key !== 'limit' && key !== 'offset') {
        params = params.set(key, String(value));
      }
    }
    return this.http.get(`${this.base}/applications/export.xlsx`, { params, responseType: 'blob' });
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

  /** Übergänge, die der Magic-Link-Antragsteller feuern darf (actorIsApplicant-Gate). */
  applicantTransitions(id: Uuid): Observable<Transition[]> {
    const lang = this.i18n.locale();
    return this.http
      .get<TransitionOutWire[]>(`${this.base}/applications/${id}/applicant-transitions`)
      .pipe(map((items) => items.map((t) => mapTransition(t, lang))));
  }

  fireApplicantTransition(id: Uuid, req: TransitionRequestBody): Observable<TransitionResult> {
    return this.http.post<TransitionResult>(
      `${this.base}/applications/${id}/applicant-transition`,
      req,
    );
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

  /** DELETE /attachments/{id} — Anhang löschen (Principal/Antragsteller/Ersteller:in). */
  deleteAttachment(attachmentId: Uuid): Observable<void> {
    return this.http.delete<void>(`${this.base}/attachments/${attachmentId}`);
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
  castBallot(id: Uuid, choice: string, asDelegation = false): Observable<BallotResult> {
    return this.http.post<BallotResult>(`${this.base}/votes/${id}/ballot`, {
      choice,
      asDelegation,
    });
  }

  // --- meetings (Sitzungssteuerung, T-33) ----------------------------------
  /** POST /meetings — Sitzung anlegen (P(meeting.manage)). */
  createMeeting(body: MeetingCreateBody): Observable<Meeting> {
    return this.http
      .post<MeetingOutWire>(`${this.base}/meetings`, body)
      .pipe(map(mapMeeting));
  }

  /** GET /gremien/{id}/meeting-members — Protokollant-Kandidaten fürs Anlegen (P(session.manage)). */
  listMeetingMembers(gremiumId: Uuid): Observable<MeetingMember[]> {
    return this.http.get<MeetingMember[]>(
      `${this.base}/gremien/${gremiumId}/meeting-members`,
    );
  }

  /** GET /meetings — Sitzungen auflisten (neueste zuerst), optional Gremium-gefiltert (#104). */
  listMeetings(gremiumId?: Uuid): Observable<Meeting[]> {
    let params = new HttpParams();
    if (gremiumId) params = params.set('gremiumId', gremiumId);
    return this.http
      .get<MeetingOutWire[]>(`${this.base}/meetings`, { params })
      .pipe(map((items) => items.map(mapMeeting)));
  }

  /**
   * GET /meetings/timeline — Keyset-paginierte Timeline um *jetzt* (#104).
   *
   * `direction: 'upcoming'` läuft chronologisch vorwärts, `'past'` rückwärts
   * (Infinite-Scroll nach oben). `cursor` stammt aus `nextCursor` der Vorseite;
   * `null`/leer ⇒ Beginn ab *jetzt*. `nextCursor === null` ⇒ Ende der Richtung.
   */
  listMeetingsTimeline(opts: {
    direction: TimelineDirection;
    cursor?: string | null;
    limit?: number;
    gremiumId?: Uuid;
  }): Observable<MeetingPage> {
    let params = new HttpParams().set('direction', opts.direction);
    if (opts.cursor) params = params.set('cursor', opts.cursor);
    if (opts.limit) params = params.set('limit', String(opts.limit));
    if (opts.gremiumId) params = params.set('gremiumId', opts.gremiumId);
    return this.http
      .get<MeetingPageWire>(`${this.base}/meetings/timeline`, { params })
      .pipe(map(mapMeetingPage));
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

  /** DELETE /meetings/{id} — Sitzung löschen (P(session.manage)/Admin). */
  deleteMeeting(id: Uuid): Observable<void> {
    return this.http.delete<void>(`${this.base}/meetings/${id}`);
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

  /** PATCH /meetings/{id}/agenda/{itemId} — Markdown-Text eines TOP setzen. */
  setAgendaBody(meetingId: Uuid, itemId: Uuid, body: string): Observable<AgendaItem[]> {
    return this.http.patch<AgendaItem[]>(
      `${this.base}/meetings/${meetingId}/agenda/${itemId}`,
      { body },
    );
  }

  /** PATCH /meetings/{id}/agenda/{itemId} — Freitext-TOP umbenennen (Titel setzen). */
  renameAgendaItem(meetingId: Uuid, itemId: Uuid, title: string): Observable<AgendaItem[]> {
    return this.http.patch<AgendaItem[]>(
      `${this.base}/meetings/${meetingId}/agenda/${itemId}`,
      { title },
    );
  }

  /** PUT /meetings/{id}/agenda/order — TOPs in der gelieferten Reihenfolge anordnen. */
  reorderAgenda(meetingId: Uuid, itemIds: Uuid[]): Observable<AgendaItem[]> {
    return this.http.put<AgendaItem[]>(`${this.base}/meetings/${meetingId}/agenda/order`, {
      itemIds,
    });
  }

  /**
   * POST /meetings/{id}/votes — Live-Abstimmung für einen Antrag anlegen + öffnen,
   * mit Beschlussfrage (fürs Protokoll). Antwort = aktualisierte Sitzung (#Meetings).
   */
  openMeetingVote(
    meetingId: Uuid,
    body: {
      agendaItemId: Uuid;
      question?: string | null;
      options?: string[];
      majorityRule?: 'simple' | 'absolute' | 'two_thirds';
      secret?: boolean;
      eligibleCount?: number | null;
      quorumPercent?: number | null;
    },
  ): Observable<Meeting> {
    return this.http
      .post<MeetingOutWire>(`${this.base}/meetings/${meetingId}/votes`, body)
      .pipe(map(mapMeeting));
  }

  /** DELETE /meetings/{id}/votes/{voteId} — Beschlussfrage (inkl. Stimmen) löschen. */
  deleteMeetingVote(meetingId: Uuid, voteId: Uuid): Observable<Meeting> {
    return this.http
      .delete<MeetingOutWire>(`${this.base}/meetings/${meetingId}/votes/${voteId}`)
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

  /** POST /votes/{id}/cancel — Vote abbrechen (#12): kein Ergebnis, kein Branch. */
  cancelVote(voteId: Uuid): Observable<void> {
    return this.http.post<void>(`${this.base}/votes/${voteId}/cancel`, {});
  }

  /** GET /site-config — öffentliche (auth-freie) aktive Branding-Config (#18). */
  publicSiteConfig(): Observable<PublicSiteConfig> {
    return this.http.get<PublicSiteConfig>(`${this.base}/site-config`);
  }

  // --- protocol (Protokoll-Editor, T-33) -----------------------------------
  /** POST /meetings/{id}/protocol — Protokoll anlegen **oder** laden (idempotent). */
  loadProtocol(meetingId: Uuid): Observable<Protocol> {
    return this.http
      .post<ProtocolOutWire>(`${this.base}/meetings/${meetingId}/protocol`, {})
      .pipe(map(mapProtocol));
  }

  /** GET /meetings/{id}/protocol — Protokoll **lesen** (404 ohne Protokoll).

      Für Reload/Status-Poll (#async-finalize): GETs unterliegen nicht dem
      Default-Write-Rate-Limit — der 4s-Poll über den POST lief schnell in 429. */
  getProtocol(meetingId: Uuid): Observable<Protocol> {
    return this.http
      .get<ProtocolOutWire>(`${this.base}/meetings/${meetingId}/protocol`)
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

  /** POST /protocols/{id}/finalize — →PDF (pytex) → MinIO + MAIL_LIST. */
  finalizeProtocol(protocolId: Uuid): Observable<Protocol> {
    return this.http
      .post<ProtocolOutWire>(`${this.base}/protocols/${protocolId}/finalize`, {})
      .pipe(map(mapProtocol));
  }

  // --- Benachrichtigungs-Präferenzen (#4-2, Self-Service) ------------------
  /** GET /notifications/preferences — eigene Schalter (voller Katalog). */
  listNotificationPreferences(): Observable<NotificationPreference[]> {
    return this.http.get<NotificationPreference[]>(`${this.base}/notifications/preferences`);
  }

  /** PUT /notifications/preferences — eigene Schalter setzen (Bulk). */
  setNotificationPreferences(
    preferences: NotificationPreference[],
  ): Observable<NotificationPreference[]> {
    return this.http.put<NotificationPreference[]>(`${this.base}/notifications/preferences`, {
      preferences,
    });
  }

  // --- OAuth-Grants + MCP-Setup (#MCP, Self-Service) -----------------------
  /** GET /oauth/grants — eigene aktive Agent-/MCP-Grants. */
  listGrants(): Observable<OAuthGrant[]> {
    return this.http.get<OAuthGrant[]>(`${this.base}/oauth/grants`);
  }

  /** DELETE /oauth/grants/{id} — einen eigenen Grant widerrufen. */
  revokeGrant(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/oauth/grants/${id}`);
  }

  /** DELETE /oauth/grants — alle eigenen Grants widerrufen (Not-Aus). */
  revokeAllGrants(): Observable<void> {
    return this.http.delete<void>(`${this.base}/oauth/grants`);
  }

  /** GET /oauth/consent-request — schwebender Authorize-Request fürs Consent-FE. */
  consentRequest(): Observable<ConsentRequest> {
    return this.http.get<ConsentRequest>(`${this.base}/oauth/consent-request`);
  }

  /** POST /oauth/consent — Scope+Lebensdauer bestätigen/ablehnen → Redirect-URL. */
  submitConsent(body: {
    approve: boolean;
    scopes: string[];
    lifetime: string;
  }): Observable<{ redirect: string }> {
    return this.http.post<{ redirect: string }>(`${this.base}/oauth/consent`, body);
  }

  /** GET /mcp/config — fertiger mcpServers-Schnipsel für diese Plattform (P(`mcp.use`)). */
  mcpConfig(): Observable<McpSetup> {
    return this.http.get<McpSetup>(`${this.base}/mcp/config`);
  }

  /** GET /mcp/package — MCP-Quellpaket als .tar.gz (P(`mcp.use`)). */
  downloadMcpPackage(): Observable<Blob> {
    return this.http.get(`${this.base}/mcp/package`, { responseType: 'blob' });
  }

}
