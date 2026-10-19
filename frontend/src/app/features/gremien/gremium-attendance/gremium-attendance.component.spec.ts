import { render, screen, within } from '@testing-library/angular';
import { of, throwError } from 'rxjs';
import { GremienApiService } from '@core/api/gremien.service';
import { downloadBlob, MEDIA } from '@stupa-makers/ui-kit';
import { runAxe } from '../../../../testing/a11y';
import { GREMIEN_TEST_NOW, attendance, gremienApiMock } from '../../../../testing/gremien-fixtures';
import { matchMediaQueries } from '../../../../testing/meeting-fixtures';
import { GREMIEN_NOW } from '../gremien.store';
import { GremiumAttendanceComponent } from './gremium-attendance.component';

jest.mock('@stupa-makers/ui-kit', () => ({
  __esModule: true,
  ...jest.requireActual('@stupa-makers/ui-kit'),
  downloadBlob: jest.fn(),
}));

function readBlob(blob: Blob): Promise<string> {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.readAsText(blob);
  });
}

async function setup(opts: { api?: ReturnType<typeof gremienApiMock>; phone?: boolean; fill?: boolean } = {}) {
  localStorage.setItem('ap.locale', 'de');
  const restore = matchMediaQueries(...(opts.phone ? [MEDIA.phone] : []));
  const api = opts.api ?? gremienApiMock();
  const view = await render(GremiumAttendanceComponent, {
    inputs: { gremiumId: 'g-1', gremiumName: 'Studierendenparlament', fill: opts.fill ?? false },
    providers: [
      { provide: GremienApiService, useValue: api },
      { provide: GREMIEN_NOW, useValue: GREMIEN_TEST_NOW },
    ],
  });
  return { ...view, api, restore, cmp: view.fixture.componentInstance };
}

describe('GremiumAttendanceComponent', () => {
  let restore: (() => void) | null = null;
  afterEach(() => {
    restore?.();
    restore = null;
    localStorage.clear();
    (downloadBlob as jest.Mock).mockClear();
  });

  it('shows the matrix with the counts, the marks, the sums and the average', async () => {
    const view = await setup({ fill: true });
    restore = view.restore;
    expect(view.api.attendance).toHaveBeenCalledWith('g-1', { from: '2026-05', to: '2026-10' });
    expect((view.container as HTMLElement).classList.contains('gat-host--fill')).toBe(true);
    expect(view.cmp.rangeText()).toBe('Zeitraum: Mai – Okt 2026');

    const table = screen.getByRole('table');
    const heads = within(table).getAllByRole('columnheader').map((h) => h.textContent?.replace(/\s+/g, ' ').trim());
    expect(heads).toEqual(['Mitglied', 'Sep2 Sitzungen', 'Okt0 Sitzungen', 'Gesamt 2 Sitzungen']);

    // Quota ascending: 1/2, 2/2, then the person without a meeting.
    const names = within(table)
      .getAllByRole('rowheader')
      .map((h) => (h.querySelector('.gat__name') ?? h).textContent?.trim());
    expect(names).toEqual(['Finn Schulze', 'Anna Berg', 'Kai Meier', 'Ø anwesend je Sitzung']);

    const cell = screen.getByRole('button', {
      name: 'Finn Schulze, September 2026: 1 von 2 Sitzungen anwesend, 1 entschuldigt, 1 Stimme übertragen',
    });
    expect(cell).toHaveTextContent('1/2');
    expect(cell.querySelector('.gat__ex:not(.gat__ex--dv)')?.textContent).toBe('1');
    expect(cell.querySelector('.gat__ex--dv')?.textContent).toBe('1V');
    expect(screen.getByRole('button', { name: /^Anna Berg, September 2026/ }).classList.contains('gat__cell--full')).toBe(true);
    expect(screen.getByRole('img', { name: 'Finn Schulze, Oktober 2026: keine Sitzung' })).toHaveTextContent('—');
    expect(screen.getByRole('img', { name: 'Kai Meier, September 2026: nicht Mitglied' })).toBeTruthy();

    const rows = within(table).getAllByRole('row');
    expect(rows[1]).toHaveTextContent('50 %');
    expect(rows[3]).toHaveTextContent('0/0');
    expect(rows[3]).toHaveTextContent('—');
    expect([...rows[4].querySelectorAll('td')].map((c) => c.textContent?.trim())).toEqual(['1,5', '—', '1,5']);
    expect(screen.getByRole('list', { name: 'Legende' })).toHaveTextContent('Stimme übertragen');
    expect(await runAxe(view.container)).toHaveNoViolations();
  });

  it('opens the meetings of a month from a cell', async () => {
    const view = await setup();
    restore = view.restore;
    screen.getByRole('button', { name: /^Finn Schulze, September 2026/ }).click();
    view.fixture.detectChanges();
    expect(view.api.memberAttendance).toHaveBeenCalledWith('g-1', 'p-1', '2026-09');
    expect(screen.getByRole('dialog', { name: 'Finn Schulze · September 2026' })).toHaveTextContent(
      '1 von 2 Sitzungen anwesend, 1 entschuldigt, 1 Stimme übertragen',
    );
  });

  it('sorts by quota both ways and by name, and from the head', async () => {
    const view = await setup();
    restore = view.restore;
    const order = () => view.cmp.rows().map((r) => r.name);
    view.cmp.setSort('quotaDesc');
    expect(order()).toEqual(['Anna Berg', 'Finn Schulze', 'Kai Meier']);
    expect(view.cmp.sortText()).toBe('Sortierung: Quote absteigend');
    view.cmp.setSort('name');
    view.fixture.detectChanges();
    expect(order()).toEqual(['Anna Berg', 'Finn Schulze', 'Kai Meier']);
    expect(screen.getByRole('columnheader', { name: /Gesamt/ }).getAttribute('aria-sort')).toBe('none');
    view.cmp.setSort('odd');
    expect(view.cmp.sort()).toBe('quotaAsc');
    view.fixture.detectChanges();
    expect(screen.getByRole('columnheader', { name: /Gesamt/ }).getAttribute('aria-sort')).toBe('ascending');
    screen.getByRole('button', { name: /Gesamt/ }).click();
    view.fixture.detectChanges();
    expect(view.cmp.sort()).toBe('quotaDesc');
    expect(screen.getByRole('columnheader', { name: /Gesamt/ }).getAttribute('aria-sort')).toBe('descending');
    view.cmp.toggleQuotaSort();
    expect(view.cmp.sort()).toBe('quotaAsc');
  });

  it('filters by role and says when no one has it', async () => {
    const view = await setup();
    restore = view.restore;
    expect(view.cmp.roleOptions().map((o) => o.label)).toEqual(['Alle Rollen', 'Mitglied', 'Vorstand']);
    expect(view.cmp.roleText()).toBeNull();
    view.cmp.role.set('vorstand');
    expect(view.cmp.roleText()).toBe('Rolle: Vorstand');
    expect(view.cmp.rows().map((r) => r.name)).toEqual(['Anna Berg']);
    view.cmp.role.set('gone');
    view.fixture.detectChanges();
    expect(view.cmp.roleText()).toBe('Rolle: gone');
    expect(screen.getByText('Kein Mitglied hat diese Rolle.')).toBeTruthy();
  });

  it('reads another range with each preset and names the semesters', async () => {
    const view = await setup();
    restore = view.restore;
    expect(view.cmp.rangeOptions().map((o) => o.label)).toEqual([
      'Letzte 6 Monate',
      'Letzte 12 Monate',
      'Letzte 24 Monate',
      'Wintersemester 26/27',
      'Sommersemester 2026',
    ]);
    view.cmp.setPreset('last12');
    view.fixture.detectChanges();
    expect(view.api.attendance).toHaveBeenLastCalledWith('g-1', { from: '2025-11', to: '2026-10' });
    view.cmp.setPreset('prevSemester');
    view.fixture.detectChanges();
    expect(view.api.attendance).toHaveBeenLastCalledWith('g-1', { from: '2026-04', to: '2026-09' });
    view.cmp.setPreset('odd');
    expect(view.cmp.preset()).toBe('last6');
  });

  it('exports the matrix as CSV', async () => {
    const view = await setup();
    restore = view.restore;
    screen.getByRole('button', { name: 'Als CSV exportieren' }).click();
    const [blob, name] = (downloadBlob as jest.Mock).mock.calls[0] as [Blob, string];
    expect(name).toBe('studierendenparlament-anwesenheit-2026-05-2026-10.csv');
    const lines = (await readBlob(blob)).replace(String.fromCharCode(0xfeff), '').split('\r\n');
    expect(lines[0]).toBe(
      'Mitglied;Rolle;September 2026 Sitzungen;September 2026 anwesend;September 2026 entschuldigt;September 2026 übertragen;' +
        'Oktober 2026 Sitzungen;Oktober 2026 anwesend;Oktober 2026 entschuldigt;Oktober 2026 übertragen;' +
        'Gesamt anwesend;Gesamt Sitzungen;Gesamt %',
    );
    expect(lines[1]).toBe('Finn Schulze;Mitglied;2;1;1;1;0;0;0;0;1;2;50');
    expect(lines[3]).toBe('Kai Meier;Mitglied;;;;;0;0;0;0;0;0;');
  });

  it('exports nothing before the data is there', async () => {
    const view = await setup({ api: gremienApiMock({ attendance: jest.fn(() => throwError(() => new Error('x'))) }) });
    restore = view.restore;
    view.cmp.exportCsv();
    expect(downloadBlob).not.toHaveBeenCalled();
  });

  it('shows a grey skeleton for a range without a meeting', async () => {
    const empty = attendance({ months: [{ month: '2026-09', meetings: 0 }], rows: [] });
    const view = await setup({ api: gremienApiMock({ attendance: jest.fn(() => of(empty)) }) });
    restore = view.restore;
    expect(view.cmp.noMeetings()).toBe(true);
    expect(screen.getByText('Im Zeitraum gab es keine abgeschlossene Sitzung.').classList).toContain('sr-only');
    expect(screen.queryByRole('alert')).toBeNull();
    expect(view.container.querySelectorAll('.gat__ghostRow')).toHaveLength(4);
    expect(view.cmp.heads()[0].meetings).toBe('0 Sitzungen');
  });

  it('says when the range has no member', async () => {
    const empty = attendance({ months: [{ month: '2026-09', meetings: 1 }], rows: [] });
    const view = await setup({ api: gremienApiMock({ attendance: jest.fn(() => of(empty)) }) });
    restore = view.restore;
    expect(screen.getByText('Im Zeitraum gab es keine Mitglieder.')).toBeTruthy();
    expect(view.cmp.heads()[0].meetings).toBe('1 Sitzung');
    expect(view.cmp.averages().total).toBe('0,0');
  });

  it('reports a failed read and reads again', async () => {
    const attendanceFn = jest.fn(() => throwError(() => new Error('x')));
    const view = await setup({ api: gremienApiMock({ attendance: attendanceFn }) });
    restore = view.restore;
    expect(screen.getByRole('alert')).toHaveTextContent('Die Anwesenheit konnte nicht geladen werden.');
    attendanceFn.mockReturnValue(of(attendance()));
    screen.getByRole('button', { name: 'Erneut versuchen' }).click();
    view.fixture.detectChanges();
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.getByRole('table')).toBeTruthy();
  });

  it('shows a card per person on a phone and opens the bottom sheet', async () => {
    const view = await setup({ phone: true });
    restore = view.restore;
    expect(screen.queryByRole('table')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Als CSV exportieren' })).toBeNull();
    const cards = screen.getAllByRole('button', { name: /anwesend$/ });
    expect(cards.map((c) => c.getAttribute('aria-label'))).toEqual([
      'Anna Berg, 2 von 2 anwesend',
      'Finn Schulze, 1 von 2 anwesend',
      'Kai Meier, 0 von 0 anwesend',
    ]);
    expect(cards[1].querySelector('.gat__dot--ex')).toBeTruthy();
    expect(cards[1].querySelector('.gat__dot--dv')).toBeTruthy();
    cards[1].click();
    view.fixture.detectChanges();
    expect(view.api.memberAttendance).toHaveBeenCalledWith('g-1', 'p-1', '2026-09');
    expect(screen.getByRole('dialog', { name: 'Finn Schulze' })).toHaveTextContent(
      'Mitglied · 1 von 2 anwesend · Mai – Okt 2026',
    );
    expect(await runAxe(view.container)).toHaveNoViolations();
  });

  it('copes with a person without a role and a row shorter than the months', async () => {
    const data = attendance();
    const odd = attendance({
      rows: [
        {
          principalId: 'p-9',
          displayName: null,
          roleKey: null,
          roleName: null,
          isSelf: false,
          cells: [{ month: '2026-09', member: true, present: 1, excused: 0, delegated: 0 }, { month: '2026-11', member: true, present: 0, excused: 0, delegated: 0 }, { month: '2026-12', member: true, present: 0, excused: 0, delegated: 0 }],
        },
        { ...data.rows[0], cells: data.rows[0].cells.slice(0, 1) },
      ],
    });
    const view = await setup({ phone: true, api: gremienApiMock({ attendance: jest.fn(() => of(odd)) }) });
    restore = view.restore;
    expect(view.cmp.roleOptions()).toHaveLength(2);
    const rows = view.cmp.rows();
    expect(rows[1].name).toBe('—');
    expect(rows[1].role).toBe('');
    expect(rows[1].cells[2].view.kind).toBe('none');
    view.cmp.openPerson(rows[0], null);
    expect(view.api.memberAttendance).toHaveBeenCalledTimes(1);
  });

  it('reads no month for a person without a meeting in the range', async () => {
    const view = await setup({ phone: true });
    restore = view.restore;
    screen.getByRole('button', { name: 'Kai Meier, 0 von 0 anwesend' }).click();
    view.fixture.detectChanges();
    expect(view.api.memberAttendance).not.toHaveBeenCalled();
  });
});
