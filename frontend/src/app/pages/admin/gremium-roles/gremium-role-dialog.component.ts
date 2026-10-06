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
import { RouterLink } from '@angular/router';
import type { Uuid } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { NoteComponent } from '@shared/ui';
import {
  ButtonComponent,
  CheckboxComponent,
  DialogComponent,
  InputComponent,
} from '@stupa-makers/ui-kit';
import { AdminApiService } from '../admin-api.service';
import { GREMIUM_PERMISSIONS, ROLE_KEY_PATTERN, type GremiumRole } from '../admin.models';

/** The form state of the dialog. */
interface RoleDraft {
  key: string;
  labelDe: string;
  labelEn: string;
  permissions: string[];
}

/** The rights of a new role: a new role can vote. */
const NEW_ROLE_PERMISSIONS = ['vote.cast'];

/**
 * The dialog that creates or edits one gremium role (board Verwaltung-Gremiumrolle-Dialog).
 *
 * The fields are the key (a new role only; it must match `ROLE_KEY_PATTERN`, A10), the
 * German and English name and the rights of the fixed gremium catalogue (O7). The OIDC
 * groups of the role are read-only here; they come from the group mappings, and the link
 * opens that page. "Rolle löschen" shows for an own role only, never for a forced role.
 * The dialog saves the role itself, so a 409 or 422 of the server shows under the key.
 */
@Component({
  selector: 'app-gremium-role-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    RouterLink,
    TranslatePipe,
    ButtonComponent,
    CheckboxComponent,
    DialogComponent,
    InputComponent,
    NoteComponent,
  ],
  templateUrl: './gremium-role-dialog.component.html',
  styleUrl: './gremium-role-dialog.component.scss',
})
export class GremiumRoleDialogComponent {
  private readonly api = inject(AdminApiService);
  private readonly i18n = inject(I18nService);

  readonly open = input(false);
  /** The role to edit. `null` creates a new role. */
  readonly role = input<GremiumRole | null>(null);
  readonly gremiumId = input.required<Uuid>();
  readonly gremiumName = input('');
  /** The OIDC groups that give the role (for `member`: the membership groups). */
  readonly groups = input<readonly string[]>([]);
  /** The principal may read the group mappings: the dialog shows the groups. */
  readonly showGroups = input(false);

  readonly closed = output<void>();
  readonly saved = output<GremiumRole>();
  readonly deleteRequested = output<GremiumRole>();

  protected readonly permissions = GREMIUM_PERMISSIONS;
  protected readonly draft = signal<RoleDraft>({
    key: '',
    labelDe: '',
    labelEn: '',
    permissions: [],
  });
  protected readonly saving = signal(false);
  /** The answer of the server to the last save, shown under the key (409, 422). */
  private readonly serverKeyError = signal('');
  /** The last save failed for another reason than the key. */
  protected readonly saveFailed = signal(false);

  protected readonly isNew = computed(() => this.role() === null);
  protected readonly isMemberRole = computed(() => this.role()?.key === 'member');

  /** A new key must match ROLE_KEY_PATTERN; the key of an existing role never changes. */
  protected readonly keyValid = computed(
    () => !this.isNew() || ROLE_KEY_PATTERN.test(this.draft().key.trim()),
  );
  protected readonly keyError = computed(() => {
    if (this.serverKeyError()) return this.serverKeyError();
    return this.isNew() && this.draft().key.trim() && !this.keyValid()
      ? this.i18n.translate('admin.common.roleKeyInvalid')
      : '';
  });

  protected readonly title = computed<TranslationKey>(() =>
    this.isNew() ? 'admin.gremiumRoles.add' : 'admin.gremiumRoles.edit',
  );

  constructor() {
    // Each opening starts from the role (or an empty draft), never from the last edit.
    effect(() => {
      if (!this.open()) return;
      const role = this.role();
      untracked(() => {
        this.serverKeyError.set('');
        this.saveFailed.set(false);
        this.saving.set(false);
        this.draft.set(
          role
            ? {
                key: role.key,
                labelDe: role.name['de'] ?? '',
                labelEn: role.name['en'] ?? '',
                permissions: [...(role.permissions ?? [])],
              }
            : { key: '', labelDe: '', labelEn: '', permissions: [...NEW_ROLE_PERMISSIONS] },
        );
      });
    });
  }

  protected permLabel(p: string): TranslationKey {
    return `admin.gremiumPerm.${p}` as TranslationKey;
  }

  protected has(p: string): boolean {
    return this.draft().permissions.includes(p);
  }

  protected patch(key: 'key' | 'labelDe' | 'labelEn', value: string): void {
    if (key === 'key') this.serverKeyError.set('');
    this.draft.update((d) => ({ ...d, [key]: value }));
  }

  protected togglePerm(p: string, on: boolean): void {
    this.draft.update((d) => {
      const set = new Set(d.permissions);
      if (on) set.add(p);
      else set.delete(p);
      return { ...d, permissions: GREMIUM_PERMISSIONS.filter((x) => set.has(x)) };
    });
  }

  protected close(): void {
    this.closed.emit();
  }

  protected askDelete(): void {
    const role = this.role();
    if (role && !role.forced) this.deleteRequested.emit(role);
  }

  protected save(): void {
    const d = this.draft();
    if (!this.keyValid() || this.saving()) return;
    const key = d.key.trim();
    const de = d.labelDe.trim() || key;
    const name = { de, en: d.labelEn.trim() || de };
    const permissions = [...d.permissions];
    const role = this.role();
    const req = role
      ? this.api.updateGremiumRole(role.id, { name, permissions })
      : this.api.createGremiumRole(this.gremiumId(), { key, name, permissions });
    this.saving.set(true);
    this.saveFailed.set(false);
    req.subscribe({
      next: (saved) => {
        this.saving.set(false);
        this.saved.emit(saved);
      },
      error: (err: { status?: number }) => {
        this.saving.set(false);
        if (this.isNew() && (err.status === 409 || err.status === 422)) {
          this.serverKeyError.set(
            this.i18n.translate(
              err.status === 409 ? 'admin.gremiumRoles.keyTaken' : 'admin.common.roleKeyInvalid',
            ),
          );
        } else {
          this.serverKeyError.set('');
          this.saveFailed.set(true);
        }
      },
    });
  }
}
