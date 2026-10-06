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
import { Router } from '@angular/router';
import { ApiClient } from '@core/api/api-client.service';
import type { GuestsMode, MeetingDefaults, MeetingMember } from '@core/api/models';
import { AuthService } from '@core/auth/auth.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import {
  ButtonComponent,
  DatepickerComponent,
  DialogComponent,
  InputComponent,
  SelectComponent,
  TimeInputComponent,
  ToastService,
  type SelectOption,
} from '@stupa-makers/ui-kit';
import { AdminOptionsService } from '../../../pages/admin/admin-options.service';
import { longDate } from '../meetings-display.util';
import { PublicJoinSettingsComponent } from '../public-join/public-join-settings.component';

/**
 * "Sitzung anlegen" in two steps.
 *
 * Step 1 asks for the Gremium, the date, the start and an optional end. Step 2 asks
 * for the title (prefilled from step 1) and the minute-taker. Only members with
 * `protocol.write` in the Gremium can keep the minutes (O20), so the list offers only
 * them. The dialog creates the meeting and opens its page.
 *
 * The Gremium list holds every Gremium for an admin and the Gremien with
 * `session.manage` for everybody else. The server refuses every other Gremium.
 */
@Component({
  selector: 'app-create-meeting-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    PublicJoinSettingsComponent,
    FormsModule,
    TranslatePipe,
    DialogComponent,
    ButtonComponent,
    SelectComponent,
    DatepickerComponent,
    TimeInputComponent,
    InputComponent,
  ],
  templateUrl: './create-meeting-dialog.component.html',
  styleUrl: './create-meeting-dialog.component.scss',
})
export class CreateMeetingDialogComponent {
  private readonly api = inject(ApiClient);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly toast = inject(ToastService);
  private readonly router = inject(Router);
  private readonly options = inject(AdminOptionsService);

  readonly open = input(false);
  /** The Gremium to preselect, for example the active list filter. */
  readonly gremiumId = input('');
  /** The dialog closed, with or without a new meeting. */
  readonly closed = output<void>();

  readonly step = signal<1 | 2>(1);
  readonly creating = signal(false);
  readonly gremium = signal('');
  readonly date = signal('');
  readonly time = signal('');
  /** Optional end. It must be after the start. */
  readonly endTime = signal('');
  readonly title = signal('');
  /** Optional at create time. The meeting needs a minute-taker before it starts. */
  readonly keeper = signal('');
  /** Public participation over a QR code (#17), with the guest mode. */
  readonly publicJoin = signal(false);
  readonly guestsMode = signal<GuestsMode>('vote');
  /** What the chosen gremium allows: public participation only without a quorum. */
  readonly defaults = signal<MeetingDefaults | null>(null);
  readonly members = signal<MeetingMember[]>([]);
  readonly gremiumOptions = signal<SelectOption[]>([]);
  /** The Gremium list arrived. Before that an empty list is no "no Gremium" case. */
  readonly optionsLoaded = signal(false);
  /** The last prefilled title. A title that the user changed stays. */
  private lastPrefill = '';

  /** O20: only a member with `protocol.write` can keep the minutes (422 otherwise). */
  readonly keeperOptions = computed<SelectOption[]>(() => [
    { value: '', label: this.i18n.translate('meetings.protokollant.none') },
    ...this.members()
      .filter((m) => m.canKeepProtocol)
      .map((m) => ({
        value: m.principalId,
        label: m.displayName || m.email || this.i18n.translate('common.unnamed'),
      })),
  ]);

  readonly step1Valid = computed(
    () => !!this.gremium() && !!this.date().trim() && !!this.time().trim(),
  );
  readonly step2Valid = computed(() => this.step1Valid() && !!this.title().trim());

  constructor() {
    effect(() => {
      if (this.open()) untracked(() => this.reset());
    });
  }

  /** Start empty on every opening, with the preselected Gremium. */
  private reset(): void {
    this.step.set(1);
    this.creating.set(false);
    this.date.set('');
    this.time.set('');
    this.endTime.set('');
    this.title.set('');
    this.keeper.set('');
    this.publicJoin.set(false);
    this.guestsMode.set('vote');
    this.members.set([]);
    this.lastPrefill = '';
    this.gremium.set(this.gremiumId());
    if (this.optionsLoaded()) this.keepKnownGremium();
    else this.loadOptions();
    if (this.gremium()) this.loadMembers(this.gremium());
  }

  private loadOptions(): void {
    this.options.gremiumOptions().subscribe({
      next: (opts) => {
        const managed = new Set(this.auth.sessionManageGremien());
        this.gremiumOptions.set(
          this.auth.isAdmin() ? opts : opts.filter((o) => managed.has(o.value)),
        );
        this.optionsLoaded.set(true);
        this.keepKnownGremium();
      },
      error: () => {
        this.gremiumOptions.set([]);
        this.optionsLoaded.set(true);
        this.keepKnownGremium();
      },
    });
  }

  /** A preselected Gremium that the user cannot manage is no choice. */
  private keepKnownGremium(): void {
    const id = this.gremium();
    if (id && !this.gremiumOptions().some((o) => o.value === id)) {
      this.gremium.set('');
      this.members.set([]);
    }
  }

  onGremiumChange(id: string): void {
    this.gremium.set(id);
    this.keeper.set('');
    this.members.set([]);
    if (id) this.loadMembers(id);
  }

  private loadDefaults(gremiumId: string): void {
    this.defaults.set(null);
    this.api.meetingDefaults(gremiumId).subscribe({
      next: (d) => {
        if (this.gremium() !== gremiumId) return;
        this.defaults.set(d);
        if (!d.publicJoinAllowed) this.publicJoin.set(false);
      },
      error: () => {},
    });
  }

  private loadMembers(gremiumId: string): void {
    this.loadDefaults(gremiumId);
    this.api.listMeetingMembers(gremiumId).subscribe({
      next: (rows) => {
        // A late answer for a Gremium that the user changed since then is stale.
        if (this.gremium() === gremiumId) this.members.set(rows);
      },
      error: () => this.members.set([]),
    });
  }

  /** Step 1 → 2. Prefill the title, unless the user typed one. */
  next(): void {
    if (!this.step1Valid()) return;
    if (this.endTime().trim() && this.endTime().trim() <= this.time().trim()) {
      this.toast.error(this.i18n.translate('meetings.create.endBeforeStart'));
      return;
    }
    const committee = this.gremiumOptions().find((o) => o.value === this.gremium())?.label ?? '';
    const suggestion = this.i18n.translate('meetings.create.namePrefill', {
      committee,
      date: longDate(this.date().trim(), this.i18n.locale()),
    });
    if (!this.title().trim() || this.title() === this.lastPrefill) {
      this.title.set(suggestion);
      this.lastPrefill = suggestion;
    }
    this.step.set(2);
  }

  back(): void {
    this.step.set(1);
  }

  cancel(): void {
    this.closed.emit();
  }

  submit(): void {
    if (this.step() === 1) {
      this.next();
      return;
    }
    if (!this.step2Valid() || this.creating()) return;
    this.creating.set(true);
    this.api
      .createMeeting({
        title: this.title().trim(),
        gremiumId: this.gremium(),
        date: this.date().trim(),
        startTime: this.time().trim(),
        endTime: this.endTime().trim() || null,
        protokollantId: this.keeper() || null,
        // #17: only a public meeting sends the switch and its guest mode.
        ...(this.publicJoin() ? { publicJoin: true, guestsMode: this.guestsMode() } : {}),
      })
      .subscribe({
        next: (m) => {
          this.creating.set(false);
          this.toast.success(this.i18n.translate('meetings.toast.created'));
          this.closed.emit();
          // Open the new meeting, so the lead can prepare it right away.
          void this.router.navigate(['/meetings', m.id]);
        },
        error: (err: unknown) => {
          this.creating.set(false);
          const code = (err as { error?: { code?: string } } | null)?.error?.code;
          this.toast.error(
            this.i18n.translate(
              code === 'public_join_needs_no_quorum' ? 'guests.toast.needsNoQuorum' : 'meetings.toast.createFailed',
            ),
          );
        },
      });
  }
}
