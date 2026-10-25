import { render, screen } from '@testing-library/angular';
import { of, throwError } from 'rxjs';
import { GremienApiService } from '@core/api/gremien.service';
import { downloadBlob, MEDIA } from '@stupa-makers/ui-kit';
import { runAxe } from '../../../../testing/a11y';
import { gremienApiMock, member } from '../../../../testing/gremien-fixtures';
import { matchMediaQueries } from '../../../../testing/meeting-fixtures';
import { GremiumMembersComponent } from './gremium-members.component';

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

const MEMBERS = [
  member({ principalId: 'p-1', displayName: 'Finn Schulze', email: 'finn.schulze@example.org' }),
  member({
    principalId: 'p-2',
    displayName: 'Anna Berg',
    email: 'anna.berg@a-very-long-domain-of-the-student-government.example.org',
    roleId: 'r-board',
    roleKey: 'vorstand',
    roleName: { de: 'Vorstand', en: 'Board' },
    validUntil: '2026-09-30T00:00:00Z',
    isSelf: true,
  }),
  member({ principalId: 'p-3', displayName: null, email: 'kai@example.org', validFrom: null }),
  member({
    principalId: 'p-4',
    displayName: 'Lea Wolf',
    email: null,
    roleId: 'r-kasse',
    roleKey: 'kasse',
    roleName: { de: 'Kasse', en: 'Treasury' },
  }),
];

async function setup(opts: { api?: ReturnType<typeof gremienApiMock>; phone?: boolean } = {}) {
  localStorage.setItem('ap.locale', 'de');
  const restore = matchMediaQueries(...(opts.phone ? [MEDIA.phone] : []));
  const api = opts.api ?? gremienApiMock({ members: jest.fn(() => of(MEMBERS)) });
  const view = await render(GremiumMembersComponent, {
    inputs: { gremiumId: 'g-1', gremiumName: 'Studierendenparlament' },
    providers: [{ provide: GremienApiService, useValue: api }],
  });
  return { ...view, api, restore, cmp: view.fixture.componentInstance };
}

describe('GremiumMembersComponent', () => {
  let restore: (() => void) | null = null;
  afterEach(() => {
    restore?.();
    restore = null;
    localStorage.clear();
    (downloadBlob as jest.Mock).mockClear();
  });

  it('groups the members by role and never cuts an address', async () => {
    const view = await setup();
    restore = view.restore;
    expect(view.api.members).toHaveBeenCalledWith('g-1', false);
    expect(view.cmp.groups().map((g) => g.key)).toEqual(['vorstand', 'kasse', 'member']);
    expect(view.cmp.groups()[2].rows.map((r) => r.name)).toEqual(['Finn Schulze', 'kai@example.org']);
    const mail = screen.getByText('anna.berg@a-very-long-domain-of-the-student-government.example.org');
    expect(mail.getAttribute('href')).toBe('mailto:anna.berg@a-very-long-domain-of-the-student-government.example.org');
    expect(screen.getByText('Du')).toBeTruthy();
    expect(screen.getByText('seit 01.10.2025 · bis 30.09.2026')).toBeTruthy();
    expect(view.cmp.searchPlaceholder()).toBe('4 Mitglieder durchsuchen');
    expect(await runAxe(view.container)).toHaveNoViolations();
  });

  it('filters by the search and the role', async () => {
    const view = await setup();
    restore = view.restore;
    view.cmp.query.set('ANNA');
    expect(view.cmp.groups().flatMap((g) => g.rows.map((r) => r.name))).toEqual(['Anna Berg']);
    view.cmp.query.set('kai@');
    expect(view.cmp.groups().flatMap((g) => g.rows.map((r) => r.name))).toEqual(['kai@example.org']);
    view.cmp.query.set('');
    view.cmp.role.set('kasse');
    expect(view.cmp.roleText()).toBe('Rolle: Kasse');
    expect(view.cmp.groups().map((g) => g.key)).toEqual(['kasse']);
    view.cmp.role.set('gone');
    expect(view.cmp.roleText()).toBe('Rolle: gone');
    view.fixture.detectChanges();
    expect(screen.getByText('Kein Mitglied passt zur Suche.')).toBeTruthy();
    view.cmp.role.set('');
    expect(view.cmp.roleText()).toBeNull();
  });

  it('reads the former members and says when there are none', async () => {
    const members = jest.fn((_id: string, former: boolean) => of(former ? [] : MEMBERS));
    const view = await setup({ api: gremienApiMock({ members }) });
    restore = view.restore;
    view.cmp.role.set('vorstand');
    view.cmp.setFormer('former');
    view.fixture.detectChanges();
    expect(members).toHaveBeenLastCalledWith('g-1', true);
    expect(view.cmp.role()).toBe('');
    expect(screen.getByText('Keine ehemaligen Mitglieder')).toBeTruthy();
    view.cmp.exportCsv();
    expect((downloadBlob as jest.Mock).mock.calls[0][1]).toBe('studierendenparlament-mitglieder-ehemalige.csv');
    view.cmp.setFormer('');
    view.fixture.detectChanges();
    expect(members).toHaveBeenLastCalledWith('g-1', false);
  });

  it('shows the empty state without members', async () => {
    const view = await setup({ api: gremienApiMock({ members: jest.fn(() => of([])) }) });
    restore = view.restore;
    expect(screen.getByText('Keine Mitglieder')).toBeTruthy();
  });

  it('exports the rows on screen as CSV', async () => {
    const view = await setup();
    restore = view.restore;
    screen.getByRole('button', { name: 'Als CSV exportieren' }).click();
    const [blob, name] = (downloadBlob as jest.Mock).mock.calls[0] as [Blob, string];
    expect(name).toBe('studierendenparlament-mitglieder.csv');
    const text = await readBlob(blob);
    expect(text).toContain('Name;E-Mail;Rolle;Seit;Bis');
    expect(text).toContain('Anna Berg;anna.berg@a-very-long-domain-of-the-student-government.example.org;Vorstand;01.10.2025;30.09.2026');
  });

  it('reports a failed read and reads again', async () => {
    const members = jest.fn((): ReturnType<GremienApiService['members']> => throwError(() => new Error('x')));
    const view = await setup({ api: gremienApiMock({ members }) });
    restore = view.restore;
    expect(screen.getByRole('alert')).toHaveTextContent('Die Mitglieder konnten nicht geladen werden.');
    members.mockReturnValue(of(MEMBERS));
    screen.getByRole('button', { name: 'Erneut versuchen' }).click();
    view.fixture.detectChanges();
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('hides the address and the export on a phone', async () => {
    const view = await setup({ phone: true });
    restore = view.restore;
    expect(screen.queryByText('finn.schulze@example.org')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Als CSV exportieren' })).toBeNull();
  });
});
