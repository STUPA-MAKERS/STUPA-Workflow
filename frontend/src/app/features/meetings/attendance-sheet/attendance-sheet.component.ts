import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  model,
  output,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import type { Attendance, Meeting, Uuid } from '@core/api/models';
import { DelegationsApiService } from '@core/api/delegations.service';
import { I18nService } from '@core/i18n/i18n.service';
import type { LiveViewer } from '@core/ws/ws-messages';
import {
  type AttendanceChange,
  AttendanceSheetViewComponent,
  MEETING_API,
  type MeetingApi,
} from '@stupa-makers/ui-kit/views/meeting';
import {
  type DelegationCardChange,
  MeetingDelegationCardComponent,
} from '../meeting-delegation-card.component';
import { LeadSubstituteDialogComponent } from '../lead-substitute-dialog/lead-substitute-dialog.component';
import { meetingLine } from '../meetings-display.util';
import { MeetingGuestsService } from '../meeting-guests.service';
import { GuestListComponent } from '../guests/guest-list.component';
import { GuestRequestsComponent } from '../guests/guest-requests.component';
import { JoinLinkComponent } from '../public-join/join-link.component';

export type { AttendanceChange } from '@stupa-makers/ui-kit/views/meeting';

/** The meeting port of the kit views over the delegation routes of the app. */
function meetingApi(delegations: DelegationsApiService): MeetingApi {
  return {
    listDelegations: (meetingId) => delegations.list(meetingId),
    revokeDelegation: (id) => delegations.revoke(id),
  };
}

/**
 * The Anwesenheit sheet: the kit view `app-attendance-sheet-view` (S/framework/views/002275)
 * with the parts of the app. It gives the view the delegation routes, the guests of a public
 * meeting (join link, requests, list), the own delegation and the lead substitute dialog.
 */
@Component({
  selector: 'app-attendance-sheet',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  providers: [
    { provide: MEETING_API, useFactory: () => meetingApi(inject(DelegationsApiService)) },
  ],
  imports: [
    AttendanceSheetViewComponent,
    MeetingDelegationCardComponent,
    LeadSubstituteDialogComponent,
    GuestListComponent,
    GuestRequestsComponent,
    JoinLinkComponent,
  ],
  templateUrl: './attendance-sheet.component.html',
  styleUrl: './attendance-sheet.component.scss',
})
export class AttendanceSheetComponent {
  private readonly i18n = inject(I18nService);

  readonly open = model(false);
  /** The protocol of the meeting is final or in its render. */
  readonly protocolLocked = input(false);
  readonly meeting = input.required<Meeting>();
  readonly attendance = input.required<Attendance[]>();
  readonly saving = input(false);
  /** Names of the people who have the meeting open (WS presence). */
  readonly viewers = input<readonly LiveViewer[]>([]);
  /** The member whose "present" the server refused with 409 `delegation_active`. */
  readonly conflictId = input<Uuid | null>(null);

  readonly statusChange = output<AttendanceChange>();
  readonly statusReset = output<Attendance>();
  readonly conflictResolved = output<Uuid>();
  /** "Groß zeigen": the page shows the large QR code. */
  readonly showQr = output<void>();

  /** The join requests and the guests; the lead of a public meeting has them loaded. */
  protected readonly guests = inject(MeetingGuestsService, { optional: true });
  /** The admitted guests of the loaded list, or `null` when the lead has none loaded. */
  protected readonly guestCount = computed(() =>
    this.guests && this.guests.meetingId() === this.meeting().id
      ? this.guests.admittedCount()
      : null,
  );
  protected readonly meetingLine = computed(() =>
    meetingLine(this.meeting(), this.i18n.formatLocale()),
  );
  /** The missing member for whom the lead picks a substitute, or `null`. */
  protected readonly substituteFor = signal<Attendance | null>(null);

  private readonly view = viewChild.required(AttendanceSheetViewComponent);
  private readonly ownCard = viewChild(MeetingDelegationCardComponent);

  constructor() {
    effect(() => {
      if (!this.open()) untracked(() => this.substituteFor.set(null));
    });
  }

  /** The own delegation changed in the card: the rows load the delegations again. */
  protected onOwnChange(change: DelegationCardChange): void {
    this.view().delegationChanged({
      kind: change.kind,
      delegatorId: change.kind === 'revoked' ? change.delegation.delegatorId : '',
    });
  }

  /** The lead entered a substitute; the row shows "vertreten durch …". */
  protected onSubstituted(): void {
    this.substituteFor.set(null);
    this.view().substituted();
  }

  protected reloadOwn(): void {
    this.ownCard()?.reload();
  }
}
