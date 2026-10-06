import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import type { Subscription } from 'rxjs';
import { I18nService } from '@core/i18n/i18n.service';
import { LocalizedDatePipe } from '@core/i18n/localized-date.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { liveSearch } from '@shared/live-search';
import { AvatarComponent, NoteComponent, SearchPillComponent, SkeletonComponent } from '@shared/ui';
import {
  ButtonComponent,
  CheckboxComponent,
  DialogComponent,
  IconComponent,
  ToastService,
} from '@stupa-makers/ui-kit';
import { AdminApiService } from '../../admin-api.service';
import type {
  AdminPrincipal,
  MergeArea,
  MergeAreaCount,
  MergeConflict,
  MergeConflictKind,
  MergePermission,
  MergePreview,
  MergeResult,
} from '../../admin.models';

/** The steps of the merge: pick the account that stays, check the preview, the result. */
type MergeStep = 'pick' | 'preview' | 'done';

/** At most this many accounts in the pick list. */
const PICK_LIMIT = 50;

/**
 * The refusals of the server with their own message. Every other error gives the
 * generic "Zusammenführen fehlgeschlagen.".
 */
export const MERGE_ERROR_CODES = [
  'principal_already_merged',
  'merge_target_merged',
  'merge_own_account',
  'merge_privileges',
  'principal_erased',
  'merge_target_inactive',
  'merge_retry',
] as const;
export type MergeErrorCode = (typeof MERGE_ERROR_CODES)[number];

function isMergeErrorCode(code: string | undefined): code is MergeErrorCode {
  return (MERGE_ERROR_CODES as readonly string[]).includes(code ?? '');
}

/** The problem body of a 409 `merge_conflict`. */
interface ConflictProblem {
  code?: string;
  errors?: { field: string; msg: string }[] | null;
}

/**
 * "Mit anderem Konto zusammenführen" (Verwaltung → Benutzer): merge an old account (for
 * example one from the Keycloak time) into the account that stays.
 *
 * 1. Pick the account that stays. The list leaves out the old account itself and every
 *    account that is already merged.
 * 2. The preview shows both accounts and, per area, what the merge rewrites, combines and
 *    removes. A real conflict blocks the merge and says why. Else the merge needs an
 *    explicit "I understand" before the danger button works.
 * 3. The result.
 *
 * A dialog on a desktop, a bottom sheet on a phone (`app-dialog` does both). The server
 * decides; the dialog only shows its answers. `merged` fires after a successful merge,
 * `closed` when the dialog closes.
 */
@Component({
  selector: 'app-user-merge',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    TranslatePipe,
    LocalizedDatePipe,
    AvatarComponent,
    NoteComponent,
    SearchPillComponent,
    SkeletonComponent,
    ButtonComponent,
    CheckboxComponent,
    DialogComponent,
    IconComponent,
  ],
  templateUrl: './user-merge.component.html',
  styleUrl: './user-merge.component.scss',
})
export class UserMergeComponent {
  private readonly api = inject(AdminApiService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  /** The old account. The dialog is open while it is set. */
  readonly source = input<AdminPrincipal | null>(null);
  readonly closed = output<void>();
  readonly merged = output<MergeResult>();

  protected readonly step = signal<MergeStep>('pick');
  protected readonly candidates = signal<AdminPrincipal[]>([]);
  protected readonly searched = signal(false);
  protected readonly search = liveSearch<AdminPrincipal[]>({
    run: (q) => this.api.listPrincipals(q),
    result: (list) => {
      const own = this.source()?.id;
      this.candidates.set(
        list.filter((p) => p.id !== own && !p.mergedIntoId).slice(0, PICK_LIMIT),
      );
      this.searched.set(true);
    },
    error: () => {
      this.candidates.set([]);
      this.searched.set(true);
    },
  });

  /** The account that stays, as picked. */
  private readonly target = signal<AdminPrincipal | null>(null);
  protected readonly preview = signal<MergePreview | null>(null);
  protected readonly loadingPreview = signal(false);
  protected readonly previewFailed = signal(false);
  /** The message of a refused preview (a known code of the server), else the generic one. */
  protected readonly previewError = signal<TranslationKey>('admin.users.merge.previewFailed');
  protected readonly understood = signal(false);
  protected readonly merging = signal(false);
  protected readonly result = signal<MergeResult | null>(null);

  /** The areas with at least one row, in the order of the server. */
  protected readonly previewAreas = computed(() => withRows(this.preview()?.areas ?? []));
  protected readonly resultAreas = computed(() => withRows(this.result()?.areas ?? []));
  protected readonly conflicts = computed<MergeConflict[]>(() => this.preview()?.conflicts ?? []);
  protected readonly canMerge = computed(
    () => !!this.preview()?.canMerge && this.understood() && !this.merging(),
  );

  private previewSub?: Subscription;

  constructor() {
    // A new old account starts the dialog from the first step.
    effect(() => {
      const src = this.source();
      untracked(() => this.reset(src));
    });
  }

  private reset(src: AdminPrincipal | null): void {
    this.previewSub?.unsubscribe();
    this.step.set('pick');
    this.target.set(null);
    this.preview.set(null);
    this.result.set(null);
    this.understood.set(false);
    this.merging.set(false);
    this.previewFailed.set(false);
    this.candidates.set([]);
    this.searched.set(false);
    if (src) {
      this.search.sync('');
      this.search.refresh();
    }
  }

  protected name(p: { displayName?: string | null; email?: string | null } | null): string {
    return p?.displayName || p?.email || this.i18n.translate('admin.users.merge.unnamed');
  }

  protected errorKey(code: MergeErrorCode): TranslationKey {
    return `admin.users.merge.error.${code}`;
  }

  /** "session.manage (StuPa)", or the admin role as "Administration (alle Rechte)". */
  protected permissionLabel(p: MergePermission): string {
    const key = p.key === 'admin' ? this.i18n.translate('admin.users.merge.adminRole') : p.key;
    return p.gremium ? `${key} (${p.gremium})` : key;
  }

  protected areaKey(area: MergeArea): TranslationKey {
    return `admin.users.merge.area.${area}`;
  }

  protected conflictKey(kind: MergeConflictKind): TranslationKey {
    return `admin.users.merge.conflict.${kind}`;
  }

  protected fixKey(kind: MergeConflictKind): TranslationKey {
    return `admin.users.merge.fix.${kind}`;
  }

  /** "12 übertragen · 2 zusammengefasst": only the non-zero counts, one separator between. */
  protected counts(a: MergeAreaCount): string {
    const parts: string[] = [];
    if (a.rewritten) parts.push(this.i18n.translate('admin.users.merge.count.rewritten', { n: a.rewritten }));
    if (a.combined) parts.push(this.i18n.translate('admin.users.merge.count.combined', { n: a.combined }));
    if (a.removed) parts.push(this.i18n.translate('admin.users.merge.count.removed', { n: a.removed }));
    return parts.join(' · ');
  }

  protected pick(target: AdminPrincipal): void {
    const src = this.source();
    if (!src) return;
    this.target.set(target);
    this.step.set('preview');
    this.loadPreview(src.id, target.id);
  }

  private loadPreview(sourceId: string, targetId: string): void {
    this.previewSub?.unsubscribe();
    this.preview.set(null);
    this.understood.set(false);
    this.previewFailed.set(false);
    this.loadingPreview.set(true);
    this.previewSub = this.api.previewPrincipalMerge(sourceId, targetId).subscribe({
      next: (p) => {
        this.preview.set(p);
        this.loadingPreview.set(false);
      },
      error: (err: { error?: ConflictProblem }) => {
        const code = err?.error?.code;
        this.previewError.set(
          isMergeErrorCode(code) ? this.errorKey(code) : 'admin.users.merge.previewFailed',
        );
        this.previewFailed.set(true);
        this.loadingPreview.set(false);
      },
    });
  }

  protected back(): void {
    this.previewSub?.unsubscribe();
    this.step.set('pick');
    this.preview.set(null);
    this.understood.set(false);
  }

  protected retryPreview(): void {
    const src = this.source();
    const target = this.target();
    if (src && target) this.loadPreview(src.id, target.id);
  }

  protected confirm(): void {
    const p = this.preview();
    if (!p || !this.canMerge()) return;
    this.merging.set(true);
    this.api.mergePrincipal(p.source.id, p.target.id).subscribe({
      next: (res) => {
        this.merging.set(false);
        this.result.set(res);
        this.step.set('done');
        this.toast.success(this.i18n.translate('admin.users.merge.done'));
        this.merged.emit(res);
      },
      error: (err: { status?: number; error?: ConflictProblem }) => {
        this.merging.set(false);
        if (err?.status === 409 && err.error?.code === 'merge_conflict') {
          // The data changed since the preview: show the server's conflicts, or load the
          // preview again when the answer lists none (a race on a unique key).
          const listed = (err.error.errors ?? []).map(
            (e) => ({ kind: e.field, label: e.msg || null }) as MergeConflict,
          );
          if (listed.length) {
            this.preview.set({ ...p, conflicts: listed, canMerge: false });
          } else {
            this.loadPreview(p.source.id, p.target.id);
          }
          this.understood.set(false);
          this.toast.error(this.i18n.translate('admin.users.merge.conflictToast'));
          return;
        }
        const code = err?.error?.code;
        if (code === 'merge_privileges') {
          // The rights changed since the preview: load it again, it lists them.
          this.loadPreview(p.source.id, p.target.id);
        }
        this.toast.error(
          this.i18n.translate(
            isMergeErrorCode(code) ? this.errorKey(code) : 'admin.users.merge.failed',
          ),
        );
      },
    });
  }

  protected close(): void {
    this.previewSub?.unsubscribe();
    this.closed.emit();
  }
}

function withRows(areas: readonly MergeAreaCount[]): MergeAreaCount[] {
  return areas.filter((a) => a.rewritten || a.combined || a.removed);
}
