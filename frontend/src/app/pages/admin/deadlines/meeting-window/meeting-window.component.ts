import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { type SettingsForm, settingsForm } from '@shared/forms/settings-form';
import { LoadStateComponent } from '@shared/ui/load-state/load-state.component';
import { InputComponent } from '@stupa-makers/ui-kit';
import { AdminApiService } from '../../admin-api.service';
import { MAX_LEAD_MINUTES, type MeetingSettings } from '../../admin.models';
import { SectionHeaderComponent } from '@shared/ui/section-header/section-header.component';

type Body = Pick<MeetingSettings, 'openLeadMinutes' | 'confirmLeadMinutes'>;

/** The edit state. The fields hold the text of the inputs, so a bad entry stays visible. */
interface Draft {
  open: string;
  confirm: string;
}

/** A whole number in [0, MAX_LEAD_MINUTES], else `null`. */
function minutes(text: string): number | null {
  const t = text.trim();
  if (!/^\d+$/.test(t)) return null;
  const n = Number(t);
  return n <= MAX_LEAD_MINUTES ? n : null;
}

function draftOf(s: MeetingSettings): Draft {
  return { open: String(s.openLeadMinutes), confirm: String(s.confirmLeadMinutes) };
}

/**
 * "Sitzung eröffnen" on the deadlines page: the open window of a planned meeting.
 *
 * Two settings of `GET/PUT /admin/meeting-settings` (permission `admin.deadlines`), both
 * in minutes before the planned start:
 *
 * - `openLeadMinutes` (default 60): before it the meeting does not open; the server
 *   refuses with 409 `meeting_too_early`.
 * - `confirmLeadMinutes` (default 10): before it the open asks in an extra dialog. It
 *   is never larger than `openLeadMinutes` (the server answers 422 otherwise).
 *
 * The section shows nothing without `admin.deadlines` and nothing after a 403, like the
 * guest settings below it. It shares the section layout (the stylesheet) of the guest
 * settings on this page.
 */
@Component({
  selector: 'app-meeting-window-settings',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [SectionHeaderComponent, FormsModule, TranslatePipe, InputComponent, LoadStateComponent],
  templateUrl: './meeting-window.component.html',
  styleUrl: '../guest-settings/guest-settings.component.scss',
})
export class MeetingWindowSettingsComponent {
  private readonly api = inject(AdminApiService);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);

  protected readonly form: SettingsForm<MeetingSettings, Draft> = settingsForm<MeetingSettings, Draft, Body>({
    allowed: () => this.auth.can('admin.deadlines'),
    load: () => this.api.getMeetingSettings(),
    put: (body) => this.api.putMeetingSettings(body),
    draftOf,
    initial: { open: '', confirm: '' },
    body: () => this.body(),
    unchanged: (b, s) =>
      b.openLeadMinutes === s.openLeadMinutes && b.confirmLeadMinutes === s.confirmLeadMinutes,
  });
  readonly saving = this.form.saving;
  protected readonly draft = this.form.draft;

  protected readonly openLead = computed(() => minutes(this.draft().open));
  protected readonly confirmLead = computed(() => minutes(this.draft().confirm));
  protected readonly openError = computed(() =>
    this.openLead() === null ? this.i18n.translate('admin.meetingWindow.range', { max: MAX_LEAD_MINUTES }) : '',
  );
  protected readonly confirmError = computed(() => {
    const confirm = this.confirmLead();
    if (confirm === null) return this.i18n.translate('admin.meetingWindow.range', { max: MAX_LEAD_MINUTES });
    const open = this.openLead();
    return open !== null && confirm > open ? this.i18n.translate('admin.meetingWindow.order') : '';
  });

  /** The body of the PUT, or `null` while a field is invalid. */
  private readonly body = computed<Body | null>(() => {
    const open = this.openLead();
    const confirm = this.confirmLead();
    if (open === null || confirm === null || this.confirmError()) return null;
    return { openLeadMinutes: open, confirmLeadMinutes: confirm };
  });

  /** The section has changes that are not saved. The deadlines page then shows "Speichern". */
  readonly dirty = this.form.dirty;

  /** Every field is valid, so a save can send the section. */
  readonly valid = this.form.valid;

  protected patch(change: Partial<Draft>): void {
    this.form.patch(change);
  }

  /** Send the section. The "Speichern" button of the deadlines page and the form submit call it. */
  save(): void {
    this.form.save();
  }
}
