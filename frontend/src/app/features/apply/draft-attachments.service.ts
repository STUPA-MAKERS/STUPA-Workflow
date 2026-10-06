import { Injectable, InjectionToken, computed, inject, signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import type { DraftAttachment, ProblemDetail, Uuid } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import { BrandingService } from '@core/branding/branding.service';
import type { TranslationKey } from '@core/i18n/translations';
import { AltchaService } from './altcha.service';

/** One draft file of the wizard: the server row, plus a mark when the server lost it. */
export interface DraftFile extends DraftAttachment {
  /** The submit named it as missing, expired or infected (422); upload it again. */
  failed?: boolean;
}

/** A file on its way to the server. */
export interface PendingUpload {
  key: number;
  filename: string;
  size: number;
  fieldKey: string | null;
}

/** A file the wizard could not upload, with the reason as a translation key. */
export interface UploadFailure {
  filename: string;
  reason: TranslationKey;
}

/** What the draft keeps in `sessionStorage`. */
interface StoredDraft {
  token: string;
  expiresAt: string | null;
  files: DraftFile[];
}

/** The key in `sessionStorage`. The token never goes into `localStorage`, a URL or a log. */
export const DRAFT_FILES_KEY = 'ap.draftFiles';

/**
 * The `sessionStorage` key of one draft. The wizard keeps the default; the capture
 * dialog of the applications page (#11) provides its own key, so the two drafts of one
 * tab never mix.
 */
export const DRAFT_FILES_STORAGE_KEY = new InjectionToken<string>('DRAFT_FILES_STORAGE_KEY', {
  providedIn: 'root',
  factory: () => DRAFT_FILES_KEY,
});

const TOKEN_INVALID = 'draft_token_invalid';
const QUOTA_EXCEEDED = 'draft_quota_exceeded';
const MISSING = 'draft_attachments_missing';

let nextKey = 0;

/**
 * The draft uploads of the apply wizard (Z4), provided by the wizard.
 *
 * - The first upload has no token. An anonymous applicant then solves an ALTCHA
 *   challenge in the background (`AltchaService`); a signed-in one needs none. The
 *   response carries the draft token, and every later upload and delete sends it.
 * - The token and the list of files live in component state and in `sessionStorage`
 *   (this tab only), so a reload keeps them. They never go into `localStorage`, a URL or
 *   a log.
 * - The limits come from the public site config: one file, the number of files and the
 *   bytes of one token. The service checks them before it sends a file; the server
 *   checks them again.
 * - The submit sends `attachmentIds()` and the token. A 422 that names missing ids
 *   (`markFailed`) marks those files; the applicant uploads them again. A token that
 *   the server no longer knows ends the whole draft.
 * - `scopeToFields` keeps the files of the file fields of the current form. A type
 *   switch deletes the files of the fields that the new form does not have (best
 *   effort), so they are not bound and do not count for the limits. The general files
 *   (`fieldKey` null) stay.
 * - `discard` deletes every draft on the server (best effort) and forgets the token;
 *   `clear` only forgets it, after the submit bound the files.
 * - The scan state of a file is the state of the upload response. The service does not
 *   read it again; a file that the scan finds infected shows as lost at the submit
 *   (422).
 */
@Injectable()
export class DraftAttachmentsService {
  private readonly api = inject(ApiClient);
  private readonly auth = inject(AuthService);
  private readonly altcha = inject(AltchaService);
  private readonly branding = inject(BrandingService);
  private readonly storageKey = inject(DRAFT_FILES_STORAGE_KEY);

  private readonly _token = signal<string | null>(null);
  private expiresAt: string | null = null;
  /** The file fields of the current form; `null` until the wizard sets them. */
  private fieldScope: ReadonlySet<string> | null = null;

  /** The uploaded files, oldest first. */
  readonly files = signal<DraftFile[]>([]);
  /** The files on their way to the server. */
  readonly pending = signal<PendingUpload[]>([]);
  /** True while an upload runs. */
  readonly busy = computed(() => this.pending().length > 0);
  /** The limits of the server (or the backend defaults until the config loads). */
  readonly limits = this.branding.attachmentLimits;

  /** The files the server still holds: they count for the limits and the submit. */
  readonly usable = computed(() => this.files().filter((f) => !f.failed));
  readonly count = computed(() => this.usable().length);
  readonly bytes = computed(() => this.usable().reduce((sum, f) => sum + f.size, 0));
  /** True when a file was lost and needs a new upload. */
  readonly hasFailed = computed(() => this.files().some((f) => f.failed));

  constructor() {
    this.restore();
  }

  /** The draft token, for the submit. */
  token(): string | null {
    return this._token();
  }

  /** The ids to bind on the submit: every file the server still holds. */
  attachmentIds(): Uuid[] {
    return this.usable().map((f) => f.id);
  }

  /** The files of one field (`null` = the general block). */
  filesOf(fieldKey: string | null): DraftFile[] {
    return this.files().filter((f) => f.fieldKey === fieldKey);
  }

  /**
   * Upload files one after the other. A file over a limit stays here with its reason;
   * the others go on. Resolves the uploaded files and the failures.
   */
  async upload(
    files: readonly File[],
    opts: { fieldKey?: string | null; isComparisonOffer?: boolean } = {},
  ): Promise<{ uploaded: DraftFile[]; failed: UploadFailure[] }> {
    const fieldKey = opts.fieldKey ?? null;
    const uploaded: DraftFile[] = [];
    const failed: UploadFailure[] = [];
    for (const file of files) {
      const limit = this.limitReason(file);
      if (limit) {
        failed.push({ filename: file.name, reason: limit });
        continue;
      }
      const pending: PendingUpload = {
        key: nextKey++,
        filename: file.name,
        size: file.size,
        fieldKey,
      };
      this.pending.update((list) => [...list, pending]);
      try {
        const draft = await this.send(file, fieldKey, opts.isComparisonOffer === true);
        if (!this.inScope(draft)) {
          // The type changed during the upload: the new form has no such field.
          void this.deleteQuietly([draft.id]);
          continue;
        }
        uploaded.push(draft);
        this.files.update((list) => [...list, draft]);
        this.store();
      } catch (err) {
        failed.push({ filename: file.name, reason: uploadErrorKey(err) });
      } finally {
        this.pending.update((list) => list.filter((p) => p.key !== pending.key));
      }
    }
    return { uploaded, failed };
  }

  /**
   * Remove a file. A failed file only leaves the list; the server no longer has it. A
   * 404 means the same, so the file leaves the list as well. Resolves false when the
   * server refused for another reason.
   */
  async remove(id: Uuid): Promise<boolean> {
    const file = this.files().find((f) => f.id === id);
    if (!file) return true;
    const token = this._token();
    if (!file.failed && token) {
      try {
        await firstValueFrom(this.api.deleteDraftAttachment(id, token));
      } catch (err) {
        if (!(err instanceof HttpErrorResponse && err.status === 404)) return false;
      }
    }
    this.files.update((list) => list.filter((f) => f.id !== id));
    this.store();
    return true;
  }

  /**
   * Read a 422 of the submit. `draft_attachments_missing` names the lost ids
   * (`attachmentIds.<id>`), which get the failed mark; `draft_token_invalid` ends the
   * draft, so every file gets it. Returns the ids that are now failed (empty for any
   * other problem).
   */
  markFailed(problem: ProblemDetail | null | undefined): Uuid[] {
    if (!problem) return [];
    let ids: Uuid[] = [];
    if (problem.code === TOKEN_INVALID) {
      ids = this.usable().map((f) => f.id);
      this._token.set(null);
      this.expiresAt = null;
    } else if (problem.code === MISSING) {
      const named = new Set(
        (problem.errors ?? [])
          .map((e) => /^attachmentIds\.(.+)$/.exec(e.field)?.[1])
          .filter((id): id is string => !!id),
      );
      ids = this.usable()
        .filter((f) => named.has(f.id))
        .map((f) => f.id);
    }
    if (!ids.length) return [];
    const lost = new Set(ids);
    this.files.update((list) => list.map((f) => (lost.has(f.id) ? { ...f, failed: true } : f)));
    this.store();
    return ids;
  }

  /**
   * Keep only the files of these file fields and the general files. The others leave
   * the list at once and the server deletes them (best effort). Resolves when the
   * deletes are done.
   */
  async scopeToFields(fieldKeys: ReadonlySet<string>): Promise<void> {
    this.fieldScope = new Set(fieldKeys);
    const out = this.files().filter((f) => !this.inScope(f));
    if (!out.length) return;
    const gone = new Set(out.map((f) => f.id));
    this.files.update((list) => list.filter((f) => !gone.has(f.id)));
    this.store();
    await this.deleteQuietly(out.filter((f) => !f.failed).map((f) => f.id));
  }

  /** Delete every draft on the server (best effort) and forget the draft. */
  async discard(): Promise<void> {
    const token = this._token();
    const ids = this.attachmentIds();
    this.forget();
    await this.deleteQuietly(ids, token);
  }

  /** True for a general file and for a file of a field of the current form. */
  private inScope(file: DraftFile): boolean {
    return !file.fieldKey || this.fieldScope === null || this.fieldScope.has(file.fieldKey);
  }

  /** Delete drafts on the server; a failed delete is ignored (the draft expires). */
  private async deleteQuietly(ids: Uuid[], token = this._token()): Promise<void> {
    if (!token || !ids.length) return;
    await Promise.all(
      ids.map((id) =>
        firstValueFrom(this.api.deleteDraftAttachment(id, token)).catch(() => undefined),
      ),
    );
  }

  /** Forget the draft after the submit bound its files. */
  clear(): void {
    this.forget();
  }

  private forget(): void {
    this._token.set(null);
    this.expiresAt = null;
    this.files.set([]);
    try {
      sessionStorage.removeItem(this.storageKey);
    } catch {
      /* storage blocked: nothing to clear */
    }
  }

  /** The reason a file cannot go up, or null. The server checks the same limits. */
  private limitReason(file: File): TranslationKey | null {
    const limits = this.limits();
    if (file.size > limits.maxFileBytes) return 'apply.files.error.tooLarge';
    if (this.count() + 1 > limits.maxDraftFiles) return 'apply.files.error.tooMany';
    if (this.bytes() + file.size > limits.maxDraftBytes) return 'apply.files.error.quota';
    return null;
  }

  /**
   * One upload. Without a token an anonymous applicant needs an ALTCHA solution. When
   * the server no longer knows the token (422), the draft starts again once without it.
   */
  private async send(file: File, fieldKey: string | null, isComparisonOffer: boolean): Promise<DraftFile> {
    try {
      return await this.sendOnce(file, fieldKey, isComparisonOffer);
    } catch (err) {
      if (!(err instanceof HttpErrorResponse) || problemCode(err) !== TOKEN_INVALID) throw err;
      this.markFailed({ code: TOKEN_INVALID } as ProblemDetail);
      return this.sendOnce(file, fieldKey, isComparisonOffer);
    }
  }

  private async sendOnce(
    file: File,
    fieldKey: string | null,
    isComparisonOffer: boolean,
  ): Promise<DraftFile> {
    const token = this._token();
    const altcha = !token && !this.auth.isAuthenticated() ? await this.altcha.solve() : null;
    const res = await firstValueFrom(
      this.api.uploadDraftAttachment(file, { token, altcha, fieldKey, isComparisonOffer }),
    );
    this._token.set(res.draftToken);
    this.expiresAt = res.draftExpiresAt;
    return { ...res.attachment, fieldKey };
  }

  private store(): void {
    const token = this._token();
    try {
      if (!token) {
        sessionStorage.removeItem(this.storageKey);
        return;
      }
      const draft: StoredDraft = { token, expiresAt: this.expiresAt, files: this.files() };
      sessionStorage.setItem(this.storageKey, JSON.stringify(draft));
    } catch {
      /* storage blocked: the draft lives as long as the page */
    }
  }

  private restore(): void {
    let raw: string | null = null;
    try {
      raw = sessionStorage.getItem(this.storageKey);
    } catch {
      return;
    }
    if (!raw) return;
    try {
      const draft = JSON.parse(raw) as Partial<StoredDraft>;
      if (typeof draft.token !== 'string' || !draft.token) return;
      // An expired draft is gone on the server: start a new one.
      if (draft.expiresAt && Date.parse(draft.expiresAt) <= Date.now()) {
        sessionStorage.removeItem(this.storageKey);
        return;
      }
      this._token.set(draft.token);
      this.expiresAt = draft.expiresAt ?? null;
      this.files.set(Array.isArray(draft.files) ? draft.files.filter(isDraftFile) : []);
    } catch {
      /* a broken entry: ignore it */
    }
  }
}

function isDraftFile(value: unknown): value is DraftFile {
  const f = value as Partial<DraftFile> | null;
  return !!f && typeof f.id === 'string' && typeof f.filename === 'string' && typeof f.size === 'number';
}

function problemCode(err: HttpErrorResponse): string | undefined {
  return (err.error as ProblemDetail | null)?.code;
}

/** The reason of a refused upload as a translation key. */
export function uploadErrorKey(err: unknown): TranslationKey {
  if (!(err instanceof HttpErrorResponse)) return 'apply.files.error.upload';
  if (problemCode(err) === QUOTA_EXCEEDED) return 'apply.files.error.quota';
  switch (err.status) {
    case 400:
      return 'apply.files.error.altcha';
    case 413:
      return 'apply.files.error.tooLarge';
    case 415:
      return 'apply.files.error.type';
    case 429:
      return 'apply.files.error.rateLimit';
    case 503:
      return 'apply.files.error.unavailable';
    default:
      return 'apply.files.error.upload';
  }
}
