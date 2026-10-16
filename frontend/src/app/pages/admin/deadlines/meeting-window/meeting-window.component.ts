import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { NoteComponent } from '@shared/ui/note/note.component';
import { SkeletonComponent } from '@shared/ui/skeleton/skeleton.component';
import { ButtonComponent, InputComponent, ToastService } from '@stupa-makers/ui-kit';
import { AdminApiService } from '../../admin-api.service';
import { MAX_LEAD_MINUTES, type MeetingSettings } from '../../admin.models';

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
 * guest settings below it.
 */
@Component({
  selector: 'app-meeting-window-settings',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslatePipe, ButtonComponent, InputComponent, NoteComponent, SkeletonComponent],
  templateUrl: './meeting-window.component.html',
  // The same section layout as the guest settings on this page.
  styleUrl: '../guest-settings/guest-settings.component.scss',
})
export class MeetingWindowSettingsComponent {
  private readonly api = inject(AdminApiService);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);

  /** The section needs the deadline right. The server checks it again. */
  protected readonly allowed = computed(() => this.auth.can('admin.deadlines'));

  protected readonly loading = signal(true);
  /** The read failed: `forbidden` hides the section, `error` names the failure. */
  protected readonly loadState = signal<'ok' | 'forbidden' | 'error'>('ok');
  protected readonly saving = signal(false);
  /** The stored values; the draft compares against them. */
  private readonly saved = signal<MeetingSettings | null>(null);
  protected readonly draft = signal<Draft>({ open: '', confirm: '' });

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

  protected readonly dirty = computed(() => {
    const s = this.saved();
    const b = this.body();
    if (!s) return false;
    if (!b) return true;
    return b.openLeadMinutes !== s.openLeadMinutes || b.confirmLeadMinutes !== s.confirmLeadMinutes;
  });

  protected readonly canSave = computed(() => this.dirty() && this.body() !== null && !this.saving());

  constructor() {
    if (!this.allowed()) {
      this.loading.set(false);
      this.loadState.set('forbidden');
      return;
    }
    this.api.getMeetingSettings().subscribe({
      next: (s) => this.apply(s),
      error: (err: { status?: number }) => {
        this.loading.set(false);
        this.loadState.set(err?.status === 403 ? 'forbidden' : 'error');
      },
    });
  }

  private apply(s: MeetingSettings): void {
    this.saved.set(s);
    this.draft.set(draftOf(s));
    this.loading.set(false);
    this.loadState.set('ok');
  }

  protected patch(change: Partial<Draft>): void {
    this.draft.update((d) => ({ ...d, ...change }));
  }

  protected save(): void {
    const body = this.body();
    if (!body || !this.canSave()) return;
    this.saving.set(true);
    this.api.putMeetingSettings(body).subscribe({
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
