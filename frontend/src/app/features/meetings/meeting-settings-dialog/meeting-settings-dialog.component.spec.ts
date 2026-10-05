import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { Attendance, Meeting } from '@core/api/models';
import { ToastService } from '@stupa-makers/ui-kit';
import { runAxe } from '../../../../testing/a11y';
import { MeetingSettingsDialogComponent } from './meeting-settings-dialog.component';

const MEETING = {
  id: 'm-1',
  title: '35. Sitzung',
  status: 'planned',
  date: '2026-10-13',
  startTime: '18:00',
  endTime: null,
  protokollantId: 'p-2',
} as unknown as Meeting;

const ROSTER: Attendance[] = [
  { principalId: 'p-1', displayName: 'Mara Keller', email: null, status: null, source: null, note: null, isSelf: false, canKeepProtocol: true },
  // The current minute-taker stays in the list, also without protocol.write.
  { principalId: 'p-2', displayName: 'Tom Brandt', email: null, status: null, source: null, note: null, isSelf: false, canKeepProtocol: false },
  { principalId: 'p-3', displayName: null, email: 'lea@x.de', status: null, source: null, note: null, isSelf: false, canKeepProtocol: true },
  { principalId: 'p-4', displayName: null, email: null, status: null, source: null, note: null, isSelf: false, canKeepProtocol: true },
  { principalId: 'p-5', displayName: 'Ohne Recht', email: null, status: null, source: null, note: null, isSelf: false, canKeepProtocol: false },
] as Attendance[];

async function setup(meeting: Meeting | null = MEETING, protocolFinal = false) {
  const closed = jest.fn();
  const saved = jest.fn();
  const view = await render(MeetingSettingsDialogComponent, {
    inputs: { meeting, protocolFinal },
    on: { closed, saved },
    providers: [provideHttpClient(), provideHttpClientTesting()],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  const toasts = () =>
    view.fixture.debugElement.injector
      .get(ToastService)
      .toasts()
      .map((t) => t.message);
  return { ...view, http, cmp: view.fixture.componentInstance, closed, saved, toasts };
}

function flushRoster(http: HttpTestingController, fixture: { detectChanges(): void }): void {
  http.expectOne('/api/meetings/m-1/attendance').flush(ROSTER);
  fixture.detectChanges();
}

describe('MeetingSettingsDialogComponent', () => {
  it('stays closed without a meeting', async () => {
    const { http } = await setup(null);
    expect(screen.queryByRole('dialog')).toBeNull();
    http.verify();
  });

  it('names the meeting and offers the members who can keep the minutes plus the current one (O20)', async () => {
    const { http, fixture } = await setup();
    flushRoster(http, fixture);
    const dialog = screen.getByRole('dialog', { name: 'Sitzung bearbeiten' });
    expect(dialog).toHaveAccessibleDescription('35. Sitzung');
    const keeper = within(dialog).getByLabelText('Protokollführung') as HTMLSelectElement;
    expect(within(keeper).getAllByRole('option').map((o) => o.textContent?.trim())).toEqual([
      '— niemand —',
      'Mara Keller',
      'Tom Brandt',
      'lea@x.de',
      'Ohne Namen',
    ]);
    expect(keeper.value).toBe('p-2');
  });

  it('saves the minute-taker, the date and the times in one PATCH', async () => {
    const { http, fixture, cmp, saved, toasts } = await setup();
    flushRoster(http, fixture);
    await userEvent.selectOptions(screen.getByLabelText('Protokollführung'), 'p-1');
    cmp.endTime.set('20:00');
    fixture.detectChanges();
    await userEvent.click(screen.getByRole('button', { name: 'Speichern' }));
    const req = http.expectOne('/api/meetings/m-1');
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body).toEqual({
      protokollantId: 'p-1',
      date: '2026-10-13',
      startTime: '18:00',
      endTime: '20:00',
    });
    req.flush({ ...MEETING, id: 'm-1', title: '35. Sitzung', status: 'planned', votes: [], createdAt: 'x' });
    expect(saved).toHaveBeenCalledWith(expect.objectContaining({ id: 'm-1' }));
    expect(toasts()).toContain('Einstellungen gespeichert.');
  });

  it('sends nobody as null and no end as null', async () => {
    const { http, fixture, cmp } = await setup({ ...MEETING, protokollantId: null, endTime: null } as Meeting);
    flushRoster(http, fixture);
    cmp.save();
    const req = http.expectOne('/api/meetings/m-1');
    expect(req.request.body.protokollantId).toBeNull();
    expect(req.request.body.endTime).toBeNull();
  });

  it('locks every field of a closed meeting and saves nothing', async () => {
    const { http, fixture, cmp } = await setup({ ...MEETING, status: 'closed' } as Meeting);
    flushRoster(http, fixture);
    expect(screen.getByText(/Sitzung ist geschlossen/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Speichern' })).toBeDisabled();
    cmp.save();
    http.verify();
  });

  it('leaves the minute-taker out once the protocol is final', async () => {
    const { http, fixture, cmp } = await setup(MEETING, true);
    flushRoster(http, fixture);
    expect(screen.getByText(/Protokoll ist finalisiert/)).toBeInTheDocument();
    expect(screen.getByLabelText('Protokollführung')).toBeDisabled();
    cmp.save();
    const req = http.expectOne('/api/meetings/m-1');
    expect(req.request.body).toEqual({ date: '2026-10-13', startTime: '18:00', endTime: null });
  });

  it('needs a date and a start, and an end after the start', async () => {
    const { http, fixture, cmp, toasts } = await setup({ ...MEETING, date: null, startTime: null } as Meeting);
    flushRoster(http, fixture);
    expect(cmp.date()).toBe('');
    cmp.save();
    expect(toasts()).toContain('Datum und Uhrzeit sind erforderlich.');
    cmp.date.set('2026-10-13');
    cmp.time.set('18:00');
    cmp.endTime.set('17:00');
    cmp.save();
    expect(toasts()).toContain('Die End-Uhrzeit muss nach der Start-Uhrzeit liegen.');
    http.verify();
  });

  it('explains a minute-taker without the protocol right (O20) and another refusal', async () => {
    const { http, fixture, cmp, saved, toasts } = await setup();
    flushRoster(http, fixture);
    cmp.save();
    cmp.save(); // a second save while the first runs is ignored
    http
      .expectOne('/api/meetings/m-1')
      .flush({ code: 'protokollant_needs_protocol_write' }, { status: 422, statusText: 'x' });
    expect(toasts()).toContain('Diese Person hat im Gremium kein Protokollrecht.');
    cmp.save();
    http.expectOne('/api/meetings/m-1').flush({ detail: 'zu spät' }, { status: 409, statusText: 'x' });
    expect(toasts()).toContain('Aktion fehlgeschlagen.: zu spät');
    cmp.save();
    http.expectOne('/api/meetings/m-1').flush(null, { status: 500, statusText: 'x' });
    expect(toasts()).toContain('Aktion fehlgeschlagen.');
    expect(saved).not.toHaveBeenCalled();
    expect(cmp.saving()).toBe(false);
  });

  it('keeps an empty list when the roster fails, and closes on cancel', async () => {
    const { http, fixture, cmp, closed } = await setup();
    http.expectOne('/api/meetings/m-1/attendance').flush(null, { status: 500, statusText: 'e' });
    fixture.detectChanges();
    expect(cmp.roster()).toEqual([]);
    const [, footerCancel] = screen.getAllByRole('button', { name: 'Abbrechen' });
    await userEvent.click(footerCancel);
    expect(closed).toHaveBeenCalled();
  });

  it('has no axe violations', async () => {
    const { http, fixture } = await setup();
    flushRoster(http, fixture);
    expect(await runAxe(document.body)).toHaveNoViolations();
  });

  it('does nothing on save without a meeting', async () => {
    const { http, cmp } = await setup(null);
    cmp.save();
    http.verify();
  });
});
