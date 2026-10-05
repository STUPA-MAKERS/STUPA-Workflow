import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { Delegation, MeetingDelegationContext } from '@core/api/delegations.service';
import type { Attendance, Meeting } from '@core/api/models';
import { MEDIA, ToastService } from '@stupa-makers/ui-kit';
import {
  ATTENDANCE,
  DELEGATION_CONTEXT,
  matchMediaQueries,
  meeting,
} from '../../../../testing/meeting-fixtures';
import { AttendanceSheetComponent } from './attendance-sheet.component';

const ROSTER: Attendance[] = [
  ...ATTENDANCE,
  { principalId: 'pr-4', displayName: 'Vera Vertretung', email: null, status: 'excused', source: 'self', note: 'Prüfung', isSelf: false },
  { principalId: 'pr-5', displayName: 'Fritz Fehlend', email: null, status: 'absent', source: 'lead', note: null, isSelf: false },
];

function delegation(over: Partial<Delegation> = {}): Delegation {
  return {
    id: 'd-1',
    meetingId: 'm-1',
    meetingTitle: 'Konstituierende Sitzung',
    meetingDate: '2026-10-15',
    gremiumId: 'g-1',
    gremiumName: 'StuPa',
    delegatorId: 'pr-4',
    delegatorName: 'Vera Vertretung',
    delegateId: 'pr-9',
    delegateName: 'Sven Stellvertreter',
    delegateVoting: true,
    viaPool: false,
    createdAt: '2026-10-01T00:00:00Z',
    revocable: true,
    direction: null,
    ...over,
  };
}

interface Inputs {
  open: boolean;
  meeting: Meeting;
  attendance: Attendance[];
  saving: boolean;
  viewers: string[];
  conflictId: string | null;
}

let restoreMedia: (() => void) | null = null;
afterEach(() => {
  restoreMedia?.();
  restoreMedia = null;
  document.body.style.overflow = '';
});

const toast = { success: jest.fn(), error: jest.fn() };

/**
 * Render the open sheet and answer its delegation list with `delegations`, and the context
 * of the own-delegation section with `context`.
 */
async function setup(
  over: Partial<Inputs> = {},
  delegations: Delegation[] = [],
  media: string[] = [],
  context: MeetingDelegationContext = DELEGATION_CONTEXT,
) {
  restoreMedia = matchMediaQueries(...media);
  toast.success.mockReset();
  toast.error.mockReset();
  const statusChange = jest.fn();
  const reset = jest.fn();
  const conflictResolved = jest.fn();
  const view = await render(AttendanceSheetComponent, {
    inputs: {
      open: true,
      meeting: meeting(),
      attendance: ROSTER,
      saving: false,
      viewers: ['Pia Protokoll', 'Alina Admin'],
      conflictId: null,
      ...over,
    },
    on: { statusChange, statusReset: reset, conflictResolved },
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: ToastService, useValue: toast },
    ],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  http.match((r) => r.url.endsWith('/delegations')).forEach((r) => r.flush(delegations));
  http.match((r) => r.url.includes('/delegations/meetings/')).forEach((r) => r.flush(context));
  view.fixture.detectChanges();
  return { ...view, http, statusChange, reset, conflictResolved };
}

const sheet = () => screen.getByRole('dialog', { name: 'Anwesenheit' });
const row = (name: string) => within(sheet()).getByRole('radiogroup', { name: `Anwesenheit von ${name}` });

describe('AttendanceSheetComponent', () => {
  it('counts the states and filters the members by the search', async () => {
    await setup();
    expect(sheet()).toHaveClass('ss--end');
    const counts = [...(sheet().querySelectorAll('.as__counts > span') as NodeListOf<HTMLElement>)];
    expect(counts.map((c) => c.textContent?.replace(/\s+/g, ' ').trim())).toEqual([
      '1 anwesend', '2 entschuldigt', '1 unentschuldigt', '1 offen',
    ]);
    await userEvent.type(within(sheet()).getByRole('searchbox', { name: 'Mitglied suchen' }), 'vera');
    expect(within(sheet()).getAllByRole('radiogroup')).toHaveLength(1);
    await userEvent.type(within(sheet()).getByRole('searchbox', { name: 'Mitglied suchen' }), 'zzz');
    expect(within(sheet()).getByText('Kein Mitglied gefunden.')).toBeInTheDocument();
  });

  it('lets the lead set the four states, "Offen" as a reset (O15)', async () => {
    const { statusChange, reset } = await setup();
    const mika = row('Mika Mitglied');
    const radios = within(mika).getAllByRole('radio');
    expect(radios.map((r) => r.textContent?.trim())).toEqual([
      'Anwesend', 'Entschuldigt', 'Unentschuldigt', 'Offen',
    ]);
    expect(within(mika).getByRole('radio', { name: 'Entschuldigt' })).toHaveAttribute('aria-checked', 'true');
    await userEvent.click(within(mika).getByRole('radio', { name: 'Anwesend' }));
    expect(statusChange).toHaveBeenLastCalledWith({ member: expect.objectContaining({ principalId: 'pr-2' }), status: 'present' });
    await userEvent.click(within(mika).getByRole('radio', { name: 'Unentschuldigt' }));
    expect(statusChange).toHaveBeenLastCalledWith({ member: expect.objectContaining({ principalId: 'pr-2' }), status: 'absent' });
    // The chosen state sends nothing.
    statusChange.mockClear();
    await userEvent.click(within(mika).getByRole('radio', { name: 'Entschuldigt' }));
    expect(statusChange).not.toHaveBeenCalled();
    await userEvent.click(within(mika).getByRole('radio', { name: 'Offen' }));
    expect(reset).toHaveBeenCalledWith(expect.objectContaining({ principalId: 'pr-2' }));
    // An open row has nothing to reset.
    reset.mockClear();
    await userEvent.click(within(row('Alina Admin')).getByRole('radio', { name: 'Offen' }));
    expect(reset).not.toHaveBeenCalled();
  });

  it('moves the focus with the arrow keys and sets the state only on Enter', async () => {
    const { statusChange, reset, fixture } = await setup();
    // The sheet takes the focus when it opens; wait for that first.
    await new Promise((r) => setTimeout(r, 50));
    const radio = (name: string) => within(row('Mika Mitglied')).getByRole('radio', { name });
    radio('Entschuldigt').focus();
    await userEvent.keyboard('{ArrowRight}');
    expect(radio('Unentschuldigt')).toHaveFocus();
    // The focused option is the tab stop of the row; the state did not change.
    expect(radio('Unentschuldigt')).toHaveAttribute('tabindex', '0');
    expect(radio('Entschuldigt')).toHaveAttribute('tabindex', '-1');
    expect(radio('Entschuldigt')).toHaveAttribute('aria-checked', 'true');
    // A step onto "Offen" does not reset the record.
    await userEvent.keyboard('{ArrowRight}');
    expect(radio('Offen')).toHaveFocus();
    expect(statusChange).not.toHaveBeenCalled();
    expect(reset).not.toHaveBeenCalled();
    await userEvent.keyboard('{ArrowLeft}{Enter}');
    expect(statusChange).toHaveBeenCalledTimes(1);
    expect(statusChange).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'absent' }));
    // When the focus leaves the row, its tab stop is the chosen option again.
    radio('Unentschuldigt').blur();
    fixture.detectChanges();
    expect(radio('Entschuldigt')).toHaveAttribute('tabindex', '0');
  });

  it('counts an excuse and an absence as one "abwesend" for a member (Z2)', async () => {
    await setup({ meeting: meeting({ canControl: false }) });
    const counts = [...(sheet().querySelectorAll('.as__counts > span') as NodeListOf<HTMLElement>)];
    expect(counts.map((c) => c.textContent?.replace(/\s+/g, ' ').trim())).toEqual([
      '1 anwesend', '3 abwesend', '1 offen',
    ]);
  });

  it('names the minute-taker in the sub line', async () => {
    await setup();
    expect(within(sheet()).getByText('führt das Protokoll', { selector: '.as__sub' })).toBeInTheDocument();
  });

  it('shows the source and the reason in the sub line', async () => {
    await setup();
    expect(within(sheet()).getAllByText('durch Sitzungsleitung', { selector: '.as__sub' })).toHaveLength(2);
    expect(within(sheet()).getByText('Grund: Prüfung')).toBeInTheDocument();
    // The own row says so.
    expect(within(sheet()).getByText('(du)')).toBeInTheDocument();
  });

  it('gives a member only the own row, as present or absent (Z2)', async () => {
    const { statusChange } = await setup({ meeting: meeting({ canControl: false }) });
    const own = row('Pia Protokoll');
    expect(within(own).getAllByRole('radio').map((r) => r.textContent?.trim())).toEqual(['Anwesend', 'Abwesend']);
    await userEvent.click(within(own).getByRole('radio', { name: 'Abwesend' }));
    expect(statusChange).toHaveBeenCalledWith({ member: expect.objectContaining({ principalId: 'pr-1' }), status: 'excused' });
    // Every other row is read-only: an excuse reads "Abwesend" to a member.
    expect(within(sheet()).getAllByRole('radiogroup')).toHaveLength(1);
    expect(within(sheet()).getAllByText('Abwesend', { selector: 'app-status-text' }).length).toBeGreaterThan(0);
    expect(within(sheet()).getByText('Offen', { selector: 'app-status-text' })).toBeInTheDocument();
  });

  it('gives the open own row of a member a tab stop on "Anwesend"', async () => {
    const roster: Attendance[] = [{ ...ROSTER[0], status: null, source: null }, ...ROSTER.slice(1)];
    await setup({ meeting: meeting({ canControl: false }), attendance: roster });
    const own = row('Pia Protokoll');
    expect(within(own).getByRole('radio', { name: 'Anwesend' })).toHaveAttribute('tabindex', '0');
    expect(within(own).getByRole('radio', { name: 'Abwesend' })).toHaveAttribute('tabindex', '-1');
    expect(within(own).getAllByRole('radio').every((r) => r.getAttribute('aria-checked') === 'false')).toBe(true);
  });

  it('gives the open own row the tab stop on "Abwesend" while a delegation blocks "Anwesend" (O23)', async () => {
    const roster: Attendance[] = [{ ...ROSTER[0], status: null, source: null }, ...ROSTER.slice(1)];
    await setup(
      { meeting: meeting({ canControl: false }), attendance: roster },
      [delegation({ delegatorId: 'pr-1', delegatorName: 'Pia Protokoll' })],
    );
    const own = row('Pia Protokoll');
    expect(within(own).getByRole('radio', { name: 'Anwesend' })).toHaveAttribute('tabindex', '-1');
    expect(within(own).getByRole('radio', { name: 'Abwesend' })).toHaveAttribute('tabindex', '0');
  });

  it('locks the own row of a member once the lead set it (O15)', async () => {
    const roster: Attendance[] = [{ ...ROSTER[0], source: 'lead', status: 'excused' }];
    await setup({ meeting: meeting({ canControl: false }), attendance: roster });
    expect(within(sheet()).queryByRole('radiogroup')).toBeNull();
    expect(within(sheet()).getByText('Abwesend', { selector: 'app-status-text' })).toBeInTheDocument();
    expect(within(sheet()).getByText('durch Sitzungsleitung · führt das Protokoll')).toBeInTheDocument();
  });

  it('freezes every row of a closed meeting', async () => {
    await setup({ meeting: meeting({ status: 'closed' }) });
    expect(within(sheet()).queryByRole('radiogroup')).toBeNull();
    expect(within(sheet()).getByText('Unentschuldigt', { selector: 'app-status-text' })).toBeInTheDocument();
    // The live list is for a running meeting.
    expect(within(sheet()).queryByText(/Live dabei/)).toBeNull();
  });

  it('keeps a gap for the row menu only while some row has a menu', async () => {
    // Mika Mitglied: an excuse the lead set, so the row has a menu; the others keep a gap.
    const { rerender } = await setup({ meeting: meeting({ canManage: false }) });
    const gaps = () => sheet().querySelectorAll('.as__menuGap').length;
    expect(within(sheet()).getByRole('button', { name: 'Aktionen für Mika Mitglied' })).toBeInTheDocument();
    expect(gaps()).toBe(ROSTER.length - 1);
    // No row has a menu: no row keeps a gap, so the control ends at the inset of the row.
    await rerender({ inputs: { attendance: [ROSTER[0], ROSTER[2], ROSTER[4]] }, partialUpdate: true });
    expect(within(sheet()).queryByRole('button', { name: /^Aktionen für/ })).toBeNull();
    expect(gaps()).toBe(0);
  });

  it('edits the reason of an excuse from the row menu', async () => {
    const roster: Attendance[] = [{ ...ROSTER[0], status: 'excused', note: null }, ROSTER[1], ROSTER[3]];
    const { statusChange } = await setup({ attendance: roster, meeting: meeting({ canManage: false }) });
    // The lead edits the own reason and the reason of a row the lead set; a member's own
    // reason stays the member's.
    expect(within(sheet()).getByRole('button', { name: 'Aktionen für Mika Mitglied' })).toBeInTheDocument();
    expect(within(sheet()).queryByRole('button', { name: 'Aktionen für Vera Vertretung' })).toBeNull();
    await userEvent.click(within(sheet()).getByRole('button', { name: 'Aktionen für Pia Protokoll' }));
    await userEvent.click(await screen.findByRole('menuitem', { name: 'Grund eintragen' }));
    const field = within(sheet()).getByRole('textbox', { name: 'Grund' });
    expect(field).toHaveFocus();
    await userEvent.type(field, 'Krank{Enter}');
    expect(statusChange).toHaveBeenCalledWith({
      member: expect.objectContaining({ principalId: 'pr-1' }),
      status: 'excused',
      note: 'Krank',
    });
    // Escape leaves the reason as it is.
    statusChange.mockClear();
    await userEvent.click(within(sheet()).getByRole('button', { name: 'Aktionen für Pia Protokoll' }));
    await userEvent.click(await screen.findByRole('menuitem', { name: 'Grund eintragen' }));
    await userEvent.type(within(sheet()).getByRole('textbox', { name: 'Grund' }), 'x{Escape}');
    expect(statusChange).not.toHaveBeenCalled();
    expect(within(sheet()).queryByRole('textbox', { name: 'Grund' })).toBeNull();
  });

  it('blocks "present" for a member with a delegation and revokes it (O23, O6)', async () => {
    const { http, fixture } = await setup({}, [delegation()]);
    const jonas = row('Vera Vertretung');
    const present = within(jonas).getByRole('radio', { name: 'Anwesend' });
    expect(present).toHaveAttribute('aria-disabled', 'true');
    expect(present).toHaveAttribute('title', 'Erst die Vertretung widerrufen.');
    expect(within(sheet()).getByText('Grund: Prüfung · vertreten durch Sven Stellvertreter · mit Stimmrecht')).toBeInTheDocument();
    const section = within(sheet()).getByRole('region', { name: 'Vertretungen' });
    expect(within(section).getByText('Vertretungen · 1')).toBeInTheDocument();
    expect(within(section).getByText('Vera Vertretung → Sven Stellvertreter')).toBeInTheDocument();
    await userEvent.click(within(section).getByRole('button', { name: 'Widerrufen' }));
    const del = http.expectOne('/api/delegations/d-1');
    expect(del.request.method).toBe('DELETE');
    del.flush(null);
    expect(toast.success).toHaveBeenCalled();
    http.expectOne((r) => r.url.endsWith('/delegations')).flush([]);
    fixture.detectChanges();
    expect(within(row('Vera Vertretung')).getByRole('radio', { name: 'Anwesend' })).not.toHaveAttribute('aria-disabled');
  });

  it('marks the row the server refused (409 delegation_active) and offers the revoke', async () => {
    const { fixture, http, conflictResolved } = await setup();
    fixture.componentRef.setInput('conflictId', 'pr-4');
    fixture.detectChanges();
    // The refusal reloads the delegations: now the page knows the delegation.
    http.expectOne((r) => r.url.endsWith('/delegations')).flush([delegation()]);
    fixture.detectChanges();
    const alert = within(sheet()).getByRole('alert');
    expect(alert).toHaveTextContent('Vertretung aktiv: erst widerrufen, dann als anwesend erfassen.');
    await userEvent.click(within(alert).getByRole('button', { name: 'Vertretung widerrufen' }));
    http.expectOne('/api/delegations/d-1').flush(null);
    http.expectOne((r) => r.url.endsWith('/delegations')).flush([]);
    // The revoke ends the conflict: the page clears it, and the alert goes away.
    expect(conflictResolved).toHaveBeenCalledWith('pr-4');
    fixture.componentRef.setInput('conflictId', null);
    fixture.detectChanges();
    http.match((r) => r.url.endsWith('/delegations')).forEach((r) => r.flush([]));
    fixture.detectChanges();
    expect(within(sheet()).queryByRole('alert')).toBeNull();
    expect(within(row('Vera Vertretung')).getByRole('radio', { name: 'Anwesend' })).not.toHaveAttribute('aria-disabled');
  });

  it('ends no conflict with the revoke of another delegation', async () => {
    const { http, conflictResolved } = await setup({ conflictId: 'pr-4' }, [delegation({ id: 'd-2', delegatorId: 'pr-5' })]);
    await userEvent.click(within(sheet()).getByRole('button', { name: 'Widerrufen' }));
    http.expectOne('/api/delegations/d-2').flush(null);
    http.match((r) => r.url.endsWith('/delegations')).forEach((r) => r.flush([]));
    expect(conflictResolved).not.toHaveBeenCalled();
  });

  it('loads the rows again after a change in the own-delegation section, and the section after a revoke here', async () => {
    const own = delegation({ id: 'd-own', delegatorId: 'pr-1', delegatorName: 'Pia Protokoll', direction: 'outgoing' });
    const context: MeetingDelegationContext = {
      ...DELEGATION_CONTEXT,
      allowVoteDelegation: true,
      meetingStarted: false,
      canDelegate: true,
      myDelegation: own,
      recipients: [{ principalId: 'pr-2', displayName: 'Max Mitglied', viaPool: false, isMember: true }],
    };
    const { fixture, http, conflictResolved } = await setup({ conflictId: 'pr-1' }, [own], [], context);
    const pia = () => row('Pia Protokoll');
    expect(within(pia()).getByRole('radio', { name: 'Anwesend' })).toHaveAttribute('aria-disabled', 'true');
    // The member revokes the own delegation in the section: the rows know it at once.
    const section = within(sheet()).getByRole('region', { name: 'Vertretung' });
    await userEvent.click(within(section).getByRole('button', { name: 'Vertretung widerrufen' }));
    http.expectOne('/api/delegations/d-own').flush(null);
    http.expectOne((r) => r.url.includes('/delegations/meetings/')).flush({ ...context, myDelegation: null });
    http.expectOne((r) => r.url.endsWith('/delegations')).flush([]);
    fixture.detectChanges();
    expect(within(pia()).getByRole('radio', { name: 'Anwesend' })).not.toHaveAttribute('aria-disabled');
    expect(within(sheet()).queryByText(/vertreten durch/)).toBeNull();
    expect(conflictResolved).toHaveBeenCalledWith('pr-1');
    // A new delegation in the section blocks "Anwesend" again.
    await userEvent.click(within(section).getByRole('button', { name: 'Vertretung einrichten' }));
    const dialog = screen.getByRole('dialog', { name: 'Vertretung einrichten' });
    await userEvent.click(within(dialog).getByRole('radio', { name: /Max Mitglied/ }));
    await userEvent.click(within(dialog).getByRole('button', { name: 'Vertretung einrichten' }));
    http.expectOne((r) => r.method === 'POST' && r.url.endsWith('/delegations')).flush(own);
    http.expectOne((r) => r.url.includes('/delegations/meetings/')).flush(context);
    http.expectOne((r) => r.method === 'GET' && r.url.endsWith('/delegations')).flush([own]);
    fixture.detectChanges();
    expect(within(pia()).getByRole('radio', { name: 'Anwesend' })).toHaveAttribute('aria-disabled', 'true');
    // A revoke in the list of the lead loads the section again.
    await userEvent.click(within(within(sheet()).getByRole('region', { name: 'Vertretungen' })).getByRole('button', { name: 'Widerrufen' }));
    http.expectOne('/api/delegations/d-own').flush(null);
    http.expectOne((r) => r.url.endsWith('/delegations')).flush([]);
    http.expectOne((r) => r.url.includes('/delegations/meetings/')).flush({ ...context, myDelegation: null });
  });

  it('says only the refusal when the delegation cannot be revoked here', async () => {
    const { fixture, http } = await setup({ meeting: meeting({ canManage: false }) });
    fixture.componentRef.setInput('conflictId', 'pr-4');
    fixture.detectChanges();
    http.expectOne((r) => r.url.endsWith('/delegations')).flush([]);
    fixture.detectChanges();
    expect(within(sheet()).getByRole('alert')).toHaveTextContent('Vertretung aktiv');
    expect(within(sheet()).queryByRole('button', { name: 'Vertretung widerrufen' })).toBeNull();
    // A member who does not lead sees no list of the delegations.
    expect(within(sheet()).queryByRole('region', { name: 'Vertretungen' })).toBeNull();
  });

  it('reports a failed revoke', async () => {
    const { http } = await setup({}, [delegation()]);
    await userEvent.click(within(sheet()).getByRole('button', { name: 'Widerrufen' }));
    http.expectOne('/api/delegations/d-1').flush(null, { status: 403, statusText: 'x' });
    expect(toast.error).toHaveBeenCalled();
  });

  it('guards the control: no change while saving, a blocked option, and other keys', async () => {
    const { statusChange, reset, fixture } = await setup({ saving: true }, [delegation()]);
    const mika = row('Mika Mitglied');
    expect(within(mika).getByRole('radio', { name: 'Anwesend' })).toHaveAttribute('aria-disabled', 'true');
    await userEvent.click(within(mika).getByRole('radio', { name: 'Anwesend' }));
    await userEvent.click(within(mika).getByRole('radio', { name: 'Offen' }));
    expect(statusChange).not.toHaveBeenCalled();
    expect(reset).not.toHaveBeenCalled();
    fixture.componentRef.setInput('saving', false);
    fixture.detectChanges();
    // "Anwesend" of the delegator stays blocked; a click sends nothing.
    await userEvent.click(within(row('Vera Vertretung')).getByRole('radio', { name: 'Anwesend' }));
    expect(statusChange).not.toHaveBeenCalled();
    // The arrow keys skip the blocked option; other keys do nothing.
    await new Promise((r) => setTimeout(r, 50));
    within(row('Vera Vertretung')).getByRole('radio', { name: 'Entschuldigt' }).focus();
    await userEvent.keyboard('{Enter}{a}');
    expect(statusChange).not.toHaveBeenCalled();
    // From "Entschuldigt" left: "Anwesend" is blocked, so the focus wraps to "Offen".
    await userEvent.keyboard('{ArrowLeft}');
    expect(within(row('Vera Vertretung')).getByRole('radio', { name: 'Offen' })).toHaveFocus();
    expect(reset).not.toHaveBeenCalled();
    await userEvent.keyboard('{Enter}');
    expect(reset).toHaveBeenCalledWith(expect.objectContaining({ principalId: 'pr-4' }));
  });

  it('edits an existing reason, keeps an unchanged one and removes an emptied one', async () => {
    const roster: Attendance[] = [{ ...ROSTER[0], status: 'excused', note: 'Zug' }];
    const { statusChange } = await setup({ attendance: roster, meeting: meeting({ canManage: false }) });
    const edit = async () => {
      await userEvent.click(within(sheet()).getByRole('button', { name: 'Aktionen für Pia Protokoll' }));
      await userEvent.click(await screen.findByRole('menuitem', { name: 'Grund bearbeiten' }));
      return within(sheet()).getByRole('textbox', { name: 'Grund' });
    };
    let field = await edit();
    expect(field).toHaveValue('Zug');
    await userEvent.type(field, '{Enter}');
    expect(statusChange).not.toHaveBeenCalled();
    field = await edit();
    await userEvent.clear(field);
    await userEvent.type(field, '{Enter}');
    expect(statusChange).toHaveBeenCalledWith({ member: expect.objectContaining({ principalId: 'pr-1' }), status: 'excused', note: null });
  });

  it('names a member without a name by the e-mail, and else by a dash', async () => {
    const roster: Attendance[] = [
      { principalId: 'pr-7', displayName: null, email: 'kai@x.de', status: null, source: null, note: null, isSelf: false },
      { principalId: 'pr-8', displayName: null, email: null, status: null, source: null, note: null, isSelf: false },
    ];
    await setup({ attendance: roster }, [delegation({ delegatorId: 'pr-8', delegateName: null, delegateVoting: false, delegatorName: null })]);
    expect(within(sheet()).getByRole('radiogroup', { name: 'Anwesenheit von kai@x.de' })).toBeInTheDocument();
    expect(within(sheet()).getByRole('radiogroup', { name: 'Anwesenheit von —' })).toBeInTheDocument();
    expect(within(sheet()).getByText('vertreten durch —')).toBeInTheDocument();
    expect(within(sheet()).getByText('— → —')).toBeInTheDocument();
    await userEvent.type(within(sheet()).getByRole('searchbox', { name: 'Mitglied suchen' }), 'kai');
    expect(within(sheet()).getAllByRole('radiogroup')).toHaveLength(1);
  });

  it('shows no delegations when they fail to load, and keeps those of this meeting only', async () => {
    const { fixture, http } = await setup();
    fixture.componentRef.setInput('conflictId', 'pr-4');
    fixture.detectChanges();
    http.expectOne((r) => r.url.endsWith('/delegations')).flush(null, { status: 500, statusText: 'x' });
    fixture.detectChanges();
    expect(within(sheet()).queryByRole('region', { name: 'Vertretungen' })).toBeNull();
    fixture.componentRef.setInput('conflictId', null);
    fixture.detectChanges();
    http
      .expectOne((r) => r.url.endsWith('/delegations'))
      .flush([delegation({ meetingId: 'other' })]);
    fixture.detectChanges();
    expect(within(sheet()).queryByRole('region', { name: 'Vertretungen' })).toBeNull();
  });

  it('starts no second revoke while one runs', async () => {
    const { http } = await setup({}, [delegation()]);
    const button = within(sheet()).getByRole('button', { name: 'Widerrufen' });
    await userEvent.click(button);
    (button as HTMLButtonElement).click();
    http.expectOne('/api/delegations/d-1').flush(null);
    http.match((r) => r.url.endsWith('/delegations')).forEach((r) => r.flush([]));
  });

  it('lists the people who have the live meeting open', async () => {
    const { fixture } = await setup();
    const live = within(sheet()).getByRole('region', { name: 'Live dabei' });
    expect(within(live).getByText('Live dabei · 2')).toBeInTheDocument();
    expect(within(live).getByText('Alina Admin')).toBeInTheDocument();
    fixture.componentRef.setInput('viewers', []);
    fixture.detectChanges();
    expect(within(live).getByText('Niemand hat die Sitzung gerade geöffnet.')).toBeInTheDocument();
  });

  it('opens from the bottom on a phone and clears the search when it closes', async () => {
    const { fixture } = await setup({}, [], [MEDIA.phone]);
    expect(sheet()).toHaveClass('ss--bottom');
    await userEvent.type(within(sheet()).getByRole('searchbox', { name: 'Mitglied suchen' }), 'vera');
    await userEvent.keyboard('{Escape}');
    expect(fixture.componentInstance.open()).toBe(false);
    fixture.componentInstance.open.set(true);
    fixture.detectChanges();
    expect(within(sheet()).getByRole('searchbox', { name: 'Mitglied suchen' })).toHaveValue('');
  });

  describe('O6: the lead enters a substitute from the pool', () => {
    const menu = (name: string) => within(sheet()).queryByRole('button', { name: `Aktionen für ${name}` });

    it('offers the entry for a missing member without a delegation', async () => {
      await setup({}, [delegation()]);
      // Missing: excused (Mika), open (Alina), absent (Fritz). Pia is present and the
      // lead herself; Vera already has a delegation.
      for (const name of ['Mika Mitglied', 'Alina Admin', 'Fritz Fehlend']) {
        expect(menu(name)).toBeInTheDocument();
      }
      expect(menu('Pia Protokoll')).toBeNull();
      expect(menu('Vera Vertretung')).toBeNull();
      await userEvent.click(menu('Alina Admin')!);
      expect(await screen.findByRole('menuitem', { name: 'Vertretung eintragen' })).toBeInTheDocument();
    });

    it('offers no entry for a member without a vote or a member who already substitutes', async () => {
      const roster = ROSTER.map((a) => (a.displayName === 'Alina Admin' ? { ...a, canVote: false } : a));
      // Fritz already substitutes a member of another row: no chains (the server refuses).
      await setup({ attendance: roster }, [delegation({ id: 'd-2', delegatorId: 'pr-7', delegateId: 'pr-5' })]);
      expect(menu('Alina Admin')).toBeNull();
      expect(menu('Fritz Fehlend')).toBeNull();
      // A member with the vote right, and a row without the flag (older server), keep it.
      expect(menu('Mika Mitglied')).toBeInTheDocument();
      expect(menu('Vera Vertretung')).toBeInTheDocument();
    });

    it.each([
      ['a planned meeting', { status: 'planned' as const }],
      ['a member who does not manage', { canManage: false }],
    ])('offers no entry in %s', async (_label, over) => {
      await setup({ meeting: meeting(over), attendance: [ROSTER[3], ROSTER[4]] });
      expect(within(sheet()).queryByRole('button', { name: /^Aktionen für/ })).toBeNull();
    });

    it('picks a substitute and shows it in the row', async () => {
      const { http, fixture } = await setup();
      await userEvent.click(menu('Fritz Fehlend')!);
      await userEvent.click(await screen.findByRole('menuitem', { name: 'Vertretung eintragen' }));
      const picker = screen.getByRole('dialog', { name: 'Vertretung eintragen' });
      expect(within(picker).getByText('für Fritz Fehlend')).toBeInTheDocument();
      http
        .expectOne('/api/delegations/meetings/m-1/recipients?delegatorId=pr-5')
        .flush([{ principalId: 'pr-9', displayName: 'Sven Stellvertreter', viaPool: true, isMember: false }]);
      http.expectOne('/api/delegations/meetings/m-1/context').flush({ ...DELEGATION_CONTEXT, allowVoteDelegation: true });
      fixture.detectChanges();
      await userEvent.click(within(picker).getByRole('radio', { name: /Sven Stellvertreter/ }));
      await userEvent.click(within(picker).getByRole('button', { name: 'Vertretung eintragen' }));
      const made = delegation({ id: 'd-2', delegatorId: 'pr-5', delegatorName: 'Fritz Fehlend', delegateVoting: false });
      const post = http.expectOne((r) => r.method === 'POST' && r.url === '/api/delegations');
      expect(post.request.body).toMatchObject({ delegatorId: 'pr-5', delegateId: 'pr-9' });
      post.flush(made);
      http.expectOne((r) => r.method === 'GET' && r.url.endsWith('/delegations')).flush([made]);
      fixture.detectChanges();
      expect(screen.queryByRole('dialog', { name: 'Vertretung eintragen' })).toBeNull();
      expect(within(sheet()).getByText('vertreten durch Sven Stellvertreter · durch Sitzungsleitung')).toBeInTheDocument();
      expect(menu('Fritz Fehlend')).toBeNull();
    });

    it('closes the picker on cancel and when the sheet closes', async () => {
      const { http, fixture } = await setup();
      const open = async () => {
        await userEvent.click(menu('Alina Admin')!);
        await userEvent.click(await screen.findByRole('menuitem', { name: 'Vertretung eintragen' }));
        http.match((r) => r.url.includes('/delegations/meetings/')).forEach((r) => r.flush([]));
      };
      await open();
      const picker = screen.getByRole('dialog', { name: 'Vertretung eintragen' });
      await userEvent.click(within(picker).getAllByRole('button', { name: 'Abbrechen' })[0]);
      expect(screen.queryByRole('dialog', { name: 'Vertretung eintragen' })).toBeNull();
      await open();
      fixture.componentInstance.open.set(false);
      fixture.detectChanges();
      expect(screen.queryByRole('dialog', { name: 'Vertretung eintragen' })).toBeNull();
    });
  });
});
