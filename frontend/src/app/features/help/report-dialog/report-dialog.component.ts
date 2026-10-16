import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  computed,
  effect,
  inject,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import type { ProblemDetail } from '@core/api/models';
import {
  TICKET_KINDS,
  TicketsApiService,
  type TicketContext,
  type TicketKind,
} from '@core/api/tickets.service';
import { AuthService } from '@core/auth/auth.service';
import { BrandingService } from '@core/branding/branding.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { ThemeService } from '@core/theme/theme.service';
import { scanStatus } from '@shared/status-kind.util';
import {
  ButtonComponent,
  DialogComponent,
  IconComponent,
  InputComponent,
  SegmentedComponent,
  ToastService,
  type SegmentedOption,
} from '@stupa-makers/ui-kit';
import { AltchaComponent } from '../../apply/altcha.component';
import { formatSize, UPLOAD_ACCEPT } from '../../apply/apply.util';
import {
  DRAFT_FILES_STORAGE_KEY,
  DraftAttachmentsService,
  type DraftFile,
} from '../../apply/draft-attachments.service';
import { HelpService } from '../help.service';
import { browserLabel, currentEnv, reportContext, viewportLabel, type ReportEnv } from '../report-context';

/** The most files one ticket takes (server rule). */
export const MAX_TICKET_FILES = 5;
/** The caps of the server. */
export const MAX_TITLE = 200;
export const MAX_BODY = 10_000;

/** The `sessionStorage` key of the draft files of the dialog, apart from the wizard. */
export const TICKET_DRAFT_FILES_KEY = 'ap.ticketDraftFiles';

/** A plain e-mail check; the server checks again. */
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const KIND_LABEL: Record<TicketKind, TranslationKey> = {
  bug: 'tickets.kind.bug',
  question: 'tickets.kind.question',
  idea: 'tickets.kind.idea',
};

/**
 * The dialog "Problem melden" (frame 17; on a phone the kit dialog is a bottom sheet,
 * frames 27 and 28).
 *
 * The kind (Fehler / Frage / Idee), a short title, the description, files, and the
 * technical context that goes along (page, browser, window, language). Without a session
 * the dialog also asks for the e-mail and an ALTCHA solution. After the send it shows
 * only the number of the ticket: a reporter never reads the ticket again.
 *
 * The files are draft uploads (`POST /apply/attachments`) under their own
 * `sessionStorage` key; the send binds them with `attachmentIds` and the draft token.
 * A screenshot can also be pasted into the dialog. A closed dialog keeps its draft, text
 * and files, until a send.
 */
@Component({
  selector: 'app-report-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    AltchaComponent,
    ButtonComponent,
    DialogComponent,
    IconComponent,
    InputComponent,
    SegmentedComponent,
  ],
  providers: [
    DraftAttachmentsService,
    { provide: DRAFT_FILES_STORAGE_KEY, useValue: TICKET_DRAFT_FILES_KEY },
  ],
  templateUrl: './report-dialog.component.html',
  styleUrl: './report-dialog.component.scss',
})
export class ReportDialogComponent {
  readonly help = inject(HelpService);
  readonly auth = inject(AuthService);
  readonly branding = inject(BrandingService);
  readonly drafts = inject(DraftAttachmentsService);
  private readonly api = inject(TicketsApiService);
  private readonly i18n = inject(I18nService);
  private readonly theme = inject(ThemeService);
  private readonly toast = inject(ToastService);

  /** Read when the dialog opens; a spec replaces it. */
  env: () => ReportEnv = currentEnv;

  protected readonly accept = UPLOAD_ACCEPT;
  protected readonly maxTitle = MAX_TITLE;

  readonly kind = signal<TicketKind>('bug');
  readonly title = signal('');
  readonly body = signal('');
  readonly email = signal('');
  /** The ALTCHA solution, `''` when the server has ALTCHA off, `null` while unsolved. */
  readonly altcha = signal<string | null>(null);
  readonly context = signal<TicketContext>({});
  /** When the dialog opened: the time the report shows with its context. */
  readonly openedAt = signal<Date | null>(null);
  readonly sending = signal(false);
  /** The number of the sent ticket: the dialog then shows only the confirmation. */
  readonly sentNumber = signal<string | null>(null);
  /** The send was refused: the reason under the form. */
  readonly error = signal<TranslationKey | null>(null);
  /** The fields were touched by a send: their errors show from then on. */
  readonly tried = signal(false);

  readonly anonymous = computed(() => !this.auth.isAuthenticated());

  readonly kindOptions = computed<SegmentedOption[]>(() => {
    this.i18n.locale();
    return TICKET_KINDS.map((k) => ({ value: k, label: this.i18n.translate(KIND_LABEL[k]) }));
  });

  readonly titleError = computed(() =>
    this.tried() && !this.title().trim() ? this.i18n.translate('help.report.required') : '',
  );
  readonly bodyMissing = computed(() => this.tried() && !this.body().trim());
  readonly emailError = computed(() => {
    if (!this.tried() || !this.anonymous()) return '';
    const value = this.email().trim();
    if (!value) return this.i18n.translate('help.report.required');
    return EMAIL.test(value) ? '' : this.i18n.translate('help.report.emailInvalid');
  });

  readonly files = this.drafts.files;
  readonly pending = this.drafts.pending;
  readonly full = computed(() => this.drafts.count() + this.pending().length >= MAX_TICKET_FILES);

  /** The rows of "Wird automatisch mitgeschickt". */
  readonly contextRows = computed(() => {
    const c = this.context();
    const rows: { label: TranslationKey; value: string }[] = [];
    if (c.url) rows.push({ label: 'tickets.context.page', value: c.url });
    if (c.userAgent) rows.push({ label: 'tickets.context.browser', value: browserLabel(c.userAgent) });
    if (c.viewport) {
      const lang = c.language === 'en' ? 'English' : 'Deutsch';
      rows.push({ label: 'tickets.context.window', value: `${viewportLabel(c.viewport)} · ${lang}` });
    }
    const at = this.openedAt();
    if (at) {
      const locale = this.i18n.formatLocale();
      // "Do, 15.10.2026, 18:31:07": the weekday without its abbreviation dot.
      const weekday = new Intl.DateTimeFormat(locale, { weekday: 'short' }).format(at).replace(/\.$/, '');
      const rest = new Intl.DateTimeFormat(locale, {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hourCycle: 'h23',
      }).format(at);
      rows.push({ label: 'tickets.context.time', value: `${weekday}, ${rest}` });
    }
    return rows;
  });

  readonly valid = computed(() => {
    if (!this.title().trim() || this.title().trim().length > MAX_TITLE) return false;
    if (!this.body().trim() || this.body().length > MAX_BODY) return false;
    if (this.drafts.busy()) return false;
    if (!this.anonymous()) return true;
    return EMAIL.test(this.email().trim()) && this.altcha() !== null;
  });

  private readonly fileInput = viewChild<ElementRef<HTMLInputElement>>('fileInput');
  private readonly altchaWidget = viewChild(AltchaComponent);

  constructor() {
    // Each opening reads the page it was opened on. A closed draft stays; a sent report
    // starts a fresh one.
    effect(() => {
      if (!this.help.reportOpen()) return;
      untracked(() => this.prepare());
    });
  }

  private prepare(): void {
    if (this.sentNumber() !== null) {
      this.kind.set('bug');
      this.title.set('');
      this.body.set('');
      this.email.set('');
      this.sentNumber.set(null);
    }
    this.resetAltcha();
    this.sending.set(false);
    this.error.set(null);
    this.tried.set(false);
    this.openedAt.set(new Date());
    this.context.set(
      reportContext(this.env(), this.i18n.locale() === 'en' ? 'en' : 'de', this.theme.resolved()),
    );
  }

  /** A solution is good for one send: the widget asks again. */
  private resetAltcha(): void {
    this.altcha.set(null);
    this.altchaWidget()?.state.set('idle');
  }

  setKind(value: string | null): void {
    if (value === 'bug' || value === 'question' || value === 'idea') this.kind.set(value);
  }

  onAltcha(solution: string): void {
    this.altcha.set(solution);
  }

  onAltchaOff(): void {
    this.altcha.set('');
  }

  size(bytes: number): string {
    return formatSize(bytes, this.i18n.formatLocale());
  }

  /** "PNG · " from the file name, or nothing without an extension. */
  fileType(name: string): string {
    const dot = name.lastIndexOf('.');
    return dot > 0 ? `${name.slice(dot + 1).toUpperCase()} · ` : '';
  }

  scanKey(file: DraftFile): TranslationKey {
    return scanStatus(file.scanState).key;
  }

  pickFiles(): void {
    this.fileInput()?.nativeElement.click();
  }

  onPicked(event: Event): void {
    const input = event.target as HTMLInputElement;
    const files = Array.from(input.files ?? []);
    input.value = '';
    void this.addFiles(files);
  }

  /** A pasted screenshot becomes an attachment; pasted text stays text. */
  onPaste(event: ClipboardEvent): void {
    const files = Array.from(event.clipboardData?.files ?? []);
    if (!files.length) return;
    event.preventDefault();
    void this.addFiles(files);
  }

  async addFiles(files: readonly File[]): Promise<void> {
    const room = MAX_TICKET_FILES - this.drafts.count() - this.pending().length;
    if (files.length > room) {
      this.toast.error(this.i18n.translate('help.report.tooManyFiles', { max: MAX_TICKET_FILES }));
    }
    const take = files.slice(0, Math.max(0, room));
    if (!take.length) return;
    const { failed } = await this.drafts.upload(take);
    for (const f of failed) {
      this.toast.error(`${f.filename}: ${this.i18n.translate(f.reason)}`);
    }
  }

  async removeFile(file: DraftFile): Promise<void> {
    const ok = await this.drafts.remove(file.id);
    if (!ok) this.toast.error(this.i18n.translate('help.report.removeFailed'));
  }

  /** Abbrechen, the close button, Escape or the backdrop. The draft and its files stay. */
  cancel(): void {
    this.help.closeReport();
  }

  send(): void {
    this.tried.set(true);
    if (!this.valid() || this.sending()) return;
    this.sending.set(true);
    this.error.set(null);
    const ids = this.drafts.attachmentIds();
    const anonymous = this.anonymous();
    this.api
      .create({
        kind: this.kind(),
        title: this.title().trim(),
        body: this.body().trim(),
        email: anonymous ? this.email().trim() : null,
        context: this.context(),
        attachmentIds: ids.length ? ids : undefined,
        draftToken: ids.length ? this.drafts.token() : null,
        altcha: anonymous ? this.altcha() || null : null,
      })
      .subscribe({
        next: (res) => {
          this.sending.set(false);
          this.drafts.clear();
          this.sentNumber.set(res.number);
        },
        error: (err: unknown) => {
          this.sending.set(false);
          this.error.set(this.refusal(err));
        },
      });
  }

  /** The reason of a refused send. A used ALTCHA solution is spent: solve again. */
  private refusal(err: unknown): TranslationKey {
    if (this.anonymous()) this.resetAltcha();
    if (!(err instanceof HttpErrorResponse)) return 'help.report.error.generic';
    const problem = err.error as ProblemDetail | null;
    if (err.status === 400 && problem?.code === 'altcha_failed') return 'help.report.error.altcha';
    if (err.status === 403) return 'help.report.error.disabled';
    if (err.status === 413) return 'help.report.error.tooLarge';
    if (err.status === 429) return 'help.report.error.rateLimit';
    if (err.status === 422) {
      // A lost draft file: mark it, the reporter attaches it again.
      return this.drafts.markFailed(problem).length ? 'help.report.error.files' : 'help.report.error.invalid';
    }
    return 'help.report.error.generic';
  }
}
