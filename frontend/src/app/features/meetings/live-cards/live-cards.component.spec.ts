import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { render, screen, within } from '@testing-library/angular';
import { USE_MOCK_API } from '@core/api/api.config';
import { LiveCardsComponent, ballotOf } from './live-cards.component';

function meeting(id: string, status: string, extra: Record<string, unknown> = {}): unknown {
  return {
    id,
    title: `Sitzung ${id}`,
    date: null,
    startTime: null,
    endTime: null,
    status,
    activeApplicationId: null,
    currentAgendaItemId: null,
    gremiumId: 'g1',
    gremiumName: 'Studierendenparlament',
    votes: [],
    protocolId: null,
    createdAt: '2026-06-01T10:00:00Z',
    ...extra,
  };
}

async function setup(items: unknown[] | 'error', off: readonly string[] = []) {
  localStorage.setItem('ap.features.off', JSON.stringify(off));
  const view = await render(LiveCardsComponent, {
    providers: [
      provideRouter([{ path: '**', children: [] }]),
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: USE_MOCK_API, useValue: false },
    ],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  if (!off.includes('meetings')) {
    const req = http.expectOne((r) => r.url.endsWith('/api/meetings/timeline'));
    if (items === 'error') req.flush('x', { status: 500, statusText: 'err' });
    else req.flush({ items, nextCursor: null });
  }
  view.detectChanges();
  return { ...view, http };
}

afterEach(() => localStorage.removeItem('ap.features.off'));

describe('LiveCardsComponent', () => {
  /** § F/collaboration/activity/001302: the live card of a running meeting. */
  it('shows the live meeting with progress, keeper, own vote state and "Live beitreten"', async () => {
    const started = new Date(2026, 8, 29, 18, 4).toISOString();
    await setup([
      meeting('m-live', 'live', {
        title: '34. Sitzung',
        date: '2026-09-29',
        startedAt: started,
        isProtokollant: true,
        currentAgendaItem: { position: 3, title: 'Zuschuss Party' },
        agendaItemCount: 8,
        canVote: true,
        votes: [{ id: 'v1', status: 'open', myBallot: { cast: true, choice: null } }],
      }),
      meeting('m-plan', 'planned'),
    ]);
    const live = screen.getByRole('region', { name: 'Laufende Sitzung' });
    expect(screen.getAllByRole('region')).toHaveLength(1);
    expect(within(live).getByText('seit 18:04 · Du führst Protokoll')).toBeInTheDocument();
    expect(within(live).getByText('3 / 8')).toBeInTheDocument();
    expect(within(live).getByText('Zuschuss Party')).toBeInTheDocument();
    expect(within(live).getByText('Du hast abgestimmt')).toBeInTheDocument();
    expect(within(live).getByRole('link', { name: /Live beitreten/ })).toHaveAttribute('href', '/meetings/m-live');
  });

  it('falls back to the planned start; says when the own vote is missing', async () => {
    const { fixture } = await setup([
      meeting('a', 'live', {
        startTime: '18:00:00',
        currentAgendaItem: { position: 2, title: null },
        agendaItemCount: 8,
        canVote: true,
        votes: [{ id: 'v1', status: 'open' }],
      }),
      meeting('b', 'live', {
        currentAgendaItem: { position: 1, title: null },
        agendaItemCount: 0,
        votes: [{ id: 'v2', status: 'open', myBallot: { cast: false, choice: null } }],
      }),
      meeting('c', 'live', { startedAt: 'kaputt', votes: [{ id: 'v3', status: 'closed' }] }),
    ]);
    const [a, b, c] = fixture.componentInstance.cards();
    expect(a.sub).toBe('seit 18:00');
    expect(a.now).toEqual({ position: 2, title: '', count: 8 });
    expect(a.vote).toEqual({ ballot: 'pending' });
    expect(screen.getByText('Deine Stimme fehlt')).toBeInTheDocument();
    expect(b.sub).toBe('');
    expect(b.now).toBeNull();
    expect(b.vote).toEqual({ ballot: null });
    expect(c.vote).toBeNull();
  });

  it('renders nothing without a live meeting', async () => {
    await setup([meeting('p', 'planned')]);
    expect(screen.queryByRole('region')).toBeNull();
  });

  it('renders nothing after an error', async () => {
    const { fixture } = await setup('error');
    expect(fixture.componentInstance.cards()).toEqual([]);
    expect(screen.queryByRole('region')).toBeNull();
  });

  it('asks for no meeting while Sitzungen is off', async () => {
    const { http, fixture } = await setup([], ['meetings']);
    http.expectNone((r) => r.url.endsWith('/api/meetings/timeline'));
    expect(fixture.componentInstance.cards()).toEqual([]);
  });

  it('knows the own state in an open vote', () => {
    expect(ballotOf(true, false)).toBe('cast');
    expect(ballotOf(false, true)).toBe('pending');
    expect(ballotOf(false, false)).toBeNull();
  });
});
