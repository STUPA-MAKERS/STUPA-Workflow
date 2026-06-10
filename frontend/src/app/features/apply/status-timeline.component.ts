import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import { FormGroup } from '@angular/forms';
import { catchError, forkJoin, of } from 'rxjs';
import { FormlyForm, type FormlyFieldConfig } from '@ngx-formly/core';
import { ApiClient } from '@core/api/api-client.service';
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
import { BadgeComponent } from '@shared/ui/badge/badge.component';
import { CardComponent } from '@shared/ui/card/card.component';
import { ButtonComponent } from '@shared/ui/button/button.component';
import { IconComponent } from '@shared/ui/icon/icon.component';
import { ToastService } from '@shared/ui/toast/toast.service';

type Phase = 'loading' | 'expired' | 'error' | 'ready';

interface ReadonlyRow {
  label: string;
  value: string;
}

/**
 * Magic-Link Status-/Timeline-Seite (T-30, flows §2). Verifiziert den Token,
 * zeigt Status, Verlauf und öffentliche Kommentare und erlaubt das Bearbeiten der
 * Antwortdaten — read-only, wenn der aktuelle Status nicht editierbar ist
 * (`state.editAllowed`) oder der Link nur `view`-Scope hat.
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
    IconComponent,
    TranslatePipe,
  ],
  templateUrl: './status-timeline.component.html',
  styleUrl: './status-timeline.component.scss',
})
export class StatusTimelineComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly route = inject(ActivatedRoute);

  readonly phase = signal<Phase>('loading');
  readonly application = signal<Application | null>(null);
  readonly timeline = signal<TimelineEntry[]>([]);
  readonly comments = signal<ApplicationComment[]>([]);
  readonly readonlyRows = signal<ReadonlyRow[]>([]);
  /** Vom Antragsteller feuerbare Übergänge (actorIsApplicant-Gate); leer ⇒ keine Aktionen. */
  readonly actions = signal<Transition[]>([]);
  /** Id des gerade feuernden Übergangs (Button-Spinner / Sperre). */
  readonly firing = signal<string | null>(null);

  readonly editFields = signal<FormlyFieldConfig[]>([]);
  editModel: Record<string, unknown> = {};
  readonly editForm = new FormGroup({});
  readonly saving = signal(false);
  /** Magic-Link-Scope: `view` sperrt die Bearbeitung unabhängig vom Status. */
  private readonly editScope = signal(true);

  readonly commentBody = new FormControl('', {
    nonNullable: true,
    validators: [Validators.required],
  });
  readonly postingComment = signal(false);

  readonly canEdit = computed(
    () => this.editScope() && Boolean(this.application()?.state?.editAllowed),
  );

  constructor() {
    const snap = this.route.snapshot;
    const query = snap.queryParamMap;
    // Magic-Link-Ziel ist /antrag/{id}#t={token}: Token steht im **Fragment**
    // (kein Referer-/Log-Leak, security.md §1), die App-ID im Pfad. Query-Form
    // (?t=&app=) bleibt als Fallback erhalten.
    const fragmentParams = new URLSearchParams(snap.fragment ?? '');
    const token = fragmentParams.get('t') ?? query.get('t');
    const appId = snap.paramMap.get('id') ?? query.get('app') ?? query.get('id');

    if (token) {
      // Magic-Link-Token gegen die HttpOnly-Applicant-Cookie eintauschen.
      this.verifyAndLoad(token, appId);
    } else if (appId) {
      // Kein Token in der URL (z. B. Reload nach Token-Strip): bestehende
      // Cookie-Session nutzen — der Interceptor sendet sie via withCredentials.
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
        // Token aus der URL entfernen (History-/Referer-Leak vermeiden) und die
        // App-ID für einen späteren Reload behalten.
        this.stripTokenFromUrl(appId);
        this.load(appId);
      },
      error: (err: { status?: number }) => {
        this.phase.set(err.status === 410 ? 'expired' : 'error');
      },
    });
  }

  /**
   * Magic-Link-Token aus der URL streichen (S3): er darf nicht in History oder
   * `Referer` landen. App-ID bleibt erhalten, damit ein Reload die bestehende
   * Cookie-Session weiterverwenden kann.
   */
  private stripTokenFromUrl(appId: string): void {
    if (typeof window === 'undefined' || typeof history === 'undefined') return;
    try {
      const url = new URL(window.location.href);
      const frag = new URLSearchParams(url.hash.replace(/^#/, ''));
      if (!url.searchParams.has('t') && !frag.has('t')) return;
      url.searchParams.delete('t'); // Query-Form
      frag.delete('t'); // Fragment-Form (/antrag/:id#t=…)
      url.hash = frag.toString() ? `#${frag.toString()}` : '';
      // App-ID für einen Reload erhalten. Der Pfad /antrag/:id trägt sie bereits;
      // nur für die ?app=-Form ergänzen.
      if (appId && !url.pathname.includes(appId) && !url.searchParams.has('app')) {
        url.searchParams.set('app', appId);
      }
      history.replaceState(history.state, '', url.toString());
    } catch {
      /* History-API nicht verfügbar — unkritisch */
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
      // Aktionen sind optional: ein Fehler darf die Statusseite nicht kippen.
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

  /** Anzeigename eines Kommentars (Fallback: Antragsteller:in/Gremium) — wie intern. */
  authorName(comment: ApplicationComment): string {
    if (comment.author) return comment.author;
    return this.i18n.translate(
      comment.authorKind === 'applicant'
        ? 'applications.comments.author.applicant'
        : 'applications.comments.author.committee',
    );
  }

  /** Initialen für den Chat-Avatar (wie intern). */
  initial(name: string): string {
    const parts = name.trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return '?';
    const first = parts[0][0];
    const last = parts.length > 1 ? parts[parts.length - 1][0] : '';
    return (first + last).toUpperCase();
  }

  /** Einen Antragsteller-Übergang feuern (actorIsApplicant-Gate) und neu laden. */
  fireAction(t: Transition): void {
    const app = this.application();
    if (!app || this.firing()) return;
    this.firing.set(t.id);
    this.api.fireApplicantTransition(app.id, { transitionId: t.id }).subscribe({
      next: () => {
        this.firing.set(null);
        this.load(app.id); // Status/Verlauf/Aktionen spiegeln den neuen State.
      },
      error: () => {
        this.firing.set(null);
        this.toast.error(this.i18n.translate('status.actions.failed'));
      },
    });
  }

  private loadForm(application: Application): void {
    this.api.effectiveForm(application.typeId, application.budgetPotId).subscribe({
      next: (eff) => {
        this.buildView(eff, application);
        this.phase.set('ready');
      },
      // Form-Definition optional: Status/Timeline bleiben auch ohne sie nutzbar.
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
        toFormlyFields(allFields, lang, { has_budget: Boolean(eff.budgetPotId) }),
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
    if (Array.isArray(value)) return value.map((v) => this.optionLabel(field, v, lang)).join(', ');
    if (typeof value === 'boolean')
      return this.i18n.translate(value ? 'common.yes' : 'common.no');
    return this.optionLabel(field, value, lang);
  }

  private optionLabel(field: FormFieldDef, value: unknown, lang: string): string {
    const opt = field.options?.find((o) => o.value === value);
    return opt ? resolveI18n(opt.label, lang) : String(value);
  }

  // --- actions -------------------------------------------------------------
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
        this.api.timeline(app.id).subscribe((t) => this.timeline.set(t));
      },
      error: (err: { status?: number; error?: ProblemDetail }) => {
        this.saving.set(false);
        if (err.status === 409) {
          this.toast.error(this.i18n.translate('status.toast.locked'));
          this.api.getApplication(app.id).subscribe((a) => this.application.set(a));
        } else {
          this.toast.error(err.error?.detail ?? this.i18n.translate('status.toast.saveFailed'));
        }
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
        this.api.comments(app.id).subscribe((c) => this.comments.set(c));
      },
      error: () => {
        this.postingComment.set(false);
        this.toast.error(this.i18n.translate('status.toast.commentFailed'));
      },
    });
  }
}
