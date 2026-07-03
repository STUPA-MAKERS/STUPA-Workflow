import { ChangeDetectionStrategy, Component, inject, input, output } from '@angular/core';
import { RouterLink } from '@angular/router';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type {
  AgendaItem,
  Attendance,
  AttendanceStatus,
  I18nMap,
  Meeting,
  MeetingVote,
  Uuid,
} from '@core/api/models';
import {
  BadgeComponent,
  ButtonComponent,
  CardComponent,
  IconComponent,
} from '@stupa-makers/ui-kit';
import { MeetingAttendanceTableComponent } from './meeting-attendance-table.component';
import { MeetingDelegationCardComponent } from './meeting-delegation-card.component';
import { renderMarkdown } from './meetings.util';
import {
  countEntries,
  resolveI18n,
  voteOptionLabel,
  voteOptionsFor,
  voteResultKey,
  voteResultVariant,
  voteStatusKey,
  voteStatusVariant,
} from './meetings-display.util';

/** Member live-follow view: read the protocol, cast on open votes. */
@Component({
  selector: 'app-meeting-follow-view',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    TranslatePipe,
    RouterLink,
    BadgeComponent,
    ButtonComponent,
    CardComponent,
    IconComponent,
    MeetingAttendanceTableComponent,
    MeetingDelegationCardComponent,
  ],
  templateUrl: './meeting-follow-view.component.html',
  styleUrl: './meeting-follow-view.component.scss',
})
export class MeetingFollowViewComponent {
  private readonly i18n = inject(I18nService);

  readonly meeting = input.required<Meeting>();
  readonly agenda = input.required<AgendaItem[]>();
  readonly attendance = input.required<Attendance[]>();
  readonly savingAttendance = input.required<boolean>();
  readonly casting = input.required<Uuid | null>();
  /** Own choice per vote id (highlights the picked option). */
  readonly choices = input.required<Record<string, string>>();

  readonly castVote = output<{ voteId: Uuid; choice: string }>();
  readonly attendanceChange = output<{ member: Attendance; status: AttendanceStatus }>();

  protected readonly voteVariant = voteStatusVariant;
  protected readonly voteStatusKey = voteStatusKey;
  protected readonly voteResultKey = voteResultKey;
  protected readonly voteResultVariant = voteResultVariant;
  protected readonly countEntries = countEntries;
  protected readonly voteOptionsFor = voteOptionsFor;
  protected readonly renderBody = renderMarkdown;

  protected votesForTop(topId: Uuid): MeetingVote[] {
    return this.meeting().votes.filter((v) => v.agendaItemId === topId);
  }

  protected myChoice(voteId: Uuid): string | null {
    return this.choices()[voteId] ?? null;
  }

  protected stateLabelOf(map: I18nMap | null | undefined): string {
    return resolveI18n(map, this.i18n.locale());
  }

  protected optionLabel(opt: string): string {
    return voteOptionLabel(opt, (key) => this.i18n.translate(key));
  }
}
