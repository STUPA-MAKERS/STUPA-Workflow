import { Injectable, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Router } from '@angular/router';
import { ApiClient } from '@core/api/api-client.service';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import type { Attendance, Meeting, MeetingMember } from '@core/api/models';
import { ToastService, type SelectOption } from '@stupa-makers/ui-kit';
import { AdminOptionsService } from '../../pages/admin/admin-options.service';
import { MeetingSessionService } from './meeting-session.service';
import { MeetingsTimelineService } from './meetings-timeline.service';
import { longDate } from './meetings-display.util';

/**
 * Meeting metadata dialogs: the two-step create dialog, the settings dialog for
 * protokollant and date or time, and the delete confirmation.
 * MeetingsComponent provides this service.
 */
@Injectable()
export class MeetingDialogsService {
  private readonly api = inject(ApiClient);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly router = inject(Router);
  private readonly options = inject(AdminOptionsService);
  private readonly session = inject(MeetingSessionService);
  private readonly timeline = inject(MeetingsTimelineService);

  readonly createOpen = signal(false);
  /** Step 1 asks for Gremium, date and time. Step 2 asks for name and protokollant. */
  readonly createStep = signal<1 | 2>(1);
  readonly creating = signal(false);
  readonly newTitle = signal('');
  readonly newDate = signal('');
  readonly newTime = signal('');
  /** Optional end time. It must be after `newTime`. */
  readonly newEndTime = signal('');
  /** The Gremium is required. An empty value locks the submit. */
  readonly newGremiumId = signal('');
  /** The protokollant is optional at create time. The meeting needs one before it starts. */
  readonly newProtokollant = signal('');
  readonly createMembers = signal<MeetingMember[]>([]);
  /** The last auto-filled title. Overwrite the title only while the user keeps it. */
  private lastAutoPrefill = '';

  readonly createProtokollantOptions = computed<SelectOption[]>(() => [
    { value: '', label: this.i18n.translate('meetings.protokollant.none') },
    ...this.createMembers().map((m) => ({
      value: m.principalId,
      label: m.displayName || m.email || m.principalId,
    })),
  ]);
  /** Gremien offered in the create dropdown, read from `/gremien`. */
  readonly gremiumOptions = signal<SelectOption[]>([]);

  readonly createStep1Valid = computed(
    () => !!this.newGremiumId() && !!this.newDate().trim() && !!this.newTime().trim(),
  );

  // The settings dialog opens from the toolbar or from the list edit.
  readonly settingsMeeting = signal<Meeting | null>(null);
  readonly settingsRoster = signal<Attendance[]>([]);
  readonly settingsProtokollant = signal<string>('');
  readonly settingsDate = signal<string>('');
  readonly settingsTime = signal<string>('');
  readonly settingsEndTime = signal<string>('');
  readonly savingSettings = signal(false);
  /** A closed meeting locks all settings, also in the list edit. */
  readonly settingsLocked = computed(() => this.settingsMeeting()?.status === 'closed');
  /** A finalized protocol also locks the protokollant. The protocol status is
   *  known only in the detail view of the open meeting. */
  readonly protokollantLocked = computed(
    () =>
      this.session.meeting()?.id === this.settingsMeeting()?.id &&
      !!this.session.protocol()?.isFinal,
  );
  readonly protokollantOptions = computed<SelectOption[]>(() => [
    { value: '', label: this.i18n.translate('meetings.protokollant.none') },
    ...this.settingsRoster().map((a) => ({
      value: a.principalId,
      label: a.displayName || a.email || a.principalId,
    })),
  ]);

  readonly confirmDeleteMeeting = signal<Meeting | null>(null);
  readonly deletingMeeting = signal(false);

  constructor() {
    // Only a meeting manager gets the create dropdown. Without the global
    // `meeting.manage` permission the dropdown offers only the Gremien that the user
    // manages through a Gremium role. The server answers 403 for every other Gremium.
    const canCreate =
      this.auth.can('meeting.manage') || this.auth.sessionManageGremien().length > 0;
    if (canCreate) {
      this.options
        .gremiumOptions()
        .pipe(takeUntilDestroyed())
        .subscribe({
          next: (opts) => {
            if (this.auth.can('meeting.manage')) {
              this.gremiumOptions.set(opts);
              return;
            }
            const managed = new Set(this.auth.sessionManageGremien());
            this.gremiumOptions.set(opts.filter((o) => managed.has(o.value)));
          },
          error: () => this.gremiumOptions.set([]),
        });
    }
  }

  openCreate(): void {
    this.newProtokollant.set('');
    this.createMembers.set([]);
    this.createStep.set(1);
    this.lastAutoPrefill = '';
    // The Gremium can already be set, for example by the overview filter.
    if (this.newGremiumId()) this.loadCreateMembers(this.newGremiumId());
    this.createOpen.set(true);
  }

  closeCreate(): void {
    this.createOpen.set(false);
    this.createStep.set(1);
  }

  /** Go from step 1 to step 2 and prefill the name, such as "Meeting of the
   *  <Gremium> on <date>". A title that the user edited by hand stays. */
  goToCreateStep2(): void {
    if (!this.createStep1Valid()) return;
    const committee =
      this.gremiumOptions().find((o) => o.value === this.newGremiumId())?.label ?? '';
    const suggestion = this.i18n.translate('meetings.create.namePrefill', {
      committee,
      date: longDate(this.newDate().trim(), this.i18n.locale()),
    });
    const current = this.newTitle();
    if (!current.trim() || current === this.lastAutoPrefill) {
      this.newTitle.set(suggestion);
      this.lastAutoPrefill = suggestion;
    }
    this.createStep.set(2);
  }

  backToCreateStep1(): void {
    this.createStep.set(1);
  }

  /** Reload the protokollant candidates after the Gremium changed in the create dialog. */
  onCreateGremiumChange(gremiumId: string): void {
    this.newGremiumId.set(gremiumId);
    this.newProtokollant.set('');
    this.createMembers.set([]);
    if (gremiumId) this.loadCreateMembers(gremiumId);
  }

  private loadCreateMembers(gremiumId: string): void {
    this.api.listMeetingMembers(gremiumId).subscribe({
      next: (rows) => this.createMembers.set(rows),
      error: () => this.createMembers.set([]),
    });
  }

  create(): void {
    const title = this.newTitle().trim();
    const gremiumId = this.newGremiumId();
    const date = this.newDate().trim();
    const startTime = this.newTime().trim();
    const endTime = this.newEndTime().trim();
    // The date and the start time are required. The submit stays locked without them.
    if (!title || !gremiumId || !date || !startTime || this.creating()) return;
    if (endTime && endTime <= startTime) {
      this.toast.error(this.i18n.translate('meetings.create.endBeforeStart'));
      return;
    }
    this.creating.set(true);
    this.api
      .createMeeting({
        title,
        gremiumId,
        date,
        startTime,
        endTime: endTime || null,
        protokollantId: this.newProtokollant() || null,
      })
      .subscribe({
        next: (m) => {
          this.creating.set(false);
          this.newTitle.set('');
          this.newGremiumId.set('');
          this.newDate.set('');
          this.newTime.set('');
          this.newEndTime.set('');
          this.newProtokollant.set('');
          this.createMembers.set([]);
          this.createOpen.set(false);
          this.createStep.set(1);
          this.lastAutoPrefill = '';
          this.toast.success(this.i18n.translate('meetings.toast.created'));
          // Go to the detail route so that the user finds the meeting again.
          void this.router.navigate(['/meetings', m.id]);
        },
        error: () => {
          this.creating.set(false);
          this.toast.error(this.i18n.translate('meetings.toast.createFailed'));
        },
      });
  }

  openSettings(m: Meeting): void {
    this.settingsMeeting.set(m);
    this.settingsProtokollant.set(m.protokollantId ?? '');
    this.settingsDate.set(m.date ?? '');
    this.settingsTime.set(m.startTime ?? '');
    this.settingsEndTime.set(m.endTime ?? '');
    this.settingsRoster.set([]);
    this.api.listAttendance(m.id, { quiet: true }).subscribe({
      next: (rows) => {
        this.settingsRoster.set(rows);
        // Set the selection again after the options load. Without this step the
        // native <select> falls back to "nobody", because the option is still missing.
        this.settingsProtokollant.set(m.protokollantId ?? '');
      },
      error: () => this.settingsRoster.set([]),
    });
  }

  closeSettings(): void {
    this.settingsMeeting.set(null);
  }

  /** Save the protokollant, the date and the time in one PATCH. */
  saveSettings(): void {
    const m = this.settingsMeeting();
    if (!m || this.savingSettings() || this.settingsLocked()) return;
    // The date and the time are required, as in the create dialog.
    if (!this.settingsDate().trim() || !this.settingsTime().trim()) {
      this.toast.error(this.i18n.translate('meetings.toast.dateTimeRequired'));
      return;
    }
    const settingsEnd = this.settingsEndTime().trim();
    if (settingsEnd && settingsEnd <= this.settingsTime().trim()) {
      this.toast.error(this.i18n.translate('meetings.create.endBeforeStart'));
      return;
    }
    this.savingSettings.set(true);
    // A finalized protocol locks the protokollant. The field stays disabled and the
    // request omits the value, because the backend answers 409.
    this.api
      .patchMeeting(m.id, {
        ...(this.protokollantLocked()
          ? {}
          : { protokollantId: this.settingsProtokollant() || null }),
        date: this.settingsDate().trim() || null,
        startTime: this.settingsTime().trim() || null,
        endTime: this.settingsEndTime().trim() || null,
      })
      .subscribe({
        next: (updated) => {
          this.savingSettings.set(false);
          this.settingsMeeting.set(null);
          if (this.session.meeting()?.id === updated.id) this.session.meeting.set(updated);
          this.timeline.replaceInTimeline(updated);
          this.toast.success(this.i18n.translate('meetings.toast.settingsSaved'));
        },
        error: () => {
          this.savingSettings.set(false);
          this.toast.error(this.i18n.translate('meetings.toast.actionFailed'));
        },
      });
  }

  askDeleteMeeting(m: Meeting): void {
    this.confirmDeleteMeeting.set(m);
  }

  doDeleteMeeting(): void {
    const m = this.confirmDeleteMeeting();
    if (!m || this.deletingMeeting()) return;
    this.deletingMeeting.set(true);
    this.api.deleteMeeting(m.id).subscribe({
      next: () => {
        this.deletingMeeting.set(false);
        this.confirmDeleteMeeting.set(null);
        this.timeline.removeFromTimeline(m.id);
        this.toast.success(this.i18n.translate('meetings.toast.deleted'));
        if (this.session.meeting()?.id === m.id) void this.router.navigate(['/meetings']);
      },
      error: () => {
        this.deletingMeeting.set(false);
        this.toast.error(this.i18n.translate('meetings.toast.actionFailed'));
      },
    });
  }
}
