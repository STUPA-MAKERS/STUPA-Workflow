import { monthOptions } from '@shared/month-options';
import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { type SettingsForm, settingsForm } from '@shared/forms/settings-form';
import { LoadStateComponent } from '@shared/ui/load-state/load-state.component';
import { InputComponent, SectionComponent, SelectFieldComponent } from '@stupa-makers/ui-kit';
import { AdminApiService } from '../../admin-api.service';
import { MEETING_PERIOD_BOUNDS, type MeetingPeriodKey, type MeetingPeriods } from '../../admin.models';

/** The edit state: the text of each input, so a bad entry stays visible. */
type Draft = Readonly<Record<MeetingPeriodKey, string>>;

/** One input of the section. */
interface Field {
  readonly key: MeetingPeriodKey;
  readonly label: TranslationKey;
  /** The i18n key of the unit behind the number, or `null` for none. */
  readonly unit: TranslationKey | null;
}

const DAYS: TranslationKey = 'admin.meetingPeriods.days';

const FIELDS: readonly Field[] = [
  { key: 'inviteDaysOrdinary', label: 'admin.meetingPeriods.inviteDaysOrdinary', unit: DAYS },
  { key: 'inviteDaysExtraordinary', label: 'admin.meetingPeriods.inviteDaysExtraordinary', unit: DAYS },
  { key: 'lateExcuseDays', label: 'admin.meetingPeriods.lateExcuseDays', unit: DAYS },
  { key: 'circularMinDays', label: 'admin.meetingPeriods.circularMinDays', unit: DAYS },
  { key: 'absenceLimit', label: 'admin.meetingPeriods.absenceLimit', unit: null },
  { key: 'termStartMonth', label: 'admin.meetingPeriods.termStartMonth', unit: null },
];

const KEYS: readonly MeetingPeriodKey[] = FIELDS.map((f) => f.key);

/** A whole number inside the bounds of the field, else `null`. */
function numberOf(key: MeetingPeriodKey, text: string): number | null {
  const t = text.trim();
  if (!/^\d+$/.test(t)) return null;
  const n = Number(t);
  const [min, max] = MEETING_PERIOD_BOUNDS[key];
  return n >= min && n <= max ? n : null;
}

function draftOf(s: MeetingPeriods): Draft {
  return Object.fromEntries(KEYS.map((k) => [k, String(s[k])])) as Draft;
}

const EMPTY: Draft = Object.fromEntries(KEYS.map((k) => [k, ''])) as Draft;

/**
 * "Sitzungsfristen" on the deadlines page: the periods of the Geschäftsordnung (§ 000917).
 *
 * Seven settings of `GET/PUT /admin/meeting-periods` (permission `admin.deadlines`): the
 * invitation periods of an ordinary and of every other meeting, the period of the
 * protocol draft, the period of a late excuse, the shortest window of an
 * Umlaufbeschluss (all in days), the number of unexcused absences that ends a Mandat
 * and the month in which a term starts.
 *
 * The section shows nothing without `admin.deadlines` and nothing after a 403. It shares
 * the section layout (the stylesheet) of the guest settings on this page.
 */
@Component({
  selector: 'app-meeting-periods-settings',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [SectionComponent, FormsModule, TranslatePipe, InputComponent, SelectFieldComponent, LoadStateComponent],
  templateUrl: './meeting-periods.component.html',
  styleUrl: '../guest-settings/guest-settings.component.scss',
})
export class MeetingPeriodsSettingsComponent {
  private readonly api = inject(AdminApiService);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);

  protected readonly fields = FIELDS;
  /** The twelve months by name, for the start of the term. */
  protected readonly months = computed(() => monthOptions(this.i18n.formatLocale()));

  protected readonly form: SettingsForm<MeetingPeriods, Draft> = settingsForm<MeetingPeriods, Draft, MeetingPeriods>({
    allowed: () => this.auth.can('admin.deadlines'),
    load: () => this.api.getMeetingPeriods(),
    put: (body) => this.api.putMeetingPeriods(body),
    draftOf,
    initial: EMPTY,
    body: () => this.body(),
    unchanged: (b, s) => KEYS.every((k) => b[k] === s[k]),
  });
  readonly saving = this.form.saving;
  protected readonly draft = this.form.draft;

  /** The error text of each field, '' for a valid one. */
  protected readonly errors = computed<Readonly<Record<MeetingPeriodKey, string>>>(() => {
    const draft = this.draft();
    return Object.fromEntries(
      KEYS.map((k) => {
        const [min, max] = MEETING_PERIOD_BOUNDS[k];
        const bad = numberOf(k, draft[k]) === null;
        return [k, bad ? this.i18n.translate('admin.meetingPeriods.range', { min, max }) : ''];
      }),
    ) as Record<MeetingPeriodKey, string>;
  });

  /** The body of the PUT, or `null` while a field is invalid. */
  private readonly body = computed<MeetingPeriods | null>(() => {
    const draft = this.draft();
    const pairs = KEYS.map((k) => [k, numberOf(k, draft[k])] as const);
    if (pairs.some(([, n]) => n === null)) return null;
    return Object.fromEntries(pairs) as unknown as MeetingPeriods;
  });

  /** The section has changes that are not saved. The deadlines page then shows "Speichern". */
  readonly dirty = this.form.dirty;

  /** Every field is valid, so a save can send the section. */
  readonly valid = this.form.valid;

  protected patch(key: MeetingPeriodKey, text: string): void {
    this.form.patch({ [key]: text });
  }

  /** Back to the stored values, for "Verwerfen" of the page. */
  discard(): void {
    this.form.reset();
  }

  /** Send the section. The "Speichern" button of the deadlines page and the form submit call it. */
  save(): void {
    this.form.save();
  }
}
