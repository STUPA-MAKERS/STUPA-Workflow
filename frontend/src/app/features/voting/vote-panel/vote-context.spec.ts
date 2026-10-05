import { firstValueFrom, of, throwError } from 'rxjs';
import type { ApiClient } from '@core/api/api-client.service';
import { NO_CONTEXT, loadVoteContext } from './vote-context';

function api(opts: { meetingError?: boolean; agendaError?: boolean } = {}) {
  return {
    getMeeting: jest.fn(() =>
      opts.meetingError ? throwError(() => ({ status: 403 })) : of({ id: 'm1', title: 'Sitzung' }),
    ),
    listAgenda: jest.fn(() =>
      opts.agendaError
        ? throwError(() => ({ status: 403 }))
        : of([
            { id: 'c', position: 2 },
            { id: 'a', position: 0 },
            { id: 'b', position: 1 },
          ]),
    ),
  } as unknown as ApiClient & { getMeeting: jest.Mock; listAgenda: jest.Mock };
}

describe('loadVoteContext', () => {
  it('gives no context for a vote without a meeting', async () => {
    const a = api();
    expect(await firstValueFrom(loadVoteContext(a, null, null))).toBe(NO_CONTEXT);
    expect(a.getMeeting).not.toHaveBeenCalled();
  });

  it('numbers the item in the agenda order', async () => {
    const ctx = await firstValueFrom(loadVoteContext(api(), 'm1', 'c'));
    expect(ctx.meeting?.title).toBe('Sitzung');
    expect(ctx.position).toBe(3);
  });

  it('reads no agenda without an item and keeps the number unknown', async () => {
    const a = api();
    const ctx = await firstValueFrom(loadVoteContext(a, 'm1', null));
    expect(a.listAgenda).not.toHaveBeenCalled();
    expect(ctx.position).toBeNull();
  });

  it('keeps going when the meeting or the agenda is not readable', async () => {
    const ctx = await firstValueFrom(
      loadVoteContext(api({ meetingError: true, agendaError: true }), 'm1', 'c'),
    );
    expect(ctx).toEqual({ meeting: null, position: null });
  });
});
