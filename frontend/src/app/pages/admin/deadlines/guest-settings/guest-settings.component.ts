import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { type SettingsForm, settingsForm } from '@shared/forms/settings-form';
import { LoadStateComponent } from '@shared/ui/load-state/load-state.component';
import {
  InputComponent,
  SelectFieldComponent,
  type SelectOption,
} from '@stupa-makers/ui-kit';
import { AdminApiService } from '../../admin-api.service';
import { type GuestSettings, MAX_CONFIRM_TTL_HOURS, MAX_LINK_TTL_DAYS } from '../../admin.models';
import { SectionHeaderComponent } from '@shared/ui/section-header/section-header.component';

/** The body of the PUT. */
type Body = Pick<GuestSettings, 'confirmTtlHours' | 'linkTtlDays'>;

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
 * "Anträge ohne Konto" on the deadlines page (board Admin-Fristen).
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
  imports: [SectionHeaderComponent, FormsModule, TranslatePipe, InputComponent, SelectFieldComponent, LoadStateComponent],
  templateUrl: './guest-settings.component.html',
  styleUrl: './guest-settings.component.scss',
})
export class GuestSettingsComponent {
  private readonly api = inject(AdminApiService);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);

  protected readonly maxDays = MAX_LINK_TTL_DAYS;

  protected readonly form: SettingsForm<GuestSettings, Draft> = settingsForm<GuestSettings, Draft, Body>({
    allowed: () => this.auth.can('admin.deadlines'),
    load: () => this.api.getGuestSettings(),
    put: (body) => this.api.putGuestSettings(body),
    draftOf,
    initial: { hours: '', mode: 'unlimited', days: '' },
    body: () => this.body(),
    unchanged: (b, s) => b.confirmTtlHours === s.confirmTtlHours && b.linkTtlDays === s.linkTtlDays,
  });
  readonly saving = this.form.saving;
  protected readonly draft = this.form.draft;

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
  private readonly body = computed<Body | null>(() => {
    const hours = this.hours();
    if (hours === null || this.daysError()) return null;
    return { confirmTtlHours: hours, linkTtlDays: this.days() };
  });

  /** The section has changes that are not saved. The deadlines page then shows "Speichern". */
  readonly dirty = this.form.dirty;

  /** Every field is valid, so a save can send the section. */
  readonly valid = this.form.valid;

  protected patch(change: Partial<Draft>): void {
    this.form.patch(change);
  }

  /** "Begrenzt" starts with 30 days, so the field is never empty after the switch. */
  protected setMode(mode: string): void {
    const m: LinkMode = mode === 'days' ? 'days' : 'unlimited';
    this.draft.update((d) => ({ ...d, mode: m, days: m === 'days' && !d.days ? '30' : d.days }));
  }

  /** Send the section. The "Speichern" button of the deadlines page and the form submit call it. */
  save(): void {
    this.form.save();
  }
}
