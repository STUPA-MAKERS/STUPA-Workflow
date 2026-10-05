import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Router } from '@angular/router';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { Delegation } from '@core/api/delegations.service';
import type { Meeting } from '@core/api/models';
import { AGENDA, ATTENDANCE, meeting, vote } from '../../../../testing/meeting-fixtures';
import { runAxe } from '../../../../testing/a11y';
import { MeetingDetailSheetComponent } from './meeting-detail-sheet.component';

const DELEGATION: Delegation = {
  id: 'd-1',
  meetingId: 'm-1',
  meetingTitle: null,
  meetingDate: null,
  gremiumId: 'g-1',
  gremiumName: null,
  delegatorId: 'pr-2',
  delegatorName: 'Jonas Weber',
  delegateId: 'pr-9',
  delegateName: 'Paul Neumann',
  delegateVoting: true,
  viaPool: false,
  createdAt: '2026-09-01T00:00:00Z',
  revocable: false,
  direction: null,
};

/** The live meeting of the board: item 2 of 3 runs, its vote is open. */
const LIVE = meeting({
  currentAgendaItemId: 't-2',
  currentAgendaItem: { position: 2, title: 'Bericht des Finanzreferats' },
  agendaItemCount: 3,
  startedAt: new Date(2026, 9, 15, 18, 4).toISOString(),
  votes: [vote({ agendaItemId: 't-2', majorityRule: 'simple', voted: 14, present: 19 })],
});

async function setup(over: { meeting?: Meeting; split?: boolean; phone?: boolean } = {}) {
  const on = { edit: jest.fn(), remove: jest.fn(), beamer: jest.fn() };
  const navigate = jest.fn(() => Promise.resolve(true));
  const view = await render(MeetingDetailSheetComponent, {
    inputs: { meeting: over.meeting ?? LIVE, split: over.split ?? true, phone: over.phone ?? false },
    on,
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: Router, useValue: { navigate } },
    ],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  return { ...view, http, on, navigate };
}

/** Answer the reads of the sheet. `null` lets a read fail. */
function flush(
  http: HttpTestingController,
  id = 'm-1',
  data: { agenda?: object | null; attendance?: object | null; delegations?: object | null; protocol?: object | null | false } = {},
): void {
  const answer = (url: string, body: object | null) => {
    const req = http.expectOne((r) => r.url === url);
    if (body === null) req.flush(null, { status: 500, statusText: 'e' });
    else req.flush(body);
  };
  answer(`/api/meetings/${id}/agenda`, data.agenda === undefined ? AGENDA : data.agenda);
  answer(`/api/meetings/${id}/attendance`, data.attendance === undefined ? ATTENDANCE : data.attendance);
  answer('/api/delegations', data.delegations === undefined ? [DELEGATION] : data.delegations);
  if (data.protocol !== false) {
    answer(
      `/api/meetings/${id}/protocol`,
      data.protocol === undefined
        ? { id: 'p-1', meetingId: id, markdown: '', status: 'draft' }
        : data.protocol,
    );
  }
}

// The tests click through whole views; a busy runner needs more than the default 5 s.
jest.setTimeout(15_000);

describe('MeetingDetailSheetComponent', () => {
  it('shows the head of a live meeting: Gremium, date, status, time and minute-taker', async () => {
    const { http, fixture } = await setup();
    expect(screen.getByRole('status')).toHaveTextContent('Sitzung wird geladen');
    flush(http);
    fixture.detectChanges();
    expect(screen.getByText('StuPa · Do., 15.10.2026')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 2, name: 'Konstituierende Sitzung' })).toBeInTheDocument();
    expect(screen.getByText('Live')).toHaveClass('st--accent');
    expect(screen.getByText('seit 18:04')).toBeInTheDocument();
    expect(screen.getByText('Protokoll: Pia Protokoll')).toBeInTheDocument();
    expect(fixture.nativeElement.querySelector('.ms')).toHaveClass('ms--split');
  });

  it('marks the done and the current agenda items and names the non-public one', async () => {
    const { http, fixture } = await setup();
    flush(http);
    fixture.detectChanges();
    const rows = within(screen.getAllByRole('list')[0]).getAllByRole('listitem');
    expect(rows).toHaveLength(3);
    expect(within(rows[0]).getByText('behandelt')).toBeInTheDocument();
    expect(rows[1]).toHaveAttribute('aria-current', 'step');
    expect(within(rows[1]).getByText('Jetzt')).toBeInTheDocument();
    expect(rows[2].querySelector('.ms__topSub')?.textContent?.replace(/\s+/g, ' ').trim()).toBe(
      'Antrag · nicht öffentlich',
    );
    expect(screen.getByText('3 TOPs')).toBeInTheDocument();
  });

  it('shows the progress, the turnout of the open vote, the counts, the delegations and the protocol', async () => {
    const { http, fixture } = await setup();
    flush(http);
    fixture.detectChanges();
    expect(screen.getByText('TOP 2 von 3')).toBeInTheDocument();
    expect(screen.getByText('67 %')).toBeInTheDocument();
    expect(screen.getByText('TOP 2 · Einfache Mehrheit')).toBeInTheDocument();
    expect(screen.getByText('14 / 19')).toBeInTheDocument();
    expect(screen.getAllByText('14 von 19 Anwesenden haben abgestimmt').length).toBeGreaterThan(0);
    expect(screen.getByText('1 von 3')).toBeInTheDocument();
    expect(screen.getByText(/Jonas Weber/)).toHaveTextContent('Jonas Weber wird vertreten von Paul Neumann');
    expect(screen.getByText('mit Stimmrecht')).toBeInTheDocument();
    expect(screen.getByText('Entwurf')).toBeInTheDocument();
    expect(await runAxe(fixture.nativeElement)).toHaveNoViolations();
  });

  it('opens the meeting page, the beamer and the edit; the menu deletes', async () => {
    const { http, fixture, on, navigate } = await setup();
    flush(http);
    fixture.detectChanges();
    await userEvent.click(screen.getByRole('button', { name: /Sitzung öffnen/ }));
    expect(navigate).toHaveBeenCalledWith(['/meetings', 'm-1']);
    await userEvent.click(screen.getByRole('button', { name: /Beamer-Ansicht/ }));
    expect(on.beamer).toHaveBeenCalledWith(LIVE);
    await userEvent.click(screen.getByRole('button', { name: 'Sitzung bearbeiten: Konstituierende Sitzung' }));
    expect(on.edit).toHaveBeenCalledWith(LIVE);
    await userEvent.click(screen.getByRole('button', { name: 'Weitere Aktionen: Konstituierende Sitzung' }));
    const menu = await screen.findByRole('menu');
    expect(within(menu).queryByRole('menuitem', { name: 'Sitzung bearbeiten' })).toBeNull();
    await userEvent.click(within(menu).getByRole('menuitem', { name: 'Sitzung löschen' }));
    expect(on.remove).toHaveBeenCalledWith(LIVE);
  });

  it('puts the edit and the beamer into the menu on a phone', async () => {
    const { http, fixture, on } = await setup({ phone: true, split: false });
    flush(http);
    fixture.detectChanges();
    expect(screen.queryByRole('button', { name: /Beamer-Ansicht/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /^Sitzung bearbeiten/ })).toBeNull();
    const open = async () => {
      await userEvent.click(screen.getByRole('button', { name: /Weitere Aktionen/ }));
      return screen.findByRole('menu');
    };
    await userEvent.click(within(await open()).getByRole('menuitem', { name: 'Sitzung bearbeiten' }));
    expect(on.edit).toHaveBeenCalled();
    await userEvent.click(within(await open()).getByRole('menuitem', { name: 'Beamer-Ansicht' }));
    expect(on.beamer).toHaveBeenCalled();
  });

  it('offers no beamer in the phone menu of a closed meeting', async () => {
    const { http, fixture } = await setup({ meeting: meeting({ status: 'closed' }), phone: true });
    flush(http);
    fixture.detectChanges();
    await userEvent.click(screen.getByRole('button', { name: /Weitere Aktionen/ }));
    const menu = await screen.findByRole('menu');
    expect(within(menu).getAllByRole('menuitem').map((i) => i.textContent?.trim())).toEqual([
      'Sitzung bearbeiten',
      'Sitzung löschen',
    ]);
  });

  it('warns about a planned meeting without a minute-taker and offers to name one', async () => {
    const planned = meeting({
      status: 'planned',
      protokollantId: null,
      protokollantName: null,
      protocolId: null,
      currentAgendaItemId: null,
      startTime: '18:00',
      endTime: '20:00',
    });
    const { http, fixture, on } = await setup({ meeting: planned });
    flush(http, 'm-1', { protocol: false, delegations: [], agenda: [] });
    fixture.detectChanges();
    expect(screen.getByText('Keine Protokollführung')).toHaveClass('ms__warn');
    expect(screen.getByText('18:00–20:00')).toBeInTheDocument();
    expect(screen.getByText('Noch keine TOPs.')).toBeInTheDocument();
    expect(screen.getByText('keine TOPs')).toBeInTheDocument();
    expect(screen.queryByText('Jetzt')).toBeNull();
    expect(screen.queryByText('Vertretungen')).toBeNull();
    expect(screen.queryByRole('heading', { name: 'Protokoll' })).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: /Protokollführung festlegen/ }));
    expect(on.edit).toHaveBeenCalledWith(planned);
  });

  it('shows a closed meeting with its final protocol and no beamer', async () => {
    const closed = meeting({
      status: 'closed',
      currentAgendaItemId: 't-2',
      startedAt: new Date(2026, 9, 15, 18, 4).toISOString(),
      closedAt: new Date(2026, 9, 15, 21, 40).toISOString(),
      keeperPeriods: [
        {
          principalId: 'pr-1',
          name: 'Mara Keller',
          fromAt: '2026-10-15T16:04:00Z',
          toAt: '2026-10-15T19:40:00Z',
          fromAgendaItemId: 't-1',
          toAgendaItemId: 't-3',
          fromPosition: 1,
          toPosition: 3,
        },
      ],
    });
    const { http, fixture } = await setup({ meeting: closed });
    flush(http, 'm-1', {
      protocol: { id: 'p-1', meetingId: 'm-1', markdown: '', status: 'final', pdfUrl: '/api/p.pdf' },
    });
    fixture.detectChanges();
    expect(screen.getByText('18:04–21:40')).toBeInTheDocument();
    expect(screen.getByText('Protokoll: Mara Keller')).toBeInTheDocument();
    // A closed meeting marks no item.
    expect(screen.queryByText('behandelt')).toBeNull();
    expect(screen.queryByRole('button', { name: /Beamer-Ansicht/ })).toBeNull();
    expect(screen.getByText('Final')).toBeInTheDocument();
    const pdf = screen.getByRole('link', { name: 'Öffnen' });
    expect(pdf).toHaveAttribute('href', '/api/p.pdf');
    expect(pdf).toHaveAttribute('target', '_blank');
  });

  it('names the state of a protocol that renders, and a closed meeting without one', async () => {
    const { http, fixture } = await setup({ meeting: meeting({ status: 'closed' }) });
    flush(http, 'm-1', { protocol: { id: 'p-1', meetingId: 'm-1', markdown: '', status: 'rendering' } });
    fixture.detectChanges();
    expect(screen.getByText('Wird gerendert …')).toBeInTheDocument();
    fixture.componentRef.setInput('meeting', meeting({ id: 'm-2', status: 'closed', protocolId: null, protokollantName: null }));
    fixture.detectChanges();
    flush(http, 'm-2', { protocol: false });
    fixture.detectChanges();
    expect(screen.getByText('Noch keines')).toBeInTheDocument();
    expect(screen.getByText('–')).toBeInTheDocument();
  });

  it('says which part failed and keeps the others', async () => {
    const { http, fixture } = await setup();
    flush(http, 'm-1', { agenda: null, attendance: null, delegations: null, protocol: null });
    fixture.detectChanges();
    expect(screen.getByText('Die Tagesordnung konnte nicht geladen werden.')).toBeInTheDocument();
    expect(screen.getByText('Die Anwesenheit konnte nicht geladen werden.')).toBeInTheDocument();
    expect(screen.queryByText('Vertretungen')).toBeNull();
    // The vote of an item that is not in the (failed) agenda shows its rule only.
    expect(screen.getByText('Einfache Mehrheit')).toBeInTheDocument();
  });

  it('reads again for another meeting only, and drops a late answer', async () => {
    const { http, fixture } = await setup();
    // The same meeting with a new status: no new read.
    fixture.componentRef.setInput('meeting', { ...LIVE, title: 'Neu' });
    fixture.detectChanges();
    const late = http.expectOne('/api/meetings/m-1/agenda');
    fixture.componentRef.setInput('meeting', meeting({ id: 'm-2', protocolId: null, votes: [vote({ majorityRule: undefined, agendaItemId: null })] }));
    fixture.detectChanges();
    late.flush(AGENDA);
    http.expectOne('/api/meetings/m-1/attendance').flush(ATTENDANCE);
    http.expectOne((r) => r.url === '/api/delegations' && r.params.get('meetingId') === 'm-1').flush([]);
    http.expectOne('/api/meetings/m-1/protocol').flush({ id: 'p-1', meetingId: 'm-1', markdown: '', status: 'draft' });
    fixture.detectChanges();
    expect(screen.getByRole('status')).toHaveTextContent('Sitzung wird geladen');
    http.expectOne('/api/meetings/m-2/agenda').flush([{ ...AGENDA[0], title: '  ' }]);
    http.expectOne('/api/meetings/m-2/attendance').flush([]);
    http.expectOne((r) => r.url === '/api/delegations' && r.params.get('meetingId') === 'm-2').flush([
      { ...DELEGATION, delegatorName: null, delegateName: null, delegateVoting: false },
    ]);
    fixture.detectChanges();
    expect(screen.getByText('0 von 0')).toBeInTheDocument();
    expect(screen.getByTitle('Unbenannter TOP')).toBeInTheDocument();
    expect(screen.getByText(/Unbekannt/)).toHaveTextContent('Unbekannt wird vertreten von Unbekannt');
    expect(screen.queryByText('mit Stimmrecht')).toBeNull();
    // The open vote has no item and no rule: the head shows the status only.
    expect(fixture.nativeElement.querySelector('.ms__voteMeta')).toBeNull();
  });

  it('offers no edit and no menu without the manage right', async () => {
    const { http, fixture } = await setup({ meeting: { ...LIVE, canManage: false } });
    flush(http);
    fixture.detectChanges();
    expect(screen.queryByRole('button', { name: /Weitere Aktionen/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /bearbeiten/ })).toBeNull();
    expect(screen.queryByRole('button', { name: /Beamer/ })).toBeNull();
  });

  it('leaves out an empty meta part and the time of a meeting without one', async () => {
    const bare = meeting({ status: 'planned', date: null, gremiumName: null, startTime: null, protocolId: null });
    const { http, fixture } = await setup({ meeting: bare });
    flush(http, 'm-1', { protocol: false });
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.ms__meta').textContent.trim()).toBe('');
    expect(fixture.nativeElement.querySelectorAll('.ms__part')).toHaveLength(2);
  });
});
