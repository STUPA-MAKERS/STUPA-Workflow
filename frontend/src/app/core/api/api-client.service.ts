import { HttpClient, HttpErrorResponse, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { type Observable, catchError, map, of, throwError } from 'rxjs';
import { I18nService } from '@core/i18n/i18n.service';
import { skipLoading } from '@core/loading/loading.interceptor';
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
  mapState,
  mapTimelineEvent,
  mapTransition,
  mapVersion,
  toApplicationCreateBody,
} from './mappers';
import type {
  CalendarFeed,
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
  ApplicationShareLink,
  ApplicationState,
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
  SearchResults,
  MeetingPageWire,
  MeetingPatchBody,
  NewApplication,
  Page,
  Principal,
  Protocol,
  PublicSiteConfig,
  ProtocolOutWire,
  ProtocolVotesBody,
  RenderJob,
  SignedUrl,
  SignedUrlOutWire,
  StateOutWire,
  TimelineDirection,
  TimelineEntry,
  TimelineEventOutWire,
  ForceStatusBody,
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
 * Typed REST client for the OpenAPI contracts.
 *
 * Responses arrive in the backend wire form (`*Wire`, camelCase via
 * `_CamelModel`). `mappers.ts` translates them into the FE view models and
 * resolves the i18n labels for the current `lang`. Components see only the
 * view models.
 */
@Injectable({ providedIn: 'root' })
export class ApiClient {
  private readonly http = inject(HttpClient);
  private readonly base = inject(API_BASE_URL);
  private readonly i18n = inject(I18nService);

  me(): Observable<Principal> {
    return this.http.get<Principal>(`${this.base}/auth/me`);
  }

  logout(): Observable<LogoutOut> {
    return this.http.post<LogoutOut>(`${this.base}/auth/logout`, {});
  }

  /** GET /calendar/me — own iCal subscription URL (`url` is null until created). */
  myCalendar(): Observable<CalendarFeed> {
    return this.http.get<CalendarFeed>(`${this.base}/calendar/me`, {
      context: skipLoading(),
    });
  }

  /** POST /calendar/me/rotate — generate a new feed token. The old URL stops working. */
  rotateCalendar(): Observable<CalendarFeed> {
    return this.http.post<CalendarFeed>(`${this.base}/calendar/me/rotate`, {});
  }

  /**
   * POST /auth/magic-link/verify — exchange the magic-link token from the mail
   * URL for an HttpOnly applicant session cookie.
   *
   * The server sets the cookie. The response carries no session token.
   * Follow-up requests authenticate with `withCredentials` and store nothing in
   * JavaScript. `MagicLinkVerifyOut` is a plain `BaseModel`, so
   * `application_id` stays snake_case.
   */
  verifyMagicLink(token: string): Observable<MagicLinkVerifyResult> {
    return this.http.post<MagicLinkVerifyResult>(`${this.base}/auth/magic-link/verify`, {
      token,
    });
  }

  /** GET /application-types — the backend returns a Page. The FE wants the list. */
  /** `quiet` skips the global overlay for a background type-cache load. */
  applicationTypes(opts: { quiet?: boolean } = {}): Observable<ApplicationType[]> {
    return this.http
      .get<Page<ApplicationTypeListItemWire>>(`${this.base}/application-types`, {
        context: opts.quiet ? skipLoading() : undefined,
      })
      .pipe(map((page) => page.items.map(mapApplicationType)));
  }

  /** Effective form definition (type fields plus optional pot extra fields). */
  effectiveForm(typeId: Uuid, budgetPotId?: Uuid | null): Observable<EffectiveForm> {
    let params = new HttpParams();
    // The backend expects `?budgetPotId=`, not `?pot=`.
    if (budgetPotId) params = params.set('budgetPotId', budgetPotId);
    return this.http.get<EffectiveForm>(`${this.base}/application-types/${typeId}/form`, {
      params,
      context: skipLoading(),
    });
  }

  /**
   * Effective form of an existing application, taken from its pinned version.
   *
   * The result holds the fields the server validates against, even after the
   * active form version changed.
   */
  applicationForm(applicationId: Uuid): Observable<EffectiveForm> {
    return this.http.get<EffectiveForm>(`${this.base}/applications/${applicationId}/form`, {
      context: skipLoading(),
    });
  }

  listApplications(query: ApplicationListQuery = {}): Observable<Page<ApplicationListItem>> {
    let params = new HttpParams();
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null) params = params.set(key, String(value));
    }
    const lang = this.i18n.locale();
    return this.http
      .get<Page<ApplicationListItemWire>>(`${this.base}/applications`, {
        params,
        context: skipLoading(),
      })
      .pipe(
        map((page) => ({
          ...page,
          items: page.items.map((item) => mapApplicationListItem(item, lang)),
        })),
      );
  }

  /** GET /applications/export.xlsx — filtered list as Excel (P(`application.export`)). */
  exportApplicationsXlsx(query: ApplicationListQuery = {}): Observable<Blob> {
    let params = new HttpParams();
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && key !== 'limit' && key !== 'offset') {
        params = params.set(key, String(value));
      }
    }
    return this.http.get(`${this.base}/applications/export.xlsx`, {
      params,
      responseType: 'blob',
      context: skipLoading(),
    });
  }

  /** GET /applications/tasks — open decisions for the current role. */
  listTasks(): Observable<ApplicationListItem[]> {
    const lang = this.i18n.locale();
    return this.http
      .get<ApplicationListItemWire[]>(`${this.base}/applications/tasks`, {
        context: skipLoading(),
      })
      .pipe(map((items) => items.map((item) => mapApplicationListItem(item, lang))));
  }

  /** `quiet` skips the global overlay for a background reload after a mutation. */
  getApplication(id: Uuid, opts: { quiet?: boolean } = {}): Observable<Application> {
    const lang = this.i18n.locale();
    return this.http
      .get<ApplicationOutWire>(`${this.base}/applications/${id}`, {
        context: opts.quiet ? skipLoading() : undefined,
      })
      .pipe(map((wire) => mapApplication(wire, lang)));
  }

  /**
   * GET /altcha/challenge — fresh, server-signed PoW challenge. Returns `null`
   * when the server turns ALTCHA off (404 → no captcha).
   */
  altchaChallenge(): Observable<AltchaChallenge | null> {
    return this.http.get<AltchaChallenge>(`${this.base}/altcha/challenge`).pipe(
      catchError((err: HttpErrorResponse) =>
        err.status === 404 ? of(null) : throwError(() => err),
      ),
    );
  }

  /** POST /applications — camelCase body. The response is `{ applicationId }`, not a full DTO. */
  createApplication(input: NewApplication): Observable<ApplicationCreated> {
    return this.http
      .post<ApplicationCreatedWire>(
        `${this.base}/applications`,
        toApplicationCreateBody(input),
      )
      .pipe(map(mapApplicationCreated));
  }

  /** PATCH /applications/{id} — update `data` (only when state.editAllowed). */
  updateApplication(id: Uuid, data: Record<string, unknown>): Observable<Application> {
    const lang = this.i18n.locale();
    return this.http
      .patch<ApplicationOutWire>(`${this.base}/applications/${id}`, { data })
      .pipe(map((wire) => mapApplication(wire, lang)));
  }

  /** DELETE /applications/{id} — manager or creator. */
  deleteApplication(id: Uuid): Observable<void> {
    return this.http.delete<void>(`${this.base}/applications/${id}`);
  }

  /**
   * Move an application out of the working list, or bring it back.
   *
   * Reversible, and it destroys nothing: an archived application stays fully readable.
   * Not to be confused with `requestErasure`, which is the GDPR Art. 17 path.
   */
  setApplicationArchived(id: Uuid, archived: boolean): Observable<Application> {
    const url = `${this.base}/applications/${id}/archive`;
    const lang = this.i18n.locale();
    const call = archived
      ? this.http.post<ApplicationOutWire>(url, {})
      : this.http.delete<ApplicationOutWire>(url);
    return call.pipe(map((wire) => mapApplication(wire, lang)));
  }

  /**
   * GET /applications/{id}/shares — every link ever minted for this application.
   *
   * Revoked and expired links stay in the list. "Revocable" only means something if you
   * can see what you revoked, and a link that once existed is part of the record of who
   * published what. None of them carries a `url`.
   */
  applicationShares(id: Uuid): Observable<ApplicationShareLink[]> {
    return this.http.get<ApplicationShareLink[]>(`${this.base}/applications/${id}/shares`, {
      context: skipLoading(),
    });
  }

  /**
   * POST /applications/{id}/shares — mint a public, read-only link.
   *
   * The `url` on the response is the ONLY place the token ever appears. It is not stored
   * and cannot be fetched again, so a caller who loses it mints a new link.
   */
  createApplicationShare(
    id: Uuid,
    input: { ttlDays?: number; label?: string } = {},
  ): Observable<ApplicationShareLink> {
    return this.http.post<ApplicationShareLink>(
      `${this.base}/applications/${id}/shares`,
      input,
    );
  }

  /** DELETE /applications/{id}/shares/{shareId} — stop honouring one link. */
  revokeApplicationShare(id: Uuid, shareId: Uuid): Observable<ApplicationShareLink> {
    return this.http.delete<ApplicationShareLink>(
      `${this.base}/applications/${id}/shares/${shareId}`,
    );
  }

  /** POST /applications/{id}/erasure-request — file a GDPR Art. 17 erasure request. */
  requestErasure(id: Uuid): Observable<void> {
    return this.http.post<void>(`${this.base}/applications/${id}/erasure-request`, {});
  }

  /** `quiet` skips the global overlay for a refresh after a mutation. */
  timeline(id: Uuid, opts: { quiet?: boolean } = {}): Observable<TimelineEntry[]> {
    const lang = this.i18n.locale();
    return this.http
      .get<TimelineEventOutWire[]>(`${this.base}/applications/${id}/timeline`, {
        context: opts.quiet ? skipLoading() : undefined,
      })
      .pipe(map((events) => events.map((e) => mapTimelineEvent(e, lang))));
  }

  /**
   * GET /applications/{id}/versions — version history + diff (principal-only).
   *
   * The diff is language-neutral and holds raw field values. It needs no `lang`
   * mapping.
   */
  versions(id: Uuid): Observable<ApplicationVersion[]> {
    return this.http
      .get<VersionOutWire[]>(`${this.base}/applications/${id}/versions`, {
        context: skipLoading(),
      })
      .pipe(map((items) => items.map(mapVersion)));
  }

  /** `quiet` skips the global overlay for a background refresh. */
  comments(id: Uuid, opts: { quiet?: boolean } = {}): Observable<ApplicationComment[]> {
    return this.http
      .get<CommentOutWire[]>(`${this.base}/applications/${id}/comments`, {
        context: opts.quiet ? skipLoading() : undefined,
      })
      .pipe(map((comments) => comments.map(mapComment)));
  }

  /** Applicants may write only `public` (the backend rejects `internal` with 403). */
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

  /**
   * PATCH /applications/{id}/comments/{commentId} — replace the body.
   *
   * The visibility is deliberately not patchable. Allowed for the author of the
   * comment and for a holder of `application.manage`. The server decides.
   */
  updateComment(id: Uuid, commentId: Uuid, body: string): Observable<ApplicationComment> {
    return this.http
      .patch<CommentOutWire>(`${this.base}/applications/${id}/comments/${commentId}`, { body })
      .pipe(map(mapComment));
  }

  /** DELETE /applications/{id}/comments/{commentId} — author or `application.manage`. */
  deleteComment(id: Uuid, commentId: Uuid): Observable<void> {
    return this.http.delete<void>(`${this.base}/applications/${id}/comments/${commentId}`);
  }

  /**
   * POST /applications/{id}/pdf — start an async PDF render.
   *
   * The answer is 202 with a job in the `pending` state. Poll it with
   * {@link getJob}. Access follows the read scope of the application.
   */
  createApplicationPdf(id: Uuid): Observable<RenderJob> {
    return this.http.post<RenderJob>(`${this.base}/applications/${id}/pdf`, {});
  }

  /** GET /jobs/{jobId} — poll a render job. A poll never shows the overlay. */
  getJob(jobId: Uuid): Observable<RenderJob> {
    return this.http.get<RenderJob>(`${this.base}/jobs/${jobId}`, { context: skipLoading() });
  }

  transitions(id: Uuid): Observable<Transition[]> {
    const lang = this.i18n.locale();
    return this.http
      .get<TransitionOutWire[]>(`${this.base}/applications/${id}/transitions`, {
        context: skipLoading(),
      })
      .pipe(map((items) => items.map((t) => mapTransition(t, lang))));
  }

  fireTransition(id: Uuid, req: TransitionRequestBody): Observable<TransitionResult> {
    return this.http.post<TransitionResult>(`${this.base}/applications/${id}/transition`, req);
  }

  /** GET /applications/{id}/flow-states — all states of the application flow.
   *  They fill the force-status picker. Needs `application.force_status`. */
  flowStates(id: Uuid): Observable<ApplicationState[]> {
    const lang = this.i18n.locale();
    return this.http
      .get<StateOutWire[]>(`${this.base}/applications/${id}/flow-states`, {
        context: skipLoading(),
      })
      .pipe(
        map((items) =>
          items
            .map((s) => mapState(s, lang))
            .filter((s): s is ApplicationState => s !== null),
        ),
      );
  }

  /** POST /applications/{id}/force-status — set a status directly. This privileged
   *  override bypasses guards and transitions. Needs `application.force_status`. */
  forceStatus(id: Uuid, req: ForceStatusBody): Observable<TransitionResult> {
    return this.http.post<TransitionResult>(
      `${this.base}/applications/${id}/force-status`,
      req,
    );
  }

  /** Transitions the magic-link applicant may fire (actorIsApplicant gate). */
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

  /**
   * POST /applications/{id}/attachments — multipart upload (≤10 MB, A(edit)/P).
   *
   * The server scans the file asynchronously with ClamAV. The response carries
   * `scanned=false` until the worker finishes. Errors: 413 (too large), 415
   * (type), 429 (rate limit), 503 (storage off).
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

  /** GET /applications/{id}/attachments — existing attachments (panel hydration). */
  listAttachments(id: Uuid): Observable<Attachment[]> {
    return this.http
      .get<AttachmentOutWire[]>(`${this.base}/applications/${id}/attachments`, {
        context: skipLoading(),
      })
      .pipe(map((list) => list.map(mapAttachment)));
  }

  /**
   * GET /attachments/{id} — short-lived signed MinIO URL. 409 = not yet scanned
   * clean / quarantined, 410 = expired/consumed.
   */
  attachmentUrl(attachmentId: Uuid): Observable<SignedUrl> {
    return this.http
      .get<SignedUrlOutWire>(`${this.base}/attachments/${attachmentId}`, {
        context: skipLoading(),
      })
      .pipe(map(mapSignedUrl));
  }

  /** DELETE /attachments/{id} — delete an attachment (principal/applicant/creator). */
  deleteAttachment(attachmentId: Uuid): Observable<void> {
    return this.http.delete<void>(`${this.base}/attachments/${attachmentId}`);
  }

  /**
   * GET /votes/{id} — vote state + tally.
   *
   * `VoteOut` is a `_CamelModel` (camelCase) and needs no mapper layer. For a
   * `secret` vote the server returns only `counts` in `tally`.
   */
  /** `quiet` skips the global overlay for a tally refresh after casting. */
  getVote(id: Uuid, opts: { quiet?: boolean } = {}): Observable<Vote> {
    return this.http.get<Vote>(`${this.base}/votes/${id}`, {
      context: opts.quiet ? skipLoading() : undefined,
    });
  }

  /**
   * POST /votes/{id}/ballot — cast a ballot (`choice` ∈ config.options).
   *
   * The call is idempotent. The same choice again stays `cast`. A different
   * choice returns `changed`, but only when `config.allowChange` is set. 409 =
   * duplicate or closed, 403 = not eligible. The components evaluate the status.
   */
  castBallot(id: Uuid, choice: string, asDelegation = false): Observable<BallotResult> {
    return this.http.post<BallotResult>(`${this.base}/votes/${id}/ballot`, {
      choice,
      asDelegation,
    });
  }

  /** POST /meetings — create a meeting (P(meeting.manage)). */
  createMeeting(body: MeetingCreateBody): Observable<Meeting> {
    return this.http
      .post<MeetingOutWire>(`${this.base}/meetings`, body)
      .pipe(map(mapMeeting));
  }

  /** GET /gremien/{id}/meeting-members — protokollant candidates (P(session.manage)). */
  listMeetingMembers(gremiumId: Uuid): Observable<MeetingMember[]> {
    return this.http.get<MeetingMember[]>(
      `${this.base}/gremien/${gremiumId}/meeting-members`,
      { context: skipLoading() },
    );
  }

  /** GET /meetings — list meetings (newest first), optionally gremium-filtered. */
  listMeetings(gremiumId?: Uuid): Observable<Meeting[]> {
    let params = new HttpParams();
    if (gremiumId) params = params.set('gremiumId', gremiumId);
    return this.http
      .get<MeetingOutWire[]>(`${this.base}/meetings`, { params, context: skipLoading() })
      .pipe(map((items) => items.map(mapMeeting)));
  }

  /**
   * GET /meetings/timeline — keyset-paginated timeline around *now*.
   *
   * `direction: 'upcoming'` runs forward in time. `'past'` runs backward for
   * the infinite scroll upward. `cursor` comes from `nextCursor` of the
   * previous page. A `null` or empty cursor starts at *now*.
   * `nextCursor === null` marks the end of the direction.
   */
  /**
   * Global search across every kind of record the caller may see.
   *
   * `skipLoading` on purpose: the palette runs this on every keystroke, and the global
   * overlay flashing on each one would be worse than no feedback at all. The palette
   * shows its own inline state.
   */
  search(q: string): Observable<SearchResults> {
    const params = new HttpParams().set('q', q.trim()).set('lang', this.i18n.locale());
    return this.http.get<SearchResults>(`${this.base}/search`, {
      params,
      context: skipLoading(),
    });
  }

  listMeetingsTimeline(opts: {
    direction: TimelineDirection;
    cursor?: string | null;
    limit?: number;
    gremiumId?: Uuid;
    q?: string;
  }): Observable<MeetingPage> {
    let params = new HttpParams().set('direction', opts.direction);
    if (opts.cursor) params = params.set('cursor', opts.cursor);
    if (opts.limit) params = params.set('limit', String(opts.limit));
    if (opts.gremiumId) params = params.set('gremiumId', opts.gremiumId);
    if (opts.q && opts.q.trim()) params = params.set('q', opts.q.trim());
    return this.http
      .get<MeetingPageWire>(`${this.base}/meetings/timeline`, { params, context: skipLoading() })
      .pipe(map(mapMeetingPage));
  }

  /**
   * GET /meetings/gremien — gremien for the meeting-overview filter.
   *
   * The list holds every Gremium with at least ONE meeting the user may read.
   * It is not the list of member Gremien. The response is already camelCase
   * (`id`/`name`) and needs no wire mapping.
   */
  listMeetingFilterGremien(): Observable<{ id: Uuid; name: string }[]> {
    // `skipLoading` like the timeline beside it. This fills a filter dropdown while the
    // list loads its own rows, so without it the page showed its own placeholder AND the
    // global overlay at the same time — two answers to one question.
    return this.http.get<{ id: Uuid; name: string }[]>(`${this.base}/meetings/gremien`, {
      context: skipLoading(),
    });
  }

  /** GET /meetings/{id} — meeting state + votes. */
  /** `quiet` skips the global overlay for a background reload after a vote action. */
  getMeeting(id: Uuid, opts: { quiet?: boolean } = {}): Observable<Meeting> {
    return this.http
      .get<MeetingOutWire>(`${this.base}/meetings/${id}`, {
        context: opts.quiet ? skipLoading() : undefined,
      })
      .pipe(map(mapMeeting));
  }

  /** PATCH /meetings/{id} — set status and/or the active application. */
  patchMeeting(id: Uuid, body: MeetingPatchBody): Observable<Meeting> {
    return this.http
      .patch<MeetingOutWire>(`${this.base}/meetings/${id}`, body)
      .pipe(map(mapMeeting));
  }

  /** DELETE /meetings/{id} — delete a meeting (P(session.manage)/admin). */
  deleteMeeting(id: Uuid): Observable<void> {
    return this.http.delete<void>(`${this.base}/meetings/${id}`);
  }

  /** GET /meetings/{id}/attendance — roster of current members + status. */
  /** `quiet` skips the global overlay for a roster reload in a dialog. */
  listAttendance(meetingId: Uuid, opts: { quiet?: boolean } = {}): Observable<Attendance[]> {
    return this.http.get<Attendance[]>(`${this.base}/meetings/${meetingId}/attendance`, {
      context: opts.quiet ? skipLoading() : undefined,
    });
  }

  /** PUT /meetings/{id}/attendance/me — mark own attendance. */
  setOwnAttendance(meetingId: Uuid, status: AttendanceStatus): Observable<Attendance[]> {
    return this.http.put<Attendance[]>(
      `${this.base}/meetings/${meetingId}/attendance/me`,
      { status },
    );
  }

  /** PUT /meetings/{id}/attendance/{principalId} — set a member (meeting lead). */
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

  /** GET /meetings/{id}/agenda — assigned applications (ordered). */
  /** `quiet` skips the global overlay for a reload after a WS event or mutation. */
  listAgenda(meetingId: Uuid, opts: { quiet?: boolean } = {}): Observable<AgendaItem[]> {
    return this.http.get<AgendaItem[]>(`${this.base}/meetings/${meetingId}/agenda`, {
      context: opts.quiet ? skipLoading() : undefined,
    });
  }

  /** GET /meetings/{id}/agenda/assignable — vote applications not yet on the agenda. */
  listAssignableApplications(meetingId: Uuid): Observable<AssignableApplication[]> {
    return this.http.get<AssignableApplication[]>(
      `${this.base}/meetings/${meetingId}/agenda/assignable`,
      { context: skipLoading() },
    );
  }

  /** POST /meetings/{id}/agenda — put an application on the agenda (meeting lead). */
  addAgendaItem(meetingId: Uuid, applicationId: Uuid): Observable<AgendaItem[]> {
    return this.http.post<AgendaItem[]>(`${this.base}/meetings/${meetingId}/agenda`, {
      applicationId,
    });
  }

  /** POST /meetings/{id}/agenda — create a free-text agenda item (no application). */
  addAgendaFreetext(meetingId: Uuid, title: string): Observable<AgendaItem[]> {
    return this.http.post<AgendaItem[]>(`${this.base}/meetings/${meetingId}/agenda`, {
      title,
    });
  }

  /** DELETE /meetings/{id}/agenda/{itemId} — remove an item from the agenda. */
  removeAgendaItem(meetingId: Uuid, itemId: Uuid): Observable<AgendaItem[]> {
    return this.http.delete<AgendaItem[]>(
      `${this.base}/meetings/${meetingId}/agenda/${itemId}`,
    );
  }

  /** PATCH /meetings/{id}/agenda/{itemId} — set the markdown text of an item. */
  setAgendaBody(meetingId: Uuid, itemId: Uuid, body: string): Observable<AgendaItem[]> {
    return this.http.patch<AgendaItem[]>(
      `${this.base}/meetings/${meetingId}/agenda/${itemId}`,
      { body },
    );
  }

  /** PATCH /meetings/{id}/agenda/{itemId} — rename a free-text item (set title). */
  renameAgendaItem(meetingId: Uuid, itemId: Uuid, title: string): Observable<AgendaItem[]> {
    return this.http.patch<AgendaItem[]>(
      `${this.base}/meetings/${meetingId}/agenda/${itemId}`,
      { title },
    );
  }

  /** PATCH /meetings/{id}/agenda/{itemId} — mark an item (non-)public. */
  setAgendaNonPublic(
    meetingId: Uuid,
    itemId: Uuid,
    nonPublic: boolean,
  ): Observable<AgendaItem[]> {
    return this.http.patch<AgendaItem[]>(
      `${this.base}/meetings/${meetingId}/agenda/${itemId}`,
      { nonPublic },
    );
  }

  /** PUT /meetings/{id}/agenda/order — order items in the supplied sequence. */
  reorderAgenda(meetingId: Uuid, itemIds: Uuid[]): Observable<AgendaItem[]> {
    return this.http.put<AgendaItem[]>(`${this.base}/meetings/${meetingId}/agenda/order`, {
      itemIds,
    });
  }

  /**
   * POST /meetings/{id}/votes — create and open a live vote for an application,
   * with a motion for the protocol. The response is the updated meeting.
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

  /** DELETE /meetings/{id}/votes/{voteId} — delete a motion (incl. ballots). */
  deleteMeetingVote(meetingId: Uuid, voteId: Uuid): Observable<Meeting> {
    return this.http
      .delete<MeetingOutWire>(`${this.base}/meetings/${meetingId}/votes/${voteId}`)
      .pipe(map(mapMeeting));
  }

  /** POST /votes/{id}/open — open a vote, a live one too (P(vote.manage)). */
  openVote(voteId: Uuid): Observable<void> {
    return this.http.post<void>(`${this.base}/votes/${voteId}/open`, {});
  }

  /** POST /votes/{id}/close — close a vote → result → flow branch. */
  closeVote(voteId: Uuid): Observable<void> {
    return this.http.post<void>(`${this.base}/votes/${voteId}/close`, {});
  }

  /** POST /votes/{id}/cancel — cancel a vote: no result, no branch. */
  cancelVote(voteId: Uuid): Observable<void> {
    return this.http.post<void>(`${this.base}/votes/${voteId}/cancel`, {});
  }

  /**
   * DELETE /votes/{id} — remove a standalone vote that never opened.
   *
   * The server answers 409 with `vote_meeting_bound`, `vote_not_draft` or
   * `vote_has_ballots`. Use `cancel` for a vote that is already open.
   */
  deleteVote(voteId: Uuid): Observable<void> {
    return this.http.delete<void>(`${this.base}/votes/${voteId}`);
  }

  /** GET /site-config — public (auth-free) active branding config. */
  publicSiteConfig(): Observable<PublicSiteConfig> {
    return this.http.get<PublicSiteConfig>(`${this.base}/site-config`);
  }

  /** POST /meetings/{id}/protocol — create or load the protocol (idempotent). */
  loadProtocol(meetingId: Uuid): Observable<Protocol> {
    return this.http
      .post<ProtocolOutWire>(`${this.base}/meetings/${meetingId}/protocol`, {})
      .pipe(map(mapProtocol));
  }

  /** GET /meetings/{id}/protocol — read the protocol (404 if none).

      Use this route for reload and status polling. The default write rate limit
      does not apply to a GET. The 4s poll over the POST route soon hit 429. */
  getProtocol(meetingId: Uuid, opts: { quiet?: boolean } = {}): Observable<Protocol> {
    return this.http
      .get<ProtocolOutWire>(`${this.base}/meetings/${meetingId}/protocol`, {
        context: opts.quiet ? skipLoading() : undefined,
      })
      .pipe(map(mapProtocol));
  }

  /** PATCH /protocols/{id} — update markdown. */
  updateProtocol(protocolId: Uuid, markdown: string): Observable<Protocol> {
    return this.http
      .patch<ProtocolOutWire>(`${this.base}/protocols/${protocolId}`, { markdown })
      .pipe(map(mapProtocol));
  }

  /** POST /protocols/{id}/votes — embed vote snippets server-side. */
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

  /**
   * DELETE /protocols/{id} — discard a draft protocol.
   *
   * The scope is the same as the PATCH: whoever may write the minutes may drop
   * them. The server answers 409 once the protocol is `final` or `rendering`.
   */
  deleteProtocol(protocolId: Uuid): Observable<void> {
    return this.http.delete<void>(`${this.base}/protocols/${protocolId}`);
  }

  /** GET /notifications/preferences — own toggles (full catalog). */
  listNotificationPreferences(): Observable<NotificationPreference[]> {
    return this.http.get<NotificationPreference[]>(`${this.base}/notifications/preferences`, {
      context: skipLoading(),
    });
  }

  /** PUT /notifications/preferences — set own toggles (bulk). */
  setNotificationPreferences(
    preferences: NotificationPreference[],
  ): Observable<NotificationPreference[]> {
    return this.http.put<NotificationPreference[]>(`${this.base}/notifications/preferences`, {
      preferences,
    });
  }

  /** GET /oauth/grants — own active agent/MCP grants. */
  listGrants(): Observable<OAuthGrant[]> {
    return this.http.get<OAuthGrant[]>(`${this.base}/oauth/grants`, {
      context: skipLoading(),
    });
  }

  /** DELETE /oauth/grants/{id} — revoke one of your own grants. */
  revokeGrant(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/oauth/grants/${id}`);
  }

  /** DELETE /oauth/grants — revoke all your own grants (kill switch). */
  revokeAllGrants(): Observable<void> {
    return this.http.delete<void>(`${this.base}/oauth/grants`);
  }

  /** GET /oauth/consent-request — pending authorize request for the consent FE. */
  consentRequest(): Observable<ConsentRequest> {
    return this.http.get<ConsentRequest>(`${this.base}/oauth/consent-request`, {
      context: skipLoading(),
    });
  }

  /** POST /oauth/consent — approve/reject scope+lifetime → redirect URL. */
  submitConsent(body: {
    approve: boolean;
    scopes: string[];
    lifetime: string;
  }): Observable<{ redirect: string }> {
    return this.http.post<{ redirect: string }>(`${this.base}/oauth/consent`, body);
  }

  /** GET /mcp/config — ready-made mcpServers snippet for this platform (P(`mcp.use`)). */
  mcpConfig(): Observable<McpSetup> {
    return this.http.get<McpSetup>(`${this.base}/mcp/config`);
  }

  /** GET /mcp/package — MCP source package as .tar.gz (P(`mcp.use`)). */
  downloadMcpPackage(): Observable<Blob> {
    return this.http.get(`${this.base}/mcp/package`, { responseType: 'blob' });
  }

}
