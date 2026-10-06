import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { of } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import type { Meeting } from '@core/api/models';
import { MEDIA, ToastService } from '@stupa-makers/ui-kit';
import { LINK, guestRow } from '../../../../testing/guest-fixtures';
import {
  ATTENDANCE,
  DELEGATION_CONTEXT,
  matchMediaQueries,
  meeting,
} from '../../../../testing/meeting-fixtures';
import { AttendanceSheetComponent } from '../attendance-sheet/attendance-sheet.component';
import { MeetingGuestsService } from '../meeting-guests.service';

const GUESTS = [
  guestRow({ id: 'g-1', displayName: 'Emma Nguyen', requestedAt: '2026-10-05T16:50:00Z' }),
  guestRow({ id: 'g-2', displayName: 'Tobias Lang', requestedAt: new Date(Date.now() - 5_000).toISOString() }),
  guestRow({ id: 'g-3', displayName: 'Malte Krüger', status: 'admitted', admittedAt: '2026-10-06T16:16:00Z', decidedByName: 'Lea Hoffmann' }),
  guestRow({ id: 'g-4', displayName: null, number: 4, status: 'left', admittedAt: '2026-10-06T16:18:00Z' }),
  guestRow({ id: 'g-5', displayName: 'Ben Okafor', status: 'removed', admittedAt: '2026-10-06T16:20:00Z' }),
];

let restore: (() => void) | null = null;
afterEach(() => {
  restore?.();
  restore = null;
  document.body.style.overflow = '';
});

async function setup(over: Partial<Meeting> = {}, media: string[] = []) {
  localStorage.setItem('ap.locale', 'de');
  restore = matchMediaQueries(...media);
  const api = {
    listMeetingGuests: jest.fn(() => of(GUESTS)),
    getJoinLink: jest.fn(() => of(LINK)),
    decideMeetingGuest: jest.fn((_m: string, id: string, action: string) =>
      of({ ...GUESTS.find((g) => g.id === id)!, status: action === 'admit' ? 'admitted' : action === 'reject' ? 'rejected' : 'removed' }),
    ),
    renameMeetingGuest: jest.fn((_m: string, id: string, name: string) =>
      of({ ...GUESTS.find((g) => g.id === id)!, displayName: name }),
    ),
    admitAllMeetingGuests: jest.fn(() => of([])),
    rotateJoinCode: jest.fn(() => of(LINK)),
  };
  const m = meeting({ publicJoin: true, joinCode: '7KQ4MP', admittedGuests: 1, pendingGuests: 2, ...over });
  const showQr = jest.fn();
  const view = await render(AttendanceSheetComponent, {
    inputs: { open: true, meeting: m, attendance: ATTENDANCE, saving: false, viewers: [], conflictId: null },
    on: { showQr },
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      MeetingGuestsService,
      { provide: ApiClient, useValue: api },
      { provide: ToastService, useValue: { success: jest.fn(), error: jest.fn() } },
    ],
  });
  const guests = view.fixture.debugElement.injector.get(MeetingGuestsService);
  guests.sync(m);
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  http.match(() => true).forEach((r) => r.flush(r.request.url.includes('/delegations/meetings/') ? DELEGATION_CONTEXT : []));
  view.fixture.detectChanges();
  await view.fixture.whenStable();
  return { ...view, api, guests, showQr };
}

const sheet = () => screen.getByRole('dialog', { name: 'Anwesenheit' });

describe('guests in the attendance sheet (#17, variant A)', () => {
  it('sums up the room, shows the link and the open requests', async () => {
    const { showQr } = await setup();
    expect(sheet().querySelector('.as__total')?.textContent?.replace(/\s+/g, ' ').trim()).toBe(
      '2 anwesend: 1 Mitglieder + 1 Gäste',
    );
    expect(within(sheet()).getByText('Öffentliche Teilnahme an')).toBeInTheDocument();
    await userEvent.click(within(sheet()).getByRole('button', { name: /Groß zeigen/ }));
    expect(showQr).toHaveBeenCalled();
    expect(within(sheet()).getByText('Beitrittsanfragen · 2')).toBeInTheDocument();
    expect(within(sheet()).getByText(/^wartet seit \d\d:\d\d$/)).toBeInTheDocument();
    expect(within(sheet()).getByText('gerade eben')).toBeInTheDocument();
  });

  it('admits, rejects and admits all', async () => {
    const { api } = await setup();
    await userEvent.click(within(sheet()).getByRole('button', { name: 'Emma Nguyen zulassen' }));
    expect(api.decideMeetingGuest).toHaveBeenCalledWith('m-1', 'g-1', 'admit');
    await userEvent.click(within(sheet()).getByRole('button', { name: 'Tobias Lang ablehnen' }));
    expect(api.decideMeetingGuest).toHaveBeenCalledWith('m-1', 'g-2', 'reject');
    expect(within(sheet()).queryByText(/Beitrittsanfragen/)).toBeNull();
  });

  it('admits every request with one click', async () => {
    const { api } = await setup();
    await userEvent.click(within(sheet()).getByRole('button', { name: /Alle zulassen/ }));
    expect(api.admitAllMeetingGuests).toHaveBeenCalledWith('m-1');
  });

  it('rejects with an icon on a phone', async () => {
    const { api } = await setup({}, [MEDIA.phone]);
    await userEvent.click(within(sheet()).getByRole('button', { name: 'Emma Nguyen ablehnen' }));
    expect(api.decideMeetingGuest).toHaveBeenCalledWith('m-1', 'g-1', 'reject');
  });

  it('lists the guests in their own tab, renames and removes one', async () => {
    const { api } = await setup();
    await userEvent.click(within(sheet()).getByRole('radio', { name: /Gäste 1/ }));
    expect(within(sheet()).getByText('Malte Krüger')).toBeInTheDocument();
    expect(within(sheet()).getByText(/^zugelassen \d\d:\d\d · Lea Hoffmann$/)).toBeInTheDocument();
    expect(within(sheet()).getByText('Gast 4')).toBeInTheDocument();
    expect(within(sheet()).getByText('Hat verlassen')).toBeInTheDocument();
    expect(within(sheet()).getByText('Entfernt')).toBeInTheDocument();
    // The search filters the guests too.
    await userEvent.type(within(sheet()).getByRole('searchbox'), 'zzz');
    expect(within(sheet()).getByText('Kein Mitglied gefunden.')).toBeInTheDocument();
    await userEvent.clear(within(sheet()).getByRole('searchbox'));

    await userEvent.click(within(sheet()).getByRole('button', { name: 'Aktionen für Malte Krüger' }));
    await userEvent.click(screen.getByRole('menuitem', { name: 'Namen ändern' }));
    const input = screen.getByLabelText(/Dein Name/);
    await userEvent.clear(input);
    await userEvent.type(input, 'Malte K.{Enter}');
    expect(api.renameMeetingGuest).toHaveBeenCalledWith('m-1', 'g-3', 'Malte K.');

    await userEvent.click(within(sheet()).getByRole('button', { name: 'Aktionen für Malte K.' }));
    await userEvent.click(screen.getByRole('menuitem', { name: 'Gast entfernen' }));
    expect(screen.getByText(/kann danach nicht mehr abstimmen/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Gast entfernen' }));
    expect(api.decideMeetingGuest).toHaveBeenCalledWith('m-1', 'g-3', 'remove');
  });

  it('cancels the rename and the remove', async () => {
    const { api } = await setup();
    await userEvent.click(within(sheet()).getByRole('radio', { name: /Gäste 1/ }));
    await userEvent.click(within(sheet()).getByRole('button', { name: 'Aktionen für Malte Krüger' }));
    await userEvent.click(screen.getByRole('menuitem', { name: 'Namen ändern' }));
    await userEvent.click(screen.getAllByRole('button', { name: 'Abbrechen' }).at(-1)!);
    await userEvent.click(within(sheet()).getByRole('button', { name: 'Aktionen für Malte Krüger' }));
    await userEvent.click(screen.getByRole('menuitem', { name: 'Gast entfernen' }));
    await userEvent.click(screen.getAllByRole('button', { name: 'Abbrechen' }).at(-1)!);
    expect(api.renameMeetingGuest).not.toHaveBeenCalled();
    expect(api.decideMeetingGuest).not.toHaveBeenCalled();
  });

  it('marks watching guests and offers no menu on a closed meeting', async () => {
    await setup({ guestsMode: 'watch', status: 'live' });
    await userEvent.click(within(sheet()).getByRole('radio', { name: /Gäste \(zuschauend\) 1/ }));
    expect(within(sheet()).getByText('Schaut zu')).toBeInTheDocument();
  });

  it('shows only the count to a member (no names, no tabs)', async () => {
    localStorage.setItem('ap.locale', 'de');
    await render(AttendanceSheetComponent, {
      inputs: {
        open: true,
        meeting: meeting({ canManage: false, canControl: false, canWrite: false, publicJoin: true, admittedGuests: 7 }),
        attendance: ATTENDANCE,
        saving: false,
        viewers: [],
        conflictId: null,
      },
      providers: [provideHttpClient(), provideHttpClientTesting(), { provide: ToastService, useValue: {} }],
    });
    expect(sheet().querySelector('.as__total')?.textContent).toContain('7');
    expect(within(sheet()).queryByRole('radio', { name: /Gäste/ })).toBeNull();
  });

  it('guards the dialogs and names a pseudonymized guest', async () => {
    const view = await setup();
    const list = view.fixture.debugElement.query((d) => d.name === 'app-guest-list');
    expect(list).toBeNull();
    await userEvent.click(within(sheet()).getByRole('radio', { name: /Gäste 1/ }));
    const cmp = view.fixture.debugElement.query((d) => d.name === 'app-guest-list').componentInstance;
    cmp.saveRename();
    cmp.confirmRemove();
    cmp.onMenu({ g: GUESTS[2] }, 'other');
    cmp['renaming'].set(GUESTS[2]);
    cmp['renameDraft'].set('X');
    cmp.saveRename();
    expect(view.api.renameMeetingGuest).not.toHaveBeenCalled();
    // An admitted guest whose name is gone (pseudonymized) keeps only "Gast entfernen".
    view.guests.apply(guestRow({ id: 'g-6', displayName: null, number: 6, status: 'admitted', admittedAt: null, decidedAt: '2026-10-05T16:00:00Z' }));
    view.fixture.detectChanges();
    expect(within(sheet()).getByText('Gast 6')).toBeInTheDocument();
    await userEvent.click(within(sheet()).getByRole('button', { name: 'Aktionen für Gast 6' }));
    expect(screen.queryByRole('menuitem', { name: 'Namen ändern' })).toBeNull();
  });
});
