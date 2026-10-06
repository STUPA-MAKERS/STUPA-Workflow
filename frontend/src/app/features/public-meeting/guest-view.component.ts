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
import { ApiClient } from '@core/api/api-client.service';
import type { GuestAgendaItem, GuestMe, GuestVote } from '@core/api/models';
import { I18nService } from '@core/i18n/i18n.service';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { TranslationKey } from '@core/i18n/translations';
import { MarkdownViewComponent } from '@shared/markdown/markdown-view.component';
import { NoteComponent } from '@shared/ui/note/note.component';
import { StatusTextComponent } from '@shared/ui/status-text/status-text.component';
import { voteResultStatus } from '@shared/status-kind.util';
import { ButtonComponent, IconComponent, SegmentedComponent, type SegmentedOption } from '@stupa-makers/ui-kit';
import type { BallotCaster } from '../voting/ballot/ballot.component';
import { VotePanelComponent } from '../voting/vote-panel/vote-panel.component';
import { guestVoteToVote } from './guest-vote.util';

/** One agenda row of the guest view. */
interface AgendaRow {
  item: GuestAgendaItem;
  done: boolean;
  now: boolean;
  sub: string;
}

/**
 * The participant view of an admitted guest (#17, boards Telefon-Teilnahme): the own
 * status ("Du bist zugelassen" or "Du schaust zu"), the item that runs now, the open
 * vote (or "Keine offene Abstimmung"), and the tabs "Tagesordnung" and "Protokoll".
 *
 * A non-public item shows with its title and a lock, never with its text or its votes
 * (the server sends neither). The protocol tab shows the draft texts of the public items
 * as the minute-taker writes them. A vote opens on its own page in the view, with the
 * shared vote panel: the guest votes like a member (one ballot, no change, O11), or
 * reads it when the meeting lets guests only watch or the vote is for members only.
 */
@Component({
  selector: 'app-guest-view',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    TranslatePipe,
    ButtonComponent,
    IconComponent,
    MarkdownViewComponent,
    NoteComponent,
    SegmentedComponent,
    StatusTextComponent,
    VotePanelComponent,
  ],
  templateUrl: './guest-view.component.html',
  styleUrl: './guest-view.component.scss',
})
export class GuestViewComponent {
  private readonly api = inject(ApiClient);
  private readonly i18n = inject(I18nService);

  readonly me = input.required<GuestMe>();
  readonly code = input.required<string>();
  /** The guest was admitted while a vote ran (seen on this page). */
  readonly admittedDuringVote = input(false);
  /** A ballot went in, or the server refused it: read the view again. */
  readonly changed = output<void>();

  protected readonly tab = signal<'agenda' | 'protocol'>('agenda');
  /** The vote on its own page, or `null` for the overview. */
  protected readonly openVoteId = signal<string | null>(null);
  /** The votes that opened their page once by themselves. */
  private readonly autoOpened = new Set<string>();

  protected readonly view = computed(() => this.me().view);
  protected readonly watch = computed(() => this.me().meeting.guestsMode === 'watch');

  protected readonly tabs = computed<SegmentedOption[]>(() => [
    { value: 'agenda', label: this.i18n.translate('meetings.agenda.title') },
    { value: 'protocol', label: this.i18n.translate('guests.view.protocol') },
  ]);

  private readonly ordered = computed(() =>
    [...(this.view()?.agenda ?? [])].sort((a, b) => a.position - b.position),
  );
  private readonly currentPos = computed(() => {
    const id = this.view()?.currentAgendaItemId;
    return this.ordered().find((i) => i.id === id)?.position ?? 0;
  });
  protected readonly current = computed(
    () => this.ordered().find((i) => i.id === this.view()?.currentAgendaItemId) ?? null,
  );

  protected readonly rows = computed<AgendaRow[]>(() =>
    this.ordered().map((item) => {
      const now = item.position === this.currentPos();
      const parts = [this.i18n.translate('meetings.agenda.top', { n: item.position })];
      if (item.nonPublic) parts.push(this.i18n.translate('guests.view.membersOnly'));
      else if (item.kind === 'application') parts.push(this.i18n.translate('guests.view.application'));
      if (now) parts.push(this.i18n.translate('guests.view.nowShort'));
      return { item, done: item.position < this.currentPos(), now, sub: parts.join(' · ') };
    }),
  );

  /** "TOP 4 von 7 · Antrag". */
  protected readonly currentLine = computed(() => {
    const c = this.current();
    if (!c) return '';
    const parts = [
      this.i18n.translate('guests.view.topOf', { n: c.position, m: this.ordered().length }),
    ];
    if (c.kind === 'application' && !c.nonPublic) parts.push(this.i18n.translate('guests.view.application'));
    return parts.join(' · ');
  });

  /** The protocol excerpts: the public items with text, the newest first. */
  protected readonly excerpts = computed(() =>
    this.ordered()
      .filter((i) => !i.nonPublic && !!i.body?.trim())
      .reverse(),
  );

  /** The open vote, else the newest result of the current item. */
  protected readonly focusVote = computed<GuestVote | null>(() => {
    const votes = this.view()?.votes ?? [];
    const open = votes.find((v) => v.status === 'open');
    if (open) return open;
    const item = this.view()?.currentAgendaItemId;
    const closed = votes.filter((v) => v.status === 'closed' && v.agendaItemId === item);
    return closed.length ? closed[closed.length - 1] : null;
  });

  /** The vote of the vote page. */
  protected readonly pageVote = computed<GuestVote | null>(() => {
    const id = this.openVoteId();
    return (this.view()?.votes ?? []).find((v) => v.id === id) ?? null;
  });
  protected readonly panelVote = computed(() => {
    const v = this.pageVote();
    return v ? guestVoteToVote(v) : null;
  });
  /** The own ballot row: only where the guest may vote, or has voted. */
  protected readonly own = computed(() => {
    const v = this.pageVote();
    if (!v) return null;
    return v.canCast || v.myBallot.cast ? v.myBallot : null;
  });
  /** The note above a vote: watch mode, members only, secret, or admitted during the vote. */
  protected readonly voteNote = computed<{ key: TranslationKey; icon: 'eye' | 'info' | 'lock' } | null>(() => {
    const v = this.pageVote();
    if (!v || v.status !== 'open') return null;
    if (this.watch()) return { key: 'guests.vote.noteWatch', icon: 'eye' };
    if (!v.guestsVote) return { key: 'guests.vote.noteMembersOnly', icon: 'info' };
    if (this.admittedDuringVote() && !v.myBallot.cast) return { key: 'guests.vote.noteLate', icon: 'info' };
    if (v.secret) return { key: 'guests.vote.noteSecret', icon: 'lock' };
    return null;
  });
  /** "TOP 3 · 7. Sitzung der Fachschaft Informatik". */
  protected readonly voteWhere = computed(() => {
    const v = this.pageVote();
    const item = this.ordered().find((i) => i.id === v?.agendaItemId);
    const title = this.me().meeting.title;
    return item ? `${this.i18n.translate('meetings.agenda.top', { n: item.position })} · ${title}` : title;
  });

  /** The ballot goes to the public route with the device cookie. */
  protected readonly caster = computed<BallotCaster>(() => {
    const code = this.code();
    const id = this.openVoteId() ?? '';
    return (choice) => this.api.castGuestBallot(code, id, choice);
  });

  constructor() {
    // A vote that the guest can cast opens its page once by itself.
    effect(() => {
      const v = this.focusVote();
      untracked(() => {
        if (v && v.status === 'open' && v.canCast && !this.autoOpened.has(v.id)) {
          this.autoOpened.add(v.id);
          this.openVoteId.set(v.id);
        }
      });
    });
  }

  setTab(value: string | null): void {
    if (value === 'agenda' || value === 'protocol') this.tab.set(value);
  }

  protected resultOf(v: GuestVote) {
    return voteResultStatus(v.result === 'passed' ? 'passed' : 'rejected');
  }

  protected progressOf(v: GuestVote): string {
    return this.i18n.translate(v.guestsVote ? 'meetings.vote.progress' : 'guests.vote.progressMembers', {
      voted: v.tally.voted,
      present: v.tally.present,
    });
  }
}
