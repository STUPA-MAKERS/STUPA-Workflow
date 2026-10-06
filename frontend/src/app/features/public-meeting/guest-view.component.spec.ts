import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { of } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import type { GuestMe } from '@core/api/models';
import { guestMe, guestVote } from '../../../testing/guest-fixtures';
import { GuestViewComponent } from './guest-view.component';
import { guestVoteToVote } from './guest-vote.util';

async function setup(me: GuestMe, admittedDuringVote = false) {
  localStorage.setItem('ap.locale', 'de');
  const api = { castGuestBallot: jest.fn(() => of({ status: 'cast' })) };
  const changed = jest.fn();
  const view = await render(GuestViewComponent, {
    inputs: { me, code: '7KQ4MP', admittedDuringVote },
    on: { changed },
    providers: [{ provide: ApiClient, useValue: api }],
  });
  return { ...view, api, changed };
}

const closedVote = guestVote({
  status: 'closed',
  canCast: false,
  result: 'passed',
  closedAt: '2026-10-06T16:58:00Z',
  tally: { counts: { yes: 17, no: 4, abstain: 3 }, voted: 24, present: 26, revealed: true, leading: 'yes', presentMembers: 19, presentGuests: 7 },
});

describe('GuestViewComponent', () => {
  it('opens a vote the guest can cast by itself, and casts through the public route', async () => {
    const { api, changed } = await setup(guestMe());
    expect(screen.getByText('Stimme abgeben', { exact: false })).toBeInTheDocument();
    expect(screen.getByText(/Einfache Mehrheit der abgegebenen Stimmen/)).toBeInTheDocument();
    expect(screen.getByText('TOP 3 · 7. Sitzung')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /^Ja/ }));
    await userEvent.click(screen.getByRole('button', { name: /Stimme abgeben: Ja/ }));
    expect(api.castGuestBallot).toHaveBeenCalledWith('7KQ4MP', 'v-1', 'yes');
    expect(changed).toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Zurück zur Sitzung' }));
    expect(screen.getByText('Du bist zugelassen')).toBeInTheDocument();
  });

  it('shows the agenda with a non-public item by its title, and the protocol of public items', async () => {
    await setup(guestMe({ view: { ...guestMe().view!, votes: [] } }));
    expect(screen.getByText('Keine offene Abstimmung')).toBeInTheDocument();
    expect(screen.getByText('Jetzt')).toBeInTheDocument();
    expect(screen.getByText('Personal')).toBeInTheDocument();
    expect(screen.getByText('Inhalt nur für Mitglieder')).toBeInTheDocument();
    // D5: an application item says "Antrag"; a free-text item has no subtitle.
    expect(screen.getByText('Antrag')).toBeInTheDocument();
    expect(screen.queryByText(/^TOP \d/)).toBeNull();
    expect(document.querySelector('.gv__item[aria-current="step"]')?.textContent).toContain('Antrag');
    expect(screen.getByText('Unbenannter TOP')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('radio', { name: /Protokoll/ }));
    expect(screen.getByText('Vorstellung')).toBeInTheDocument();
    expect(screen.getByText('Eröffnet.')).toBeInTheDocument();
    expect(screen.queryByText('Personal')).toBeNull();
  });

  it('says when no protocol text exists yet', async () => {
    const me = guestMe();
    await setup({ ...me, view: { ...me.view!, votes: [], agenda: me.view!.agenda.map((a) => ({ ...a, body: null })) } });
    await userEvent.click(screen.getByRole('radio', { name: /Protokoll/ }));
    expect(screen.getByText('Noch kein Protokolltext zu öffentlichen TOPs.')).toBeInTheDocument();
  });

  it('reads a members-only vote in watch mode without a ballot', async () => {
    const me = guestMe({ meeting: { ...guestMe().meeting, guestsMode: 'watch' } });
    await setup({ ...me, view: { ...me.view!, votes: [guestVote({ guestsVote: false, canCast: false, quorum: { type: 'percent', value: 50 }, tally: { counts: {}, voted: 11, present: 19, revealed: false, leading: null, presentMembers: 19, presentGuests: 7 } })] } });
    expect(screen.getByText('Du schaust zu')).toBeInTheDocument();
    expect(screen.getByText('Abstimmung läuft · nur Mitglieder')).toBeInTheDocument();
    expect(screen.getByText('11 von 19 Mitgliedern haben abgestimmt')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Abstimmung läuft/ }));
    expect(screen.getByText(/schauen Gäste nur zu/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Stimme abgeben/ })).toBeNull();
  });

  it('names a members-only vote in a voting meeting, and the running and cast states', async () => {
    const me = guestMe();
    const { fixture } = await setup({ ...me, view: { ...me.view!, votes: [guestVote({ guestsVote: false, canCast: false })] } });
    await userEvent.click(screen.getByRole('button', { name: /nur Mitglieder/ }));
    expect(screen.getByText(/stimmen nur die Mitglieder der Fachschaft Informatik ab/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Zurück zur Sitzung' }));
    fixture.componentRef.setInput('me', { ...me, view: { ...me.view!, votes: [guestVote({ canCast: false, myBallot: { cast: true, choice: 'yes' } })] } });
    fixture.detectChanges();
    expect(screen.getByText('Abstimmung offen · deine Stimme ist abgegeben')).toBeInTheDocument();
    fixture.componentRef.setInput('me', { ...me, view: { ...me.view!, votes: [guestVote({ canCast: false })] } });
    fixture.detectChanges();
    expect(screen.getByText('Abstimmung läuft')).toBeInTheDocument();
  });

  it('notes a guest admitted during the vote, and a secret vote', async () => {
    const { fixture } = await setup(guestMe(), true);
    expect(screen.getByText(/während der Abstimmung zugelassen/)).toBeInTheDocument();
    const me = guestMe();
    fixture.componentRef.setInput('admittedDuringVote', false);
    fixture.componentRef.setInput('me', { ...me, view: { ...me.view!, votes: [guestVote({ secret: true })] } });
    fixture.detectChanges();
    expect(screen.getByText(/Geheime Abstimmung: Deine Wahl/)).toBeInTheDocument();
  });

  it('shows the result of the current item without a quorum', async () => {
    const me = guestMe();
    await setup({ ...me, view: { ...me.view!, votes: [closedVote] } });
    expect(screen.getByText('Angenommen')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Ergebnis/ }));
    expect(
      screen.getByText('19 Mitglieder + 7 Gäste anwesend · Abgegeben 24 · Mehrheit der abgegebenen Stimmen'),
    ).toBeInTheDocument();
  });

  it('shows "Abgelehnt" for a rejected result and no "Jetzt" without a current item', async () => {
    const me = guestMe();
    await setup({
      ...me,
      view: { ...me.view!, currentAgendaItemId: null, votes: [{ ...closedVote, agendaItemId: null, result: 'tie' }] },
    });
    expect(screen.getByText('Abgelehnt')).toBeInTheDocument();
    expect(screen.queryByText('Jetzt')).toBeNull();
  });

  it('maps a guest vote to the vote of the panel', () => {
    const v = guestVoteToVote(guestVote());
    expect(v.meetingId).toBe('public');
    expect(v.config.guestsVote).toBe(true);
    expect(v.tally.eligible).toBe(26);
    expect(v.tally.presentGuests).toBe(7);
  });

  it('derives nothing without a view, and guards its inputs', async () => {
    const { fixture } = await setup(guestMe({ view: null }));
    const cmp = fixture.componentInstance;
    expect(cmp['rows']()).toEqual([]);
    expect(cmp['currentLine']()).toBe('');
    expect(cmp['focusVote']()).toBeNull();
    expect(cmp['panelVote']()).toBeNull();
    expect(cmp['own']()).toBeNull();
    expect(cmp['voteNote']()).toBeNull();
    expect(cmp['voteWhere']()).toBe('7. Sitzung');
    cmp['caster']()('yes');
    cmp.setTab('other');
    expect(cmp['tab']()).toBe('agenda');
  });

  it('names a non-public application item without "Antrag", and a vote without an item', async () => {
    const me = guestMe();
    const agenda = me.view!.agenda.map((a) => (a.id === 'a-3' ? { ...a, nonPublic: true, body: null } : a));
    const { fixture } = await setup({ ...me, view: { ...me.view!, agenda, votes: [guestVote({ agendaItemId: null, canCast: false })] } });
    const cmp = fixture.componentInstance;
    expect(cmp['currentLine']()).toBe('TOP 3 von 4');
    cmp['openVoteId'].set('v-1');
    fixture.detectChanges();
    expect(cmp['voteWhere']()).toBe('7. Sitzung');
    expect(cmp['voteNote']()).toBeNull();
    cmp['openVoteId'].set('unknown');
    fixture.detectChanges();
    expect(cmp['pageVote']()).toBeNull();
  });
});
