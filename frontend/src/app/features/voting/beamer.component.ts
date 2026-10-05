import {
  ChangeDetectionStrategy,
  Component,
  type OnDestroy,
  computed,
  effect,
  inject,
  signal,
  untracked,
} from '@angular/core';
import { ActivatedRoute, Router, RouterLink, type UrlTree } from '@angular/router';
import { ApiClient } from '@core/api/api-client.service';
import type { AgendaItem, Meeting, Vote, VoteResult } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { ThemeService } from '@core/theme/theme.service';
import { LiveVoteService, type LiveVoteSession } from '@core/ws/live-vote.service';
import type { VoteClosedMsg } from '@core/ws/ws-messages';
import { IconComponent } from '@stupa-makers/ui-kit';
import { type BeamerVote, MeetingBeamerComponent } from '../meetings/meeting-beamer.component';
import { BEAMER_FROM_PARAM, beamerOrigin } from './beamer-link.util';

/** The exit control hides when the pointer rests this long (ms). */
export const BEAMER_IDLE_MS = 2500;

/**
 * The beamer page (`/voting/beamer/:id`, route data `chrome: false`): the screen for the
 * projector of a meeting. It shows the agenda item that the room handles, the open vote
 * with its turnout, and the result after the close (`MeetingBeamerComponent`).
 *
 * The page follows the read-only beamer stream of the meeting. The stream carries the
 * state of the room and of the votes, never a name and never a ballot. The question and
 * the rules come from `GET /votes/{id}`, the meeting title and the agenda from the
 * meeting reads. A result stays on the screen while the room stays on its agenda item.
 *
 * The page is dark unless the person chose a theme (`ThemeService.setPageDefault`). The
 * page is never a trap: Escape leaves it, and a pointer movement shows an exit control
 * that hides again after `BEAMER_IDLE_MS` without movement, so the projector shows no
 * control while nobody touches the mouse. Leaving goes back to the page that opened the
 * beamer (`?from=`, see `beamerUrl`) and ends a fullscreen mode.
 */
@Component({
  selector: 'app-beamer',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, TranslatePipe, IconComponent, MeetingBeamerComponent],
  host: {
    '(document:keydown.escape)': 'exit()',
    '(document:pointermove)': 'wake()',
  },
  templateUrl: './beamer.component.html',
  styleUrl: './beamer.component.scss',
})
export class BeamerComponent implements OnDestroy {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);
  private readonly live = inject(LiveVoteService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly theme = inject(ThemeService);

  private readonly session: LiveVoteSession;
  /**
   * Where "leave" goes: the page that opened the beamer, else the meeting page, else
   * the voting overview without a meeting.
   */
  readonly backLink: UrlTree;
  /** The exit control shows: the pointer moved within the last `BEAMER_IDLE_MS`. */
  readonly controlsVisible = signal(false);
  private idleTimer: ReturnType<typeof setTimeout> | null = null;

  readonly meeting = signal<Meeting | null>(null);
  readonly agenda = signal<AgendaItem[]>([]);
  /** The vote on the screen as `GET /votes/{id}` gave it. */
  private readonly loaded = signal<Vote | null>(null);
  private requested: string | null = null;

  readonly logoSrc = computed(() => `assets/logos/stupa-wordmark-${this.theme.resolved()}.svg`);

  /** The agenda item that the room handles now: the stream first, then the meeting read. */
  private readonly currentItemId = computed(() => {
    const state = this.session.meeting();
    if (state && state.currentAgendaItemId !== undefined) return state.currentAgendaItemId;
    return this.meeting()?.currentAgendaItemId ?? null;
  });

  /**
   * The vote to show: the open vote of the stream, else the newest closed vote of the
   * current agenda item. A cancelled vote leaves the stream, and the screen goes idle.
   */
  private readonly targetId = computed<string | null>(() => {
    const opened = this.session.openVote();
    if (opened) return opened.voteId;
    const item = this.currentItemId();
    const votes = this.meeting()?.votes ?? [];
    const closed = votes.filter((v) => v.status === 'closed' && (!item || v.agendaItemId === item));
    return closed.length ? closed[closed.length - 1].id : null;
  });

  /** The vote with the newest frames of the stream. */
  readonly vote = computed<BeamerVote | null>(() => {
    const v = this.loaded();
    if (!v || v.id !== this.targetId()) return null;
    const closed = this.session.result();
    if (v.status === 'open') {
      return closed?.voteId === v.id ? this.closedByFrame(v, closed) : this.openView(v);
    }
    if (v.status !== 'closed') return null;
    // A result stays only while the room stays on the agenda item of the vote.
    const item = this.currentItemId();
    if (item && v.agendaItemId && v.agendaItemId !== item) return null;
    return this.view(v, {
      status: 'closed',
      counts: v.tally.counts,
      voted: v.tally.voted ?? sum(v.tally.counts),
    });
  });

  /** "TOP 3 · Zuschuss Erstsemester-Party": the item of the vote, else the current one. */
  readonly topLine = computed<string | null>(() => {
    const itemId = (this.vote() ? this.loaded()?.agendaItemId : null) ?? this.currentItemId();
    if (!itemId) return null;
    const ordered = [...this.agenda()].sort((a, b) => a.position - b.position);
    const index = ordered.findIndex((a) => a.id === itemId);
    if (index < 0) return null;
    const top = this.i18n.translate('meetings.agenda.top', { n: index + 1 });
    const title = ordered[index].title || this.i18n.translate('meetings.agenda.untitled');
    return `${top} · ${title}`;
  });

  constructor() {
    const routeId = this.route.snapshot.paramMap.get('id');
    const meetingId = routeId ?? 'demo';
    const fallback = routeId ? `/meetings/${routeId}` : '/voting';
    const from = beamerOrigin(this.route.snapshot.queryParamMap.get(BEAMER_FROM_PARAM));
    this.backLink = this.router.parseUrl(from ?? fallback);
    this.theme.setPageDefault('dark');
    this.session = this.live.open(meetingId, { beamer: true });
    if (routeId) this.loadMeeting(routeId);

    // A new state of the room (another item, a handover, a close) can change the agenda
    // and the votes of the meeting: read them again.
    let first = true;
    effect(() => {
      const state = this.session.meeting();
      untracked(() => {
        if (!state || !routeId) return;
        if (first) {
          first = false;
          return;
        }
        this.loadMeeting(routeId);
      });
    });
    effect(() => {
      const id = this.targetId();
      untracked(() => {
        if (id) this.load(id);
      });
    });
    // The close: read the vote again for the exact turnout and the quorum.
    effect(() => {
      const closed = this.session.result();
      untracked(() => {
        if (closed && closed.voteId === this.loaded()?.id) this.load(closed.voteId, true);
      });
    });
  }

  /** A pointer movement: show the exit control, and hide it again after a rest. */
  wake(): void {
    this.controlsVisible.set(true);
    if (this.idleTimer !== null) clearTimeout(this.idleTimer);
    this.idleTimer = setTimeout(() => {
      this.idleTimer = null;
      this.controlsVisible.set(false);
    }, BEAMER_IDLE_MS);
  }

  /** Escape: leave the beamer for the page that opened it. */
  exit(): void {
    this.leaveFullscreen();
    void this.router.navigateByUrl(this.backLink);
  }

  /** End a fullscreen mode of the page (the link navigates by itself). */
  leaveFullscreen(): void {
    if (document.fullscreenElement) void document.exitFullscreen().catch(() => {});
  }

  /** An open vote: the turnout of the stream, the counts only once the server shows them. */
  private openView(v: Vote): BeamerVote {
    const frame = this.session.tally();
    const live = frame?.voteId === v.id ? frame : null;
    const revealed = (live ? live.revealed : v.tally.revealed) !== false;
    const counts = live ? live.counts : v.tally.counts;
    return this.view(v, {
      status: 'open',
      counts: revealed && Object.keys(counts).length ? counts : null,
      voted: live?.cast ?? v.tally.voted ?? 0,
      present: live?.present ?? v.tally.present ?? 0,
      quorumMet: live?.quorumMet ?? v.tally.quorumMet,
    });
  }

  /** The close frame arrived before the vote was read again. */
  private closedByFrame(v: Vote, msg: VoteClosedMsg): BeamerVote {
    return this.view(v, {
      status: 'closed',
      counts: msg.counts,
      voted: sum(msg.counts),
      result: msg.result as VoteResult,
      failedReason: msg.failedReason ?? null,
    });
  }

  private view(v: Vote, over: Partial<BeamerVote> & Pick<BeamerVote, 'status' | 'voted'>): BeamerVote {
    return {
      question: v.question || this.i18n.translate('meetings.vote.untitled'),
      options: v.config.options,
      majorityRule: v.majorityRule ?? v.config.majorityRule,
      secret: v.secret || !!v.config.secret,
      quorum: v.quorum ?? v.config.quorum ?? null,
      quorumMet: v.tally.quorumMet,
      present: v.tally.present ?? 0,
      counts: null,
      result: v.result,
      failedReason: v.tally.failedReason ?? null,
      ...over,
    };
  }

  ngOnDestroy(): void {
    if (this.idleTimer !== null) clearTimeout(this.idleTimer);
    this.session.close();
    this.theme.setPageDefault(null);
  }

  private loadMeeting(id: string): void {
    this.api.getMeeting(id, { quiet: true }).subscribe({
      next: (m) => this.meeting.set(m),
      error: () => {},
    });
    this.api.listAgenda(id, { quiet: true }).subscribe({
      next: (rows) => this.agenda.set(rows),
      error: () => {},
    });
  }

  private load(id: string, force = false): void {
    if (!force && id === this.requested) return;
    this.requested = id;
    this.api.getVote(id, { quiet: true }).subscribe({
      // A read can arrive after the read of a newer vote (a vote closes and the room
      // opens the next one at once). Keep only the vote that the screen shows now.
      next: (v) => {
        if (v.id === this.targetId()) this.loaded.set(v);
      },
      error: () => {},
    });
  }
}

function sum(counts: Readonly<Record<string, number>>): number {
  return Object.values(counts).reduce((a, b) => a + b, 0);
}
