import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { Attendance, Meeting } from '@core/api/models';
import { ToastService } from '@stupa-makers/ui-kit';
import { runAxe } from '../../../../testing/a11y';
import { MeetingSettingsDialogComponent } from './meeting-settings-dialog.component';
import { optionLabels, pickOption } from '../../../../testing/select';

const MEETING = {
  id: 'm-1',
  title: '35. Sitzung',
  gremiumName: 'Studierendenparlament',
  status: 'planned',
  date: '2026-10-13',
  startTime: '18:00',
  endTime: null,
  protokollantId: 'p-2',
} as unknown as Meeting;

/** The current minute-taker stays in the list, also without protocol.write. */
const ROSTER: Attendance[] = [
  { principalId: 'p-1', displayName: 'Mara Keller', email: null, status: null, source: null, note: null, isSelf: false, canKeepProtocol: true },
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

  it('names the gremium and offers the members who can keep the minutes plus the current one', async () => {
    const { http, fixture } = await setup();
    flushRoster(http, fixture);
    const dialog = screen.getByRole('dialog', { name: 'Sitzung bearbeiten' });
    expect(dialog).toHaveAccessibleDescription('Studierendenparlament');
    expect(within(dialog).getByLabelText(/Titel/)).toHaveValue('35. Sitzung');
    const keeper = within(dialog).getByLabelText('Protokollführung');
    expect(keeper).toHaveTextContent('Tom Brandt');
    expect(await optionLabels(keeper)).toEqual([
      '— niemand —',
      'Mara Keller',
      'Tom Brandt',
      'lea@x.de',
      'Ohne Namen',
    ]);
  });

  it('saves the minute-taker, the date and the times in one PATCH', async () => {
    const { http, fixture, cmp, saved, toasts } = await setup();
    flushRoster(http, fixture);
    await pickOption(screen.getByLabelText('Protokollführung'), 'Mara Keller');
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

  /** § 000918 */
  describe('late invitation', () => {
    const inDays = (n: number): string => {
      const d = new Date();
      d.setDate(d.getDate() + n);
      return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    };
    const PLANNED = { ...MEETING, gremiumId: 'g-1', kind: 'ordinary', date: inDays(2) } as Meeting;
    const PERIODS = { guestsVoteAllowed: false, quorumPercent: null, inviteDaysOrdinary: 7, inviteDaysExtraordinary: 3 };

    it('warns only for a new date that misses the period, and saves', async () => {
      localStorage.setItem('ap.locale', 'de');
      const { http, fixture, cmp } = await setup(PLANNED);
      http.expectOne('/api/committees/g-1/meeting-defaults').flush(PERIODS);
      flushRoster(http, fixture);
      expect(screen.queryByText(/Ladungsfrist/)).toBeNull();
      cmp.date.set(inDays(4));
      fixture.detectChanges();
      expect(screen.getByText('Die Ladungsfrist von 7 Tagen ist nicht mehr einzuhalten.')).toBeInTheDocument();
      cmp.date.set(inDays(9));
      fixture.detectChanges();
      expect(screen.queryByText(/Ladungsfrist/)).toBeNull();
      cmp.date.set(inDays(4));
      cmp.save();
      expect(http.expectOne('/api/meetings/m-1').request.body.date).toBe(inDays(4));
    });

    it('stays silent when the periods do not load, for a late answer and after the start', async () => {
      const { http, fixture, cmp } = await setup(PLANNED);
      const first = http.expectOne('/api/committees/g-1/meeting-defaults');
      flushRoster(http, fixture);
      fixture.componentRef.setInput('meeting', { ...PLANNED, id: 'm-2' } as Meeting);
      fixture.detectChanges();
      first.flush(PERIODS);
      expect(cmp.defaults()).toBeNull();
      http.expectOne('/api/committees/g-1/meeting-defaults').error(new ProgressEvent('x'));
      cmp.date.set(inDays(4));
      expect(cmp.lateInvite()).toBeNull();
      fixture.componentRef.setInput('meeting', { ...PLANNED, id: 'm-3', status: 'live' } as Meeting);
      fixture.detectChanges();
      http.expectNone('/api/committees/g-1/meeting-defaults');
      cmp.date.set(inDays(4));
      expect(cmp.lateInvite()).toBeNull();
    });
  });

  it('locks every field of a closed meeting and saves nothing', async () => {
    const { http, fixture, cmp } = await setup({ ...MEETING, status: 'closed' } as Meeting);
    flushRoster(http, fixture);
    expect(screen.getByText(/Sitzung ist geschlossen/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Speichern' })).toBeDisabled();
    expect(screen.getByLabelText(/Titel/)).toBeDisabled();
    cmp.save();
    http.verify();
  });

  it('saves a new title, without the outer blanks', async () => {
    const { http, fixture } = await setup();
    flushRoster(http, fixture);
    const field = screen.getByLabelText(/Titel/);
    await userEvent.clear(field);
    await userEvent.type(field, '  Vollversammlung ');
    await userEvent.click(screen.getByRole('button', { name: 'Speichern' }));
    const req = http.expectOne('/api/meetings/m-1');
    expect(req.request.body).toEqual({
      title: 'Vollversammlung',
      protokollantId: 'p-2',
      date: '2026-10-13',
      startTime: '18:00',
      endTime: null,
    });
  });

  it('needs a title and refuses one that is too long', async () => {
    const { http, fixture, cmp, toasts } = await setup();
    flushRoster(http, fixture);
    cmp.title.set('   ');
    fixture.detectChanges();
    expect(screen.getByRole('button', { name: 'Speichern' })).toBeDisabled();
    cmp.save();
    expect(toasts()).toContain('Der Titel ist erforderlich.');
    cmp.title.set('x'.repeat(201));
    fixture.detectChanges();
    expect(screen.getByText('Der Titel darf höchstens 200 Zeichen haben.')).toBeInTheDocument();
    cmp.save();
    expect(toasts()).toContain('Der Titel darf höchstens 200 Zeichen haben.');
    cmp.title.set('x'.repeat(200));
    fixture.detectChanges();
    expect(screen.queryByText('Der Titel darf höchstens 200 Zeichen haben.')).toBeNull();
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

  /** A second save while the first runs is ignored. */
  it('explains a minute-taker without the protocol right and another refusal', async () => {
    const { http, fixture, cmp, saved, toasts } = await setup();
    flushRoster(http, fixture);
    cmp.save();
    cmp.save();
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
    expect(screen.getByRole('button', { name: 'Schließen' })).toBeInTheDocument();
    const footerCancel = screen.getByRole('button', { name: 'Abbrechen' });
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

  describe('kind, place and form', () => {
    const FULL = { ...MEETING, kind: 'ordinary', location: 'Raum 9-108', form: 'presence' } as unknown as Meeting;

    /** §F/meetings/meetings/000903, §F/meetings/meetings/000907 */
    it('sends only what changed', async () => {
      const { http, fixture, cmp } = await setup(FULL);
      flushRoster(http, fixture);
      expect(await optionLabels(screen.getByLabelText('Sitzungsart'))).toContain('Wiederholungssitzung');
      cmp.save();
      const same = http.expectOne('/api/meetings/m-1');
      expect(same.request.body).not.toHaveProperty('kind');
      expect(same.request.body).not.toHaveProperty('location');
      expect(same.request.body).not.toHaveProperty('form');
      same.flush(FULL);
      cmp.kind.set('extraordinary');
      cmp.location.set('  ');
      cmp.form.set('video');
      cmp.save();
      const req = http.expectOne('/api/meetings/m-1');
      expect(req.request.body).toEqual(
        expect.objectContaining({ kind: 'extraordinary', location: null, form: 'video' }),
      );
      expect(req.request.body).not.toHaveProperty('repeatOfId');
    });

    /** §F/meetings/meetings/000940 */
    it('asks a planned repeat meeting for its first meeting and sends a new one', async () => {
      const planned = { ...FULL, gremiumId: 'g-1', date: '2026-11-10' } as unknown as Meeting;
      const { http, fixture, cmp, toasts } = await setup(planned);
      flushRoster(http, fixture);
      http.expectOne('/api/committees/g-1/meeting-defaults').error(new ProgressEvent('x'));
      http.expectOne('/api/meetings?gremiumId=g-1').flush([
        { id: 'm-1', title: '35. Sitzung', date: '2026-11-10', status: 'planned', votes: [], createdAt: 'x' },
        { id: 'm-0', title: '34. Sitzung', date: '2026-11-03', status: 'closed', votes: [], createdAt: 'x' },
      ]);
      fixture.detectChanges();
      expect(screen.queryByLabelText(/Erste Sitzung/)).toBeNull();
      cmp.kind.set('repeat');
      fixture.detectChanges();
      expect(await optionLabels(screen.getByLabelText(/Erste Sitzung/))).toEqual(['34. Sitzung · 03.11.2026']);
      cmp.save();
      expect(toasts()).toContain('Eine Wiederholungssitzung braucht ihre erste Sitzung.');
      http.expectNone('/api/meetings/m-1');
      cmp.repeatOf.set('m-0');
      cmp.save();
      const req = http.expectOne('/api/meetings/m-1');
      expect(req.request.body).toEqual(expect.objectContaining({ kind: 'repeat', repeatOfId: 'm-0' }));
      req.flush(
        { type: 'about:blank', status: 422, code: 'repeat_needs_first_meeting' },
        { status: 422, statusText: 'Unprocessable' },
      );
      expect(toasts()).toContain('Die erste Sitzung muss eine frühere Sitzung des Gremiums sein.');
    });

    /** §F/meetings/meetings/000940 */
    it('keeps the first meeting of a started repeat meeting', async () => {
      const live = { ...FULL, status: 'live', kind: 'repeat', repeatOfId: 'm-0' } as unknown as Meeting;
      const { http, fixture, cmp } = await setup(live);
      flushRoster(http, fixture);
      expect(screen.queryByLabelText(/Erste Sitzung/)).toBeNull();
      cmp.save();
      expect(http.expectOne('/api/meetings/m-1').request.body).not.toHaveProperty('repeatOfId');
    });

    /** §F/meetings/meetings/000940 */
    it('sends the same first meeting not again, and waits for the list', async () => {
      const planned = { ...FULL, gremiumId: 'g-1', kind: 'repeat', repeatOfId: 'm-0' } as unknown as Meeting;
      const { http, fixture, cmp } = await setup(planned);
      flushRoster(http, fixture);
      http.expectOne('/api/committees/g-1/meeting-defaults').error(new ProgressEvent('x'));
      const list = http.expectOne('/api/meetings?gremiumId=g-1');
      cmp.save();
      http.expectNone('/api/meetings/m-1');
      list.flush([{ id: 'm-0', title: '34. Sitzung', status: 'closed', votes: [], createdAt: 'x' }]);
      cmp.save();
      expect(http.expectOne('/api/meetings/m-1').request.body).not.toHaveProperty('repeatOfId');
    });

    it('has no list of first meetings after a failed read', async () => {
      const planned = { ...FULL, gremiumId: 'g-1', kind: 'repeat', repeatOfId: 'm-0' } as unknown as Meeting;
      const { http, fixture, cmp } = await setup(planned);
      flushRoster(http, fixture);
      http.expectOne('/api/committees/g-1/meeting-defaults').error(new ProgressEvent('x'));
      http.expectOne('/api/meetings?gremiumId=g-1').error(new ProgressEvent('x'));
      expect(cmp.repeatOfMissing()).toBe(true);
    });

    /** §F/meetings/meetings/000903 */
    it('locks the kind of a started meeting and refuses a place that is too long', async () => {
      const { http, fixture, cmp } = await setup({ ...FULL, status: 'live' } as unknown as Meeting);
      flushRoster(http, fixture);
      expect(cmp.kindLocked()).toBe(true);
      cmp.kind.set('repeat');
      cmp.location.set('x'.repeat(201));
      fixture.detectChanges();
      expect(cmp.valid()).toBe(false);
      expect(screen.getByRole('dialog')).toHaveTextContent('Der Ort darf höchstens 200 Zeichen haben.');
      cmp.location.set('Aula');
      cmp.save();
      const req = http.expectOne('/api/meetings/m-1');
      expect(req.request.body).not.toHaveProperty('kind');
      expect(req.request.body).toEqual(expect.objectContaining({ location: 'Aula' }));
    });
  });

  describe('public participation', () => {
    const LINK = { joinCode: '7KQ4MP', joinUrl: 'https://x.example/j/7KQ4MP', qr: { size: 1, rows: ['1'] } };
    const LIVE = {
      ...MEETING,
      status: 'live',
      canManage: true,
      publicJoin: true,
      guestsMode: 'vote',
      guestsVoteAllowed: true,
      pendingGuests: 2,
      admittedGuests: 5,
    } as unknown as Meeting;

    it('offers the switch only to the lead and sends only the changed fields', async () => {
      const { http, fixture, cmp } = await setup({ ...MEETING, canManage: true, publicJoin: false, guestsMode: 'vote', guestsVoteAllowed: true } as unknown as Meeting);
      flushRoster(http, fixture);
      await userEvent.click(screen.getByRole('switch', { name: /Öffentliche Teilnahme/ }));
      await userEvent.click(screen.getByRole('radio', { name: /Gäste schauen nur zu/ }));
      expect(cmp.confirmOff()).toBe(false);
      await userEvent.click(screen.getByRole('button', { name: 'Speichern' }));
      const req = http.expectOne('/api/meetings/m-1');
      expect(req.request.body).toEqual(expect.objectContaining({ publicJoin: true, guestsMode: 'watch' }));
    });

    /** §F/meetings/meetings/000904 */
    it('shows no choice and keeps "nur zuschauen" where guests get no ballot', async () => {
      const { http, fixture, cmp } = await setup({ ...MEETING, canManage: true, publicJoin: false, guestsMode: 'vote', guestsVoteAllowed: false } as unknown as Meeting);
      flushRoster(http, fixture);
      expect(cmp.guestsMode()).toBe('watch');
      await userEvent.click(screen.getByRole('switch', { name: /Öffentliche Teilnahme/ }));
      expect(screen.getByText('Gäste schauen in diesem Gremium nur zu.')).toBeInTheDocument();
      expect(screen.queryByRole('radio', { name: /Gäste dürfen abstimmen/ })).toBeNull();
      await userEvent.click(screen.getByRole('button', { name: 'Speichern' }));
      const req = http.expectOne('/api/meetings/m-1');
      expect(req.request.body).toEqual(expect.objectContaining({ publicJoin: true, guestsMode: 'watch' }));
    });

    it('loads the link, rotates it and asks before the switch goes off in a live meeting', async () => {
      const { http, fixture, cmp, toasts } = await setup(LIVE);
      http.expectOne('/api/meetings/m-1/join-link').flush(LINK);
      flushRoster(http, fixture);
      expect(screen.getByText(LINK.joinUrl)).toBeInTheDocument();
      await userEvent.click(screen.getByRole('button', { name: /Neuen Link erzeugen/ }));
      await userEvent.click(screen.getAllByRole('button', { name: /Neuen Link erzeugen/ })[0]);
      http.expectOne('/api/meetings/m-1/join-code/rotate').flush({ ...LINK, joinCode: '9XH2TR' });
      expect(toasts()).toContain('Neuer Beitrittslink erzeugt. Der alte gilt nicht mehr.');
      cmp.rotate();
      http
        .expectOne('/api/meetings/m-1/join-code/rotate')
        .flush({ code: 'meeting_closed', detail: 'zu' }, { status: 409, statusText: 'Conflict' });
      expect(toasts()).toContain('Aktion fehlgeschlagen.: zu');

      await userEvent.click(screen.getByRole('switch', { name: /Öffentliche Teilnahme/ }));
      const confirm = screen.getByRole('dialog', { name: 'Öffentliche Teilnahme ausschalten?' });
      expect(confirm).toHaveTextContent('2 offene Anfragen verfallen und 5 zugelassene Gäste');
      await userEvent.click(within(confirm).getAllByRole('button', { name: 'Abbrechen' }).at(-1)!);
      expect(cmp.publicJoin()).toBe(true);
      await userEvent.click(screen.getByRole('switch', { name: /Öffentliche Teilnahme/ }));
      await userEvent.click(screen.getByRole('button', { name: 'Ausschalten' }));
      expect(cmp.publicJoin()).toBe(false);
      await userEvent.click(screen.getByRole('button', { name: 'Speichern' }));
      const req = http.expectOne('/api/meetings/m-1');
      expect(req.request.body).toEqual(expect.objectContaining({ publicJoin: false }));
      req.flush({ code: 'guest_vote_open' }, { status: 409, statusText: 'Conflict' });
      await userEvent.click(screen.getByRole('button', { name: 'Speichern' }));
      http
        .expectOne('/api/meetings/m-1')
        .flush({ code: 'guests_vote_needs_no_quorum' }, { status: 422, statusText: 'x' });
      expect(toasts()).toContain('In diesem Gremium dürfen Gäste nicht abstimmen.');
      expect(toasts()).toContain(
        'Eine Abstimmung mit Gästen ist offen. Schließe sie, bevor Gäste nur noch zuschauen.',
      );
    });

    it('ignores a second rotation and a late link of another meeting', async () => {
      const { http, fixture, cmp } = await setup(LIVE);
      const linkReq = http.expectOne('/api/meetings/m-1/join-link');
      flushRoster(http, fixture);
      fixture.componentRef.setInput('meeting', null);
      fixture.detectChanges();
      linkReq.flush(LINK);
      expect(cmp.link()).toBeNull();
      cmp.rotate();
      http.expectNone('/api/meetings/m-1/join-code/rotate');
      fixture.componentRef.setInput('meeting', LIVE);
      fixture.detectChanges();
      http.expectOne('/api/meetings/m-1/join-link').error(new ProgressEvent('x'));
      flushRoster(http, fixture);
      cmp.rotate();
      cmp.rotate();
      expect(http.match('/api/meetings/m-1/join-code/rotate')).toHaveLength(1);
    });
  });
});
