import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  Injector,
  afterNextRender,
  computed,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { catchError, forkJoin, of } from 'rxjs';
import { FormlyForm, type FormlyFieldConfig } from '@ngx-formly/core';
import { ApiClient } from '@core/api/api-client.service';
import { LOCATION } from '@core/browser/location.token';
import { BrandingService } from '@core/branding/branding.service';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type {
  Application,
  ApplicationComment,
  ApplicationVersion,
  EffectiveForm,
  ProblemDetail,
  TimelineEntry,
  Transition,
  Uuid,
} from '@core/api/models';
import { AnswerViewComponent } from '@shared/forms/answer-view/answer-view.component';
import { toFormlySections } from '@shared/forms/formly-mapper';
import { resolveI18n } from '@shared/forms/i18n-text';
import { applyServerErrors, clearServerErrors } from '@shared/forms/server-errors';
import { flowColorKind } from '@shared/status-kind.util';
import { HistoryComponent, type HistoryEntry } from '@shared/ui/history/history.component';
import { RowMenuComponent, type RowMenuItem, type RowMenuSection } from '@shared/ui/row-menu/row-menu.component';
import { SideSheetComponent } from '@shared/ui/side-sheet/side-sheet.component';
import { StatusTextComponent } from '@shared/ui/status-text/status-text.component';
import { mediaQuerySignal } from '../../layout/media-query';
import { ButtonComponent, DialogComponent, IconComponent, MEDIA, ToastService } from '@stupa-makers/ui-kit';
import { AttachmentsPanelComponent } from '../../pages/applications/attachments-panel.component';
import { applicationTitle, transitionLooks } from '../../pages/applications/applications.util';
import { shortRef } from './apply.util';

type Phase = 'loading' | 'expired' | 'error' | 'ready';

/** The actor value of the applicant in the timeline and the versions. */
const APPLICANT = 'applicant';

/**
 * Status page of the applicant (board Telefon-Status; the same page on the desktop).
 * Routes `/status` and `/antrag/:id` (the magic link `#t=<token>`).
 *
 * The page verifies the token, strips it from the URL and loads the application with
 * the session cookie. It shows:
 *
 * - The header: "Vorgang 3F9A2C71", the title, the status as coloured text "· seit
 *   <stateSince>" (A9), the transitions the applicant may fire, and a menu with
 *   "Anonymisierung beantragen" (Art. 17).
 * - Rows: "Angaben bearbeiten" (disabled with "Im aktuellen Status gesperrt" while
 *   `state.editAllowed` is false), "Anhänge (n)" and "Kommentare (n)". The last two
 *   open a side sheet (a bottom sheet on a phone).
 * - "Angaben": the answers (`app-answer-view`).
 * - "Verlauf" (`app-history`): the status changes with the transition, the versions as
 *   metadata only ("Version 2 gespeichert", "Geändert: …", A11/O17). The server names
 *   the Gremium as actor for everything the applicant did not do (A12/O16); the
 *   applicant's own entries read "Du".
 *
 * "Angaben bearbeiten" turns the page into the edit form with a bar "Speichern legt
 * Version n+1 an". The focus then goes to the title of the bar; "Abbrechen" and a
 * save bring it back to the row. The magic link keeps working without an end when the
 * platform gives links no lifetime; the page then says so (only after the public
 * config loaded, and as the current setting: the verify response has no expiry of the
 * link).
 *
 * The comment composer sends on Enter; Shift+Enter makes a line break, as in the
 * chat of the internal detail page.
 */
@Component({
  selector: 'app-status-timeline',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    RouterLink,
    FormlyForm,
    LocalizedDatePipe,
    AnswerViewComponent,
    HistoryComponent,
    RowMenuComponent,
    SideSheetComponent,
    StatusTextComponent,
    ButtonComponent,
    DialogComponent,
    IconComponent,
    AttachmentsPanelComponent,
    TranslatePipe,
  ],
  templateUrl: './status-timeline.component.html',
  styleUrl: './status-timeline.component.scss',
})
export class StatusTimelineComponent {
  private readonly api = inject(ApiClient);
  private readonly location = inject(LOCATION);
  private readonly branding = inject(BrandingService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly route = inject(ActivatedRoute);
  private readonly injector = inject(Injector);

  private readonly editTitle = viewChild<ElementRef<HTMLElement>>('editTitle');
  private readonly editRow = viewChild<ElementRef<HTMLButtonElement>>('editRow');
  private readonly pageTitle = viewChild<ElementRef<HTMLElement>>('pageTitle');

  protected readonly phone = mediaQuerySignal(MEDIA.phone);

  readonly phase = signal<Phase>('loading');
  readonly application = signal<Application | null>(null);
  readonly effForm = signal<EffectiveForm | null>(null);
  readonly timeline = signal<TimelineEntry[]>([]);
  readonly versions = signal<ApplicationVersion[]>([]);
  readonly comments = signal<ApplicationComment[]>([]);
  readonly attachmentCount = signal<number | null>(null);
  /** Transitions the applicant can fire (actorIsApplicant gate). Empty ⇒ no actions. */
  readonly actions = signal<Transition[]>([]);
  /** Id of the currently firing transition (button spinner / lock). */
  readonly firing = signal<string | null>(null);

  readonly filesOpen = signal(false);
  readonly commentsOpen = signal(false);

  readonly editing = signal(false);
  readonly editFields = signal<FormlyFieldConfig[]>([]);
  editModel: Record<string, unknown> = {};
  editForm = new FormGroup({});
  readonly saving = signal(false);
  /** Magic-link scope: `view` locks editing regardless of status (old links only). */
  private readonly editScope = signal(true);

  readonly commentBody = new FormControl('', {
    nonNullable: true,
    validators: [Validators.required],
  });
  readonly postingComment = signal(false);

  /** GDPR Art. 17: request anonymization of one's own application data. */
  readonly confirmErase = signal(false);
  readonly requestingErasure = signal(false);

  readonly canEdit = computed(
    () => this.editScope() && Boolean(this.application()?.state?.editAllowed),
  );

  /** Why "Angaben bearbeiten" is off: the link (old view scope) or the status. */
  readonly lockReason = computed<TranslationKey | null>(() => {
    if (!this.editScope()) return 'status.edit.linkOnly';
    if (!this.application()?.state?.editAllowed) return 'status.edit.locked';
    return null;
  });

  /**
   * The applicant can add attachments in locked states too, for example receipts and
   * invoices after the decision. Only the magic-link scope counts here. A delete is a
   * data change: the panel gets `canEdit()` for it, and the backend answers 409 in a
   * locked state.
   */
  readonly canUploadAttachments = computed(() => this.editScope());

  /** Days a magic link works; `null`: no end. */
  protected readonly linkTtlDays = this.branding.linkTtlDays;
  /** The config loaded, so `linkTtlDays` is the real setting. */
  protected readonly linkTtlLoaded = this.branding.loaded;

  readonly ref = computed(() => shortRef(this.application()?.id));
  readonly title = computed(() =>
    applicationTitle(this.application()?.data, this.i18n.translate('applications.list.untitled')),
  );
  readonly stateKind = computed(() => flowColorKind(this.application()?.state?.color));
  readonly looks = computed(() => transitionLooks(this.actions()));

  /** The ⋮ menu: the anonymization request. */
  readonly menu = computed<RowMenuSection[]>(() => [
    {
      items: [
        {
          id: 'erase',
          label: this.i18n.translate('applications.detail.eraseRequest'),
          icon: 'lock',
          danger: true,
        },
      ],
    },
  ]);

  /** "3 Dateien" / "1 Datei"; empty until the count is in. */
  readonly filesSub = computed(() => {
    const n = this.attachmentCount();
    if (n === null) return '';
    return this.i18n.translate(n === 1 ? 'status.files.one' : 'status.files.other', { count: n });
  });
  readonly commentsSub = computed(() => {
    const n = this.comments().length;
    return this.i18n.translate(n === 1 ? 'status.comments.one' : 'status.comments.other', {
      count: n,
    });
  });

  /** The labels of the form fields, for the changed fields of a version. */
  private readonly labels = computed(() => {
    const lang = this.i18n.locale();
    const map = new Map<string, string>();
    for (const s of this.effForm()?.sections ?? []) {
      for (const f of s.fields) map.set(f.key, resolveI18n(f.label, lang));
    }
    return map;
  });

  /**
   * "Verlauf": the status changes and the versions, by day. A status change shows the
   * new state in its colour, the transition (A3) and the note. A version shows only
   * its number and the names of the changed fields (A11). The applicant's own entries
   * read "Du"; the server names the Gremium for the others (A12).
   */
  readonly historyEntries = computed<HistoryEntry[]>(() => {
    const t = (key: TranslationKey, params?: Record<string, string | number>) =>
      this.i18n.translate(key, params);
    const actor = (value: string | null): string | null =>
      value === APPLICANT ? t('status.history.you') : value;
    const events = [...this.timeline()].sort((a, b) => a.at.localeCompare(b.at));
    const entries: HistoryEntry[] = events.map((e, i) => {
      const lines: string[] = [];
      if (e.transitionLabel) {
        lines.push(t('applications.history.transition', { label: e.transitionLabel }));
      }
      if (e.note) lines.push(this.noteText(e.note));
      return {
        at: e.at,
        icon: i === 0 ? 'send' : 'flow',
        title: e.toState?.label || e.label,
        kind: flowColorKind(e.toState?.color),
        actor: actor(e.actor),
        body: lines.join('\n') || null,
      };
    });
    for (const v of this.versions()) {
      // Version 1 is the submission, which the first status event already shows.
      if (v.version === 1 && events.length) continue;
      const changed = (v.changedKeys ?? []).map((k) => this.labels().get(k) ?? k);
      entries.push({
        at: v.at,
        icon: 'edit',
        title: t('status.history.version', { version: v.version }),
        actor: actor(v.changedBy),
        body: changed.length
          ? t('status.history.changed', { fields: changed.join(', ') })
          : null,
      });
    }
    return entries;
  });

  constructor() {
    const snap = this.route.snapshot;
    const query = snap.queryParamMap;
    // Magic-link target is /antrag/{id}#t={token}: the token is in the fragment
    // (no Referer/log leak), the app id in the path. The query form (?t=&app=)
    // stays as a fallback.
    const fragmentParams = new URLSearchParams(snap.fragment ?? '');
    const token = fragmentParams.get('t') ?? query.get('t');
    const appId = snap.paramMap.get('id') ?? query.get('app') ?? query.get('id');

    if (token) {
      // Exchange the magic-link token for the HttpOnly applicant cookie.
      this.verifyAndLoad(token, appId);
    } else if (appId) {
      // No token in the URL (e.g. reload after token strip): use the existing
      // cookie session — the interceptor sends it via withCredentials.
      this.load(appId);
    } else {
      this.phase.set('error');
    }
  }

  private verifyAndLoad(token: string, fallbackAppId: string | null): void {
    this.api.verifyMagicLink(token).subscribe({
      next: (res) => {
        this.editScope.set(res.scope === 'edit');
        const appId = res.application_id ?? fallbackAppId ?? '';
        // Strip the token from the URL (avoid History/Referer leak) and keep the
        // app id for a later reload.
        this.stripTokenFromUrl(appId);
        this.load(appId);
      },
      error: (err: { status?: number }) => {
        this.phase.set(err.status === 410 ? 'expired' : 'error');
      },
    });
  }

  /**
   * Strip the magic-link token from the URL.
   *
   * The token must never land in History or in `Referer`. The method keeps the app
   * id, so a reload can reuse the existing cookie session.
   */
  private stripTokenFromUrl(appId: string): void {
    if (typeof window === 'undefined' || typeof history === 'undefined') return;
    try {
      const url = new URL(this.location.href);
      const frag = new URLSearchParams(url.hash.replace(/^#/, ''));
      if (!url.searchParams.has('t') && !frag.has('t')) return;
      url.searchParams.delete('t'); // query form
      frag.delete('t'); // fragment form (/antrag/:id#t=…)
      url.hash = frag.toString() ? `#${frag.toString()}` : '';
      // Keep the app id for a reload. The path /antrag/:id already carries it.
      // Add it only for the ?app= form.
      if (appId && !url.pathname.includes(appId) && !url.searchParams.has('app')) {
        url.searchParams.set('app', appId);
      }
      history.replaceState(history.state, '', url.toString());
    } catch {
      /* History API unavailable — non-critical */
    }
  }

  private load(appId: Uuid): void {
    if (!appId) {
      this.phase.set('error');
      return;
    }
    forkJoin({
      application: this.api.getApplication(appId),
      timeline: this.api.timeline(appId),
      comments: this.api.comments(appId),
      // Optional parts: an error must not break the status page.
      actions: this.api.applicantTransitions(appId).pipe(catchError(() => of([]))),
      versions: this.api.versions(appId).pipe(catchError(() => of([]))),
    }).subscribe({
      next: ({ application, timeline, comments, actions, versions }) => {
        this.application.set(application);
        this.timeline.set(timeline);
        this.comments.set(comments);
        this.actions.set(actions);
        this.versions.set(versions);
        this.loadCount(application.id);
        this.loadForm(application);
      },
      error: (err: { status?: number }) => {
        this.phase.set(err.status === 410 ? 'expired' : 'error');
      },
    });
  }

  /** The number of attachments for the row; the panel in the sheet loads its own list. */
  private loadCount(appId: Uuid): void {
    this.api.listAttachments(appId).subscribe({
      next: (list) => this.attachmentCount.set(list.length),
      error: () => this.attachmentCount.set(null),
    });
  }

  private loadForm(application: Application): void {
    this.api.effectiveForm(application.typeId).subscribe({
      next: (eff) => {
        this.effForm.set(eff);
        this.phase.set('ready');
      },
      // The form definition is optional. Status and timeline stay usable without it.
      error: () => this.phase.set('ready'),
    });
  }

  /** Make the machine note of a vote readable; a tie is a rejection (O18). */
  noteText(note: string): string {
    const resultKeys = {
      'vote:passed': 'vote.result.passed',
      'vote:rejected': 'vote.result.rejected',
      'vote:tie': 'vote.result.rejected',
    } as const;
    const key = resultKeys[note as keyof typeof resultKeys];
    if (key) {
      return this.i18n.translate('status.history.voteNote', {
        result: this.i18n.translate(key),
      });
    }
    return note;
  }

  /** Display name of a comment: "Du" for the own ones, else the author or the Gremium. */
  authorName(comment: ApplicationComment): string {
    if (comment.isOwn) return this.i18n.translate('status.history.you');
    if (comment.author) return comment.author;
    return this.i18n.translate(
      comment.authorKind === 'applicant'
        ? 'applications.comments.author.applicant'
        : 'applications.comments.author.committee',
    );
  }

  /** Fire an applicant transition (actorIsApplicant gate) and reload. */
  fireAction(t: Transition): void {
    const app = this.application();
    if (!app || this.firing()) return;
    this.firing.set(t.id);
    this.api.fireApplicantTransition(app.id, { transitionId: t.id }).subscribe({
      next: () => {
        this.firing.set(null);
        this.load(app.id); // reload so status, history and actions show the new state
      },
      error: () => {
        this.firing.set(null);
        this.toast.error(this.i18n.translate('status.actions.failed'));
      },
    });
  }

  onMenu(item: RowMenuItem): void {
    if (item.id === 'erase') this.confirmErase.set(true);
  }

  // --- edit ----------------------------------------------------------------------

  startEdit(): void {
    const app = this.application();
    const eff = this.effForm();
    if (!app || !eff || !this.canEdit()) return;
    // The server keeps the values of the fields it held back (O21) and of the file
    // fields (their references are no text to edit), so the form leaves them out.
    const files = eff.sections.flatMap((s) => s.fields).filter((f) => f.type === 'file');
    this.editFields.set(
      toFormlySections(eff.sections, this.i18n.locale(), { has_budget: eff.hasBudget }, {
        omitKeys: [...(app.hiddenKeys ?? []), ...files.map((f) => f.key)],
      }),
    );
    // The answers are JSON, so a JSON copy is a deep copy (jsdom has no structuredClone).
    this.editModel = JSON.parse(JSON.stringify(app.data)) as Record<string, unknown>;
    this.editForm = new FormGroup({});
    this.editing.set(true);
    window.scrollTo({ top: 0 });
    this.focusAfterRender(() => this.editTitle());
  }

  cancelEdit(): void {
    this.leaveEdit();
  }

  /**
   * Close the edit mode and give the focus back to the row "Angaben bearbeiten". When
   * the status locked the application (409), the row goes off, so the focus goes to
   * the title of the page.
   */
  private leaveEdit(locked = false): void {
    this.editing.set(false);
    this.focusAfterRender(() => (locked ? this.pageTitle() : this.editRow()));
  }

  /** Focus an element once the view drew it (the edit mode swaps the whole article). */
  private focusAfterRender(target: () => ElementRef<HTMLElement> | undefined): void {
    afterNextRender(() => target()?.nativeElement.focus(), { injector: this.injector });
  }

  save(): void {
    const app = this.application();
    if (!app || !this.canEdit() || this.saving()) return;
    clearServerErrors(this.editFields());
    if (this.editForm.invalid) {
      this.editForm.markAllAsTouched();
      this.toast.error(this.i18n.translate('apply.error.invalid'));
      return;
    }
    this.saving.set(true);
    this.api.updateApplication(app.id, { ...this.editModel }).subscribe({
      next: (updated) => {
        this.application.set(updated);
        this.saving.set(false);
        this.leaveEdit();
        this.toast.success(this.i18n.translate('status.toast.saved'));
        this.api.timeline(app.id, { quiet: true }).subscribe((t) => this.timeline.set(t));
        this.api.versions(app.id).subscribe({ next: (v) => this.versions.set(v), error: () => undefined });
      },
      error: (err: { status?: number; error?: ProblemDetail | null }) => {
        this.saving.set(false);
        if (err.status === 409) {
          this.toast.error(this.i18n.translate('status.toast.locked'));
          this.leaveEdit(true);
          this.api.getApplication(app.id, { quiet: true }).subscribe((a) => this.application.set(a));
          return;
        }
        if (err.status === 422 && err.error?.errors?.length) {
          const placed = applyServerErrors(this.editFields(), err.error.errors, (key) =>
            this.i18n.translate(key),
          );
          if (placed) {
            this.toast.error(this.i18n.translate('apply.error.invalid'));
            return;
          }
        }
        this.toast.error(err.error?.detail ?? this.i18n.translate('status.toast.saveFailed'));
      },
    });
  }

  // --- erasure and comments ------------------------------------------------------

  /** GDPR Art. 17: request anonymization of one's own application data. */
  doRequestErasure(): void {
    const app = this.application();
    if (!app || this.requestingErasure()) return;
    this.requestingErasure.set(true);
    this.api.requestErasure(app.id).subscribe({
      next: () => {
        this.requestingErasure.set(false);
        this.confirmErase.set(false);
        this.toast.success(this.i18n.translate('applications.detail.eraseRequested'));
      },
      error: () => {
        this.requestingErasure.set(false);
        this.toast.error(this.i18n.translate('applications.detail.eraseRequestFailed'));
      },
    });
  }

  addComment(): void {
    const app = this.application();
    if (!app || this.commentBody.invalid || this.postingComment()) return;
    const body = this.commentBody.value.trim();
    if (!body) return;
    this.postingComment.set(true);
    this.api.addComment(app.id, body).subscribe({
      next: () => {
        this.commentBody.reset();
        this.postingComment.set(false);
        this.api.comments(app.id, { quiet: true }).subscribe((c) => this.comments.set(c));
      },
      error: () => {
        this.postingComment.set(false);
        this.toast.error(this.i18n.translate('status.toast.commentFailed'));
      },
    });
  }
}
