import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { NoteComponent } from '@shared/ui/note/note.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';
import {
  ButtonComponent,
  InputComponent,
  SelectComponent,
  type SelectOption,
  ToastService,
} from '@stupa-makers/ui-kit';
import { AdminApiService } from '../../admin-api.service';
import { type GuestSettings, MAX_CONFIRM_TTL_HOURS, MAX_LINK_TTL_DAYS } from '../../admin.models';

/** The link lifetime as the select shows it: no expiry, or a number of days. */
type LinkMode = 'unlimited' | 'days';

/** The edit state. The fields hold the text of the inputs, so a bad entry stays visible. */
interface Draft {
  hours: string;
  mode: LinkMode;
  days: string;
}

/** A whole number in [min, max], else `null`. */
function wholeIn(text: string, min: number, max: number): number | null {
  const t = text.trim();
  if (!/^\d+$/.test(t)) return null;
  const n = Number(t);
  return n >= min && n <= max ? n : null;
}

function draftOf(s: GuestSettings): Draft {
  return {
    hours: String(s.confirmTtlHours),
    mode: s.linkTtlDays === null ? 'unlimited' : 'days',
    days: s.linkTtlDays === null ? '' : String(s.linkTtlDays),
  };
}

/**
 * "Anträge ohne Konto" on the deadlines page (Z1, board Admin-Fristen).
 *
 * Two settings of `GET/PUT /admin/guest-settings` (permission `admin.deadlines`):
 *
 * - `confirmTtlHours` (1 to 720): the time after which the platform discards a guest
 *   application whose e-mail address nobody confirmed, with its attachments.
 * - `linkTtlDays` (1 to 3650, or `null`): the lifetime of a new personal link.
 *   "Unbegrenzt" sends `null`. A change applies to the links requested from now on.
 *
 * The section shows nothing without `admin.deadlines` and nothing after a 403, so a
 * person without the right never sees a form that the server refuses.
 */
@Component({
  selector: 'app-guest-settings',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslatePipe, ButtonComponent, InputComponent, SelectComponent, NoteComponent, SkeletonComponent],
  templateUrl: './guest-settings.component.html',
  styleUrl: './guest-settings.component.scss',
})
export class GuestSettingsComponent {
  private readonly api = inject(AdminApiService);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  protected readonly maxHours = MAX_CONFIRM_TTL_HOURS;
  protected readonly maxDays = MAX_LINK_TTL_DAYS;

  /** The section needs the deadline right. The server checks it again. */
  protected readonly allowed = computed(() => this.auth.can('admin.deadlines'));

  protected readonly loading = signal(true);
  /** The read failed: `forbidden` hides the section, `error` names the failure. */
  protected readonly loadState = signal<'ok' | 'forbidden' | 'error'>('ok');
  protected readonly saving = signal(false);
  /** The stored values; the draft compares against them. */
  private readonly saved = signal<GuestSettings | null>(null);
  protected readonly draft = signal<Draft>({ hours: '', mode: 'unlimited', days: '' });

  protected readonly modeOptions = computed<SelectOption[]>(() => [
    { value: 'unlimited', label: this.i18n.translate('admin.guest.linkUnlimited') },
    { value: 'days', label: this.i18n.translate('admin.guest.linkDays') },
  ]);

  protected readonly hours = computed(() => wholeIn(this.draft().hours, 1, MAX_CONFIRM_TTL_HOURS));
  protected readonly days = computed(() =>
    this.draft().mode === 'unlimited' ? null : wholeIn(this.draft().days, 1, MAX_LINK_TTL_DAYS),
  );
  protected readonly hoursError = computed(() =>
    this.hours() === null ? this.i18n.translate('admin.guest.hoursRange', { max: MAX_CONFIRM_TTL_HOURS }) : '',
  );
  protected readonly daysError = computed(() =>
    this.draft().mode === 'days' && this.days() === null
      ? this.i18n.translate('admin.guest.daysRange', { max: MAX_LINK_TTL_DAYS })
      : '',
  );

  /** The body of the PUT, or `null` while a field is invalid. */
  private readonly body = computed<Pick<GuestSettings, 'confirmTtlHours' | 'linkTtlDays'> | null>(() => {
    const hours = this.hours();
    if (hours === null || this.daysError()) return null;
    return { confirmTtlHours: hours, linkTtlDays: this.days() };
  });

  protected readonly dirty = computed(() => {
    const s = this.saved();
    const b = this.body();
    if (!s) return false;
    if (!b) return true;
    return b.confirmTtlHours !== s.confirmTtlHours || b.linkTtlDays !== s.linkTtlDays;
  });

  protected readonly canSave = computed(() => this.dirty() && this.body() !== null && !this.saving());

  constructor() {
    if (!this.allowed()) {
      this.loading.set(false);
      this.loadState.set('forbidden');
      return;
    }
    this.api.getGuestSettings().subscribe({
      next: (s) => this.apply(s),
      error: (err: { status?: number }) => {
        this.loading.set(false);
        this.loadState.set(err?.status === 403 ? 'forbidden' : 'error');
      },
    });
  }

  private apply(s: GuestSettings): void {
    this.saved.set(s);
    this.draft.set(draftOf(s));
    this.loading.set(false);
    this.loadState.set('ok');
  }

  protected patch(change: Partial<Draft>): void {
    this.draft.update((d) => ({ ...d, ...change }));
  }

  /** "Begrenzt" starts with 30 days, so the field is never empty after the switch. */
  protected setMode(mode: string): void {
    const m: LinkMode = mode === 'days' ? 'days' : 'unlimited';
    this.draft.update((d) => ({ ...d, mode: m, days: m === 'days' && !d.days ? '30' : d.days }));
  }

  protected save(): void {
    const body = this.body();
    if (!body || !this.canSave()) return;
    this.saving.set(true);
    this.api.putGuestSettings(body).subscribe({
      next: (s) => {
        this.saving.set(false);
        this.apply(s);
        this.toast.success(this.i18n.translate('admin.common.saved'));
      },
      error: () => {
        this.saving.set(false);
        this.toast.error(this.i18n.translate('admin.common.saveFailed'));
      },
    });
  }
}
