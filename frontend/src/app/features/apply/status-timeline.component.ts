import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import { FormGroup } from '@angular/forms';
import { catchError, forkJoin, of } from 'rxjs';
import { FormlyForm, type FormlyFieldConfig } from '@ngx-formly/core';
import { ApiClient } from '@core/api/api-client.service';
import { LOCATION } from '@core/browser/location.token';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type {
  Application,
  ApplicationComment,
  EffectiveForm,
  FormFieldDef,
  ProblemDetail,
  TimelineEntry,
  Transition,
  Uuid,
} from '@core/api/models';
import { resolveI18n } from '@shared/forms/i18n-text';
import { toFormlyFields } from '@shared/forms/formly-mapper';
import { isFieldVisible } from '@shared/forms/jsonlogic';
import { PageHeaderComponent } from '@shared/ui/page-header/page-header.component';
import { BadgeComponent } from '@stupa-makers/ui-kit';
import { CardComponent } from '@stupa-makers/ui-kit';
import { ButtonComponent } from '@stupa-makers/ui-kit';
import { DialogComponent } from '@stupa-makers/ui-kit';
import { IconComponent } from '@stupa-makers/ui-kit';
import { AttachmentsPanelComponent } from '../../pages/applications/attachments-panel.component';
import { ToastService } from '@stupa-makers/ui-kit';

type Phase = 'loading' | 'expired' | 'error' | 'ready';

interface ReadonlyRow {
  label: string;
  value: string;
}

/**
 * Magic-link status and timeline page.
 *
 * The page verifies the token. It shows the status, the history and the public
 * comments. The applicant can also edit the answer data. The page stays read-only
 * if the current status forbids edits (`state.editAllowed`) or if the link has only
 * the `view` scope.
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
    BadgeComponent,
    CardComponent,
    ButtonComponent,
    DialogComponent,
    IconComponent,
    PageHeaderComponent,
    AttachmentsPanelComponent,
    TranslatePipe,
  ],
  templateUrl: './status-timeline.component.html',
  styleUrl: './status-timeline.component.scss',
})
export class StatusTimelineComponent {
  private readonly api = inject(ApiClient);
  private readonly location = inject(LOCATION);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly route = inject(ActivatedRoute);

  readonly phase = signal<Phase>('loading');
  readonly application = signal<Application | null>(null);
  readonly timeline = signal<TimelineEntry[]>([]);
  readonly comments = signal<ApplicationComment[]>([]);
  readonly readonlyRows = signal<ReadonlyRow[]>([]);
  /** Transitions the applicant can fire (actorIsApplicant gate). Empty ⇒ no actions. */
  readonly actions = signal<Transition[]>([]);
  /** Id of the currently firing transition (button spinner / lock). */
  readonly firing = signal<string | null>(null);

  readonly editFields = signal<FormlyFieldConfig[]>([]);
  editModel: Record<string, unknown> = {};
  readonly editForm = new FormGroup({});
  readonly saving = signal(false);
  /** Magic-link scope: `view` locks editing regardless of status. */
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

  /**
   * The applicant can add attachments in locked states too, for example receipts and
   * invoices after the decision. Only the magic-link scope counts here.
   */
  readonly canUploadAttachments = computed(() => this.editScope());

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
      // Actions are optional: an error must not break the status page.
      actions: this.api.applicantTransitions(appId).pipe(catchError(() => of([]))),
    }).subscribe({
      next: ({ application, timeline, comments, actions }) => {
        this.application.set(application);
        this.timeline.set(timeline);
        this.comments.set(comments);
        this.actions.set(actions);
        this.loadForm(application);
      },
      error: (err: { status?: number }) => {
        this.phase.set(err.status === 410 ? 'expired' : 'error');
      },
    });
  }

  /**
   * Display name of a comment. The fallback is the applicant or the Gremium label,
   * as in the internal view.
   */
  authorName(comment: ApplicationComment): string {
    if (comment.author) return comment.author;
    return this.i18n.translate(
      comment.authorKind === 'applicant'
        ? 'applications.comments.author.applicant'
        : 'applications.comments.author.committee',
    );
  }

  /** Initials for the chat avatar, as in the internal view. */
  initial(name: string): string {
    const parts = name.trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return '?';
    const first = parts[0][0];
    const last = parts.length > 1 ? parts[parts.length - 1][0] : '';
    return (first + last).toUpperCase();
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

  private loadForm(application: Application): void {
    this.api.effectiveForm(application.typeId).subscribe({
      next: (eff) => {
        this.buildView(eff, application);
        this.phase.set('ready');
      },
      // The form definition is optional. Status and timeline stay usable without it.
      error: () => this.phase.set('ready'),
    });
  }

  private buildView(eff: EffectiveForm, application: Application): void {
    const lang = this.i18n.locale();
    const allFields = eff.sections.flatMap((s) => s.fields);

    this.readonlyRows.set(this.buildRows(allFields, application.data, lang));

    if (this.canEdit()) {
      this.editModel = { ...application.data };
      this.editFields.set(
        toFormlyFields(allFields, lang, { has_budget: eff.hasBudget }),
      );
    }
  }

  private buildRows(
    fields: FormFieldDef[],
    data: Record<string, unknown>,
    lang: string,
  ): ReadonlyRow[] {
    const rows: ReadonlyRow[] = [];
    for (const field of fields) {
      if (field.type === 'markdown') continue;
      if (!isFieldVisible(field.visibleIf, data)) continue;
      const value = this.formatValue(field, data[field.key], lang);
      if (value !== '') rows.push({ label: resolveI18n(field.label, lang), value });
    }
    return rows;
  }

  private formatValue(field: FormFieldDef, value: unknown, lang: string): string {
    if (value === null || value === undefined || value === '') return '';
    if (field.type === 'positions') return this.formatPositions(value);
    if (Array.isArray(value)) return value.map((v) => this.optionLabel(field, v, lang)).join(', ');
    if (typeof value === 'boolean')
      return this.i18n.translate(value ? 'common.yes' : 'common.no');
    return this.optionLabel(field, value, lang);
  }

  /** Compact cost positions, as on the internal detail page: count + Σ of preferred offers. */
  private formatPositions(value: unknown): string {
    if (!Array.isArray(value)) return '';
    let total = 0;
    for (const p of value as { offers?: { value?: number | null; preferred?: boolean }[] }[]) {
      const pref = (p.offers ?? []).find((o) => o.preferred);
      total += pref?.value ?? 0;
    }
    const sum = new Intl.NumberFormat(this.i18n.formatLocale(), {
      style: 'currency',
      currency: 'EUR',
    }).format(total);
    return `${value.length} × ${this.i18n.translate('applications.detail.positionsTotal')}: ${sum}`;
  }

  /**
   * Make machine notes in the timeline readable.
   *
   * An automatic transition from a vote carries the note `vote:<result>`. The method
   * shows the translated result instead of the raw value.
   */
  noteText(note: string): string {
    const resultKeys = {
      'vote:passed': 'vote.result.passed',
      'vote:rejected': 'vote.result.rejected',
      'vote:tie': 'vote.result.tie',
    } as const;
    const key = resultKeys[note as keyof typeof resultKeys];
    if (key) {
      return this.i18n.translate('status.history.voteNote', {
        result: this.i18n.translate(key),
      });
    }
    return note;
  }

  private optionLabel(field: FormFieldDef, value: unknown, lang: string): string {
    const opt = field.options?.find((o) => o.value === value);
    return opt ? resolveI18n(opt.label, lang) : String(value);
  }

  save(): void {
    const app = this.application();
    if (!app || !this.canEdit() || this.saving()) return;
    if (this.editForm.invalid) {
      this.editForm.markAllAsTouched();
      return;
    }
    this.saving.set(true);
    this.api.updateApplication(app.id, { ...this.editModel }).subscribe({
      next: (updated) => {
        this.application.set(updated);
        this.saving.set(false);
        this.toast.success(this.i18n.translate('status.toast.saved'));
        this.api.timeline(app.id, { quiet: true }).subscribe((t) => this.timeline.set(t));
      },
      error: (err: { status?: number; error?: ProblemDetail }) => {
        this.saving.set(false);
        if (err.status === 409) {
          this.toast.error(this.i18n.translate('status.toast.locked'));
          this.api.getApplication(app.id, { quiet: true }).subscribe((a) => this.application.set(a));
        } else {
          this.toast.error(err.error?.detail ?? this.i18n.translate('status.toast.saveFailed'));
        }
      },
    });
  }

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
