import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { catchError, map, of } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import type { Meeting } from '@core/api/models';
import { FeatureService } from '@core/features/feature.service';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { clock, shortTime } from '@shared/date-format';
import { DateBlockComponent, IconComponent, SegBarComponent, StatusTextComponent } from '@stupa-makers/ui-kit';

/** Meetings the timeline loads. The live ones come first, so a few are enough. */
const TIMELINE_LIMIT = 8;

/** A live meeting as a card. */
export interface LiveCard {
  readonly meeting: Meeting;
  /** "seit 18:04 · Du führst Protokoll". */
  readonly sub: string;
  readonly now: {
    readonly position: number;
    readonly title: string;
    readonly count: number;
  } | null;
  /** The open vote of the meeting and the own state in it, or null without one. */
  readonly vote: { readonly ballot: 'cast' | 'pending' | null } | null;
}

/**
 * The live meetings that the person can see, one card each (spec 001302): date block,
 * title, "Live", the time since the start, the current TOP, the open vote with the own
 * state, and "Live beitreten". Without a live meeting, and while `Sitzungen` is off, the
 * component renders nothing. The timeline of the meetings module scopes the meetings.
 */
@Component({
  selector: 'app-live-cards',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, TranslatePipe, DateBlockComponent, IconComponent, SegBarComponent, StatusTextComponent],
  templateUrl: './live-cards.component.html',
  styleUrl: './live-cards.component.scss',
})
export class LiveCardsComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly features = inject(FeatureService);

  private readonly meetings = toSignal(
    (this.features.isOn('meetings')
      ? this.api.listMeetingsTimeline({ direction: 'upcoming', limit: TIMELINE_LIMIT }).pipe(map((p) => p.items))
      : of([] as Meeting[])
    ).pipe(catchError(() => of([] as Meeting[]))),
    { initialValue: [] as Meeting[] },
  );

  readonly cards = computed<LiveCard[]>(() =>
    this.meetings()
      .filter((m) => m.status === 'live')
      .map((m) => this.card(m)),
  );

  private card(m: Meeting): LiveCard {
    const since = m.startedAt ? clock(m.startedAt, this.i18n.formatLocale()) : shortTime(m.startTime);
    const sub = [
      since ? this.i18n.translate('dashboard.sessions.since', { time: since }) : '',
      m.isProtokollant ? this.i18n.translate('dashboard.today.keeper') : '',
    ]
      .filter((s) => !!s)
      .join(' · ');
    const item = m.currentAgendaItem;
    const count = m.agendaItemCount;
    const open = m.votes.find((v) => v.status === 'open');
    return {
      meeting: m,
      sub,
      now: item && count ? { position: item.position, title: item.title ?? '', count } : null,
      vote: open ? { ballot: ballotOf(open.myBallot?.cast ?? false, m.canVote) } : null,
    };
  }
}

/** The own state in an open vote: cast, still to cast, or none without a vote right. */
export function ballotOf(cast: boolean, canCast: boolean): 'cast' | 'pending' | null {
  if (cast) return 'cast';
  return canCast ? 'pending' : null;
}
