import { of, throwError } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { ToastService } from '@stupa-makers/ui-kit';
import { AdminApiService } from '../../admin-api.service';
import type { AdminPrincipal, RevokePreview, RevokeResult } from '../../admin.models';
import { UserRevokeComponent } from './user-revoke.component';

const PERSON: AdminPrincipal = {
  id: 'p-12',
  sub: 'kc|tobias',
  email: 'tobias@x.de',
  displayName: 'Tobias Kern',
  lastLogin: '2026-02-12T09:00:00+00:00',
  assignments: [],
  oidcGroups: ['stupa-mitglieder', 'gremien-alle'],
  hasAccess: true,
};

function preview(over: Partial<RevokePreview> = {}): RevokePreview {
  return {
    principal: { id: 'p-12', displayName: 'Tobias Kern', email: 'tobias@x.de', lastLogin: PERSON.lastLogin ?? null, active: true },
    gremien: [
      {
        gremiumId: 'g-stupa',
        name: 'StuPa',
        membership: { roleKey: 'mitglied', roleLabel: { de: 'Mitglied' }, groups: ['stupa-mitglieder'] },
        groups: ['stupa-mitglieder', 'gremien-alle', 'stupa-sitzung'],
        assignments: [
          {
            id: 'a-1',
            roleId: 'r-sl',
            roleKey: 'sitzungsleitung',
            roleLabel: { de: 'Sitzungsleitung' },
            grantedBy: 'Alex Admin',
            validFrom: null,
            validUntil: null,
          },
        ],
        poolEntries: [
          { id: 'ds-1', asSubstitute: true, gremiumWide: false, memberName: 'Mia', substituteName: 'Tobias Kern' },
          { id: 'ds-2', asSubstitute: true, gremiumWide: true, memberName: null, substituteName: 'Tobias Kern' },
          { id: 'ds-3', asSubstitute: false, gremiumWide: false, memberName: 'Tobias Kern', substituteName: null },
        ],
        plannedDelegations: [
          {
            id: 'md-1',
            meetingId: 'm-1',
            meetingTitle: '5. Sitzung',
            meetingDate: null,
            asDelegator: true,
            otherName: 'Mia',
            voting: true,
          },
        ],
        liveDelegations: [
          {
            id: 'md-2',
            meetingId: 'm-2',
            meetingTitle: '4. Sitzung',
            meetingDate: null,
            asDelegator: false,
            otherName: null,
            voting: true,
          },
        ],
        openTasks: 2,
      },
      {
        gremiumId: 'g-asta',
        name: 'AStA',
        membership: null,
        groups: ['gremien-alle'],
        assignments: [
          {
            id: 'a-2',
            roleId: 'r-v',
            roleKey: 'vorstand',
            roleLabel: { en: 'board' },
            grantedBy: 'bootstrap',
            validFrom: null,
            validUntil: null,
          },
        ],
        poolEntries: [],
        plannedDelegations: [],
        liveDelegations: [],
        openTasks: 1,
      },
    ],
    globalRoles: [
      { roleId: 'r-ref', roleKey: 'referent', roleLabel: { de: 'Referent' }, groups: ['stupa-referate'], assignments: [] },
      {
        roleId: 'r-x',
        roleKey: 'extra',
        roleLabel: {},
        groups: [],
        assignments: [
          {
            id: 'a-3',
            roleId: 'r-x',
            roleKey: 'extra',
            roleLabel: {},
            grantedBy: null,
            validFrom: '2026-01-05T00:00:00+00:00',
            validUntil: null,
          },
        ],
      },
    ],
    groups: [
      { group: 'stupa-mitglieder', gremiumIds: ['g-stupa'], globalRoleIds: [] },
      { group: 'gremien-alle', gremiumIds: ['g-stupa', 'g-asta'], globalRoleIds: [] },
      { group: 'stupa-referate', gremiumIds: [], globalRoleIds: ['r-ref'] },
    ],
    isSelf: false,
    ...over,
  };
}

const RESULT: RevokeResult = {
  gremiumIds: ['g-stupa', 'g-asta'],
  globalRoleIds: ['r-ref', 'r-x'],
  removedGroups: ['stupa-mitglieder'],
  deletedAssignments: 1,
  deletedPoolEntries: 2,
  revokedDelegations: 1,
  keptLiveDelegations: 1,
  deactivated: false,
};

function makeApi(over: Partial<Record<string, jest.Mock>> = {}) {
  return {
    previewPrincipalRevoke: jest.fn(() => of(preview())),
    revokePrincipal: jest.fn(() => of(RESULT)),
    ...over,
  };
}

async function setup(api = makeApi(), source: AdminPrincipal | null = PERSON) {
  const toast = { success: jest.fn(), error: jest.fn() };
  const closed = jest.fn();
  const revoked = jest.fn();
  const view = await render(UserRevokeComponent, {
    inputs: { source },
    on: { closed, revoked },
    providers: [
      { provide: AdminApiService, useValue: api },
      { provide: ToastService, useValue: toast },
    ],
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const inst = view.fixture.componentInstance as any;
  // `ngModel` writes its value and its disabled state one microtask later.
  const settle = async () => {
    await view.fixture.whenStable();
    view.fixture.detectChanges();
  };
  await settle();
  return { ...view, api, toast, closed, revoked, inst, settle };
}

describe('UserRevokeComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('renders nothing while no person is chosen', async () => {
    const { api } = await setup(makeApi(), null);
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(api.previewPrincipalRevoke).not.toHaveBeenCalled();
  });

  it('shows the person, the Gremien with their ties and the global roles', async () => {
    const { api } = await setup();
    expect(api.previewPrincipalRevoke).toHaveBeenCalledWith('p-12');
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getAllByText('Tobias Kern').length).toBeGreaterThan(0);
    expect(screen.getByText(/^Letzter Login .+ \(vor \d+ Monaten\)$/)).toBeInTheDocument();
    expect(screen.getByText('Gremien (2)')).toBeInTheDocument();
    expect(screen.getByText('Globale Rollen (2)')).toBeInTheDocument();
    expect(screen.getByText('Mitgliedschaft als Mitglied')).toBeInTheDocument();
    expect(screen.getByText('über die SSO-Gruppe stupa-mitglieder')).toBeInTheDocument();
    expect(screen.getByText('SSO-Gruppen gremien-alle, stupa-sitzung')).toBeInTheDocument();
    expect(screen.getByText('Rolle Sitzungsleitung, direkt vergeben')).toBeInTheDocument();
    expect(screen.getByText('vergeben von Alex Admin')).toBeInTheDocument();
    expect(screen.getByText('Vertretung für Mia')).toBeInTheDocument();
    expect(screen.getByText('Vertretung für das ganze Gremium')).toBeInTheDocument();
    expect(screen.getByText('Vertretung durch Konto ohne Namen')).toBeInTheDocument();
    expect(screen.getByText('Stimme an Mia in 5. Sitzung')).toBeInTheDocument();
    expect(screen.getByText('Stimme von Konto ohne Namen in der laufenden Sitzung 4. Sitzung')).toBeInTheDocument();
    expect(screen.getByText('Bleibt bis zum Ende der Sitzung bestehen.')).toBeInTheDocument();
    expect(screen.getByText('2 offene Abstimmungen')).toBeInTheDocument();
    expect(screen.getByText('1 offene Abstimmung')).toBeInTheDocument();
    // A role without a German label falls back to its key; bootstrap has its own text.
    expect(screen.getByText('Rolle vorstand, direkt vergeben')).toBeInTheDocument();
    expect(screen.getByText('beim Einrichten der Plattform vergeben')).toBeInTheDocument();
    expect(screen.getByText(/^vergeben von — am /)).toBeInTheDocument();
    expect(screen.getByText('über die SSO-Gruppe stupa-referate')).toBeInTheDocument();
    // The shared group ties StuPa and AStA together.
    expect(
      screen.getByText('Die SSO-Gruppe gremien-alle gilt auch für AStA. Beides wird zusammen entzogen.'),
    ).toBeInTheDocument();
    // The note names the effects and, without deactivation, the next login.
    expect(screen.getByText(/Sofort wirksam: Tobias Kern gehört keinem/)).toHaveTextContent(
      'kommen nur die Gremien und Rollen zurück',
    );
  });

  it('with the deactivation the note names the lost login, not the next one', async () => {
    await setup();
    await userEvent.click(screen.getByRole('switch', { name: /Konto zusätzlich deaktivieren/ }));
    const note = screen.getByText(/Sofort wirksam: Tobias Kern gehört keinem/);
    expect(note).toHaveTextContent('Das Konto ist danach deaktiviert');
    expect(note).not.toHaveTextContent('Meldet sich');
  });

  it('warns that the admin role of a bootstrap admin comes back', async () => {
    const base = preview();
    const role = base.globalRoles[1];
    const api = makeApi({
      previewPrincipalRevoke: jest.fn(() =>
        of(
          preview({
            globalRoles: [
              base.globalRoles[0],
              {
                ...role,
                assignments: [{ ...role.assignments[0], grantedBy: 'bootstrap', returnsAutomatically: true }],
              },
            ],
          }),
        ),
      ),
    });
    await setup(api);
    expect(screen.getByText(/Kommt beim nächsten Start oder Login zurück/)).toBeInTheDocument();
  });

  it('starts with everything checked and names the count on the danger button', async () => {
    const { settle } = await setup();
    expect(screen.getByLabelText('StuPa')).toBeChecked();
    expect(screen.getByRole('button', { name: '2 Gremien und 2 Rollen entziehen' })).toBeEnabled();
    await userEvent.click(screen.getByLabelText('AStA'));
    await settle();
    // AStA shares a group with StuPa: both go off together.
    expect(screen.getByLabelText('StuPa')).not.toBeChecked();
    expect(screen.getByRole('button', { name: '2 Rollen entziehen' })).toBeEnabled();
    await userEvent.click(screen.getByLabelText('Referent'));
    expect(screen.getByRole('button', { name: '1 Rolle entziehen' })).toBeEnabled();
    await userEvent.click(screen.getByLabelText('StuPa'));
    await settle();
    expect(screen.getByLabelText('AStA')).toBeChecked();
    expect(screen.getByRole('button', { name: '2 Gremien und 1 Rolle entziehen' })).toBeEnabled();
  });

  it('"Keine auswählen" clears the selection; the switch alone deactivates', async () => {
    await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Keine auswählen' }));
    expect(screen.getByRole('button', { name: 'Nichts ausgewählt' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: 'Alle auswählen' }));
    await userEvent.click(screen.getByRole('button', { name: 'Keine auswählen' }));
    await userEvent.click(screen.getByRole('switch', { name: /Konto zusätzlich deaktivieren/ }));
    expect(screen.getByRole('button', { name: 'Konto deaktivieren' })).toBeEnabled();
  });

  it('sends the selection, reports and closes', async () => {
    const { api, revoked, closed, toast } = await setup();
    await userEvent.click(screen.getByLabelText('Referent'));
    await userEvent.click(screen.getByRole('switch', { name: /Konto zusätzlich deaktivieren/ }));
    await userEvent.click(screen.getByRole('button', { name: '2 Gremien und 1 Rolle entziehen' }));
    expect(api.revokePrincipal).toHaveBeenCalledWith('p-12', {
      gremiumIds: ['g-stupa', 'g-asta'],
      globalRoleIds: ['r-x'],
      deactivate: true,
    });
    expect(toast.success).toHaveBeenCalledWith('Rechte entzogen.');
    expect(revoked).toHaveBeenCalledWith(RESULT);
    expect(closed).toHaveBeenCalled();
  });

  it('a stale selection loads the preview again; other errors keep it', async () => {
    const api = makeApi({
      revokePrincipal: jest.fn(() => throwError(() => ({ error: { code: 'revoke_incomplete' } }))),
    });
    const { toast, inst, settle } = await setup(api);
    // The admin narrows the choice: only the role Referent goes.
    await userEvent.click(screen.getByRole('button', { name: 'Keine auswählen' }));
    await userEvent.click(screen.getByLabelText('Referent'));
    await settle();
    inst.submit();
    expect(api.previewPrincipalRevoke).toHaveBeenCalledTimes(2);
    await settle();
    // The reload keeps the narrowed choice and does not check everything again.
    expect(screen.getByLabelText('Referent')).toBeChecked();
    expect(screen.getByLabelText('StuPa')).not.toBeChecked();
    expect(toast.error).toHaveBeenCalledWith(
      'Eine SSO-Gruppe gilt auch für etwas, das nicht ausgewählt war. Die Auswahl wurde neu geladen.',
    );
    api.revokePrincipal.mockReturnValue(throwError(() => ({ error: { code: 'revoke_own_account' } })));
    inst.submit();
    expect(api.previewPrincipalRevoke).toHaveBeenCalledTimes(2);
    expect(toast.error).toHaveBeenLastCalledWith('Deine eigenen Rechte kannst du nicht entziehen.');
    api.revokePrincipal.mockReturnValue(throwError(() => new Error('down')));
    inst.submit();
    expect(toast.error).toHaveBeenLastCalledWith('Die Rechte konnten nicht entzogen werden.');
  });

  it('the own account shows the note and blocks every control', async () => {
    await setup(makeApi({ previewPrincipalRevoke: jest.fn(() => of(preview({ isSelf: true }))) }));
    expect(
      screen.getByText('Das ist dein eigenes Konto. Deine eigenen Rechte kannst du nicht entziehen.'),
    ).toBeInTheDocument();
    expect(screen.getByLabelText('StuPa')).toBeDisabled();
    expect(screen.queryByRole('switch')).toBeNull();
    expect(screen.getByRole('button', { name: '2 Gremien und 2 Rollen entziehen' })).toBeDisabled();
  });

  it('a person without ties shows "nothing"; a never-logged-in person says so', async () => {
    const empty = preview({
      gremien: [],
      globalRoles: [],
      groups: [],
      principal: { id: 'p-12', displayName: null, email: null, lastLogin: null, active: true },
    });
    await setup(makeApi({ previewPrincipalRevoke: jest.fn(() => of(empty)) }));
    expect(screen.getByText('Diese Person hat keine Gremien und keine globalen Rollen.')).toBeInTheDocument();
    expect(screen.getByText('Noch nie angemeldet')).toBeInTheDocument();
    expect(screen.queryByText(/behält das Konto/)).toBeNull();
  });

  it('a failed preview offers a retry', async () => {
    const api = makeApi({ previewPrincipalRevoke: jest.fn(() => throwError(() => new Error('x'))) });
    await setup(api);
    expect(screen.getByText('Die Rechte der Person konnten nicht geladen werden.')).toBeInTheDocument();
    api.previewPrincipalRevoke.mockReturnValue(of(preview()));
    await userEvent.click(screen.getByRole('button', { name: 'Erneut versuchen' }));
    expect(screen.getByText('Gremien (2)')).toBeInTheDocument();
  });

  it('age() counts days and months', async () => {
    const { inst } = await setup();
    const now = Date.parse('2026-10-09T12:00:00Z');
    expect(inst.age('2026-10-09T08:00:00Z', now)).toBe('heute');
    expect(inst.age('2026-10-08T08:00:00Z', now)).toBe('vor 1 Tag');
    expect(inst.age('2026-09-29T08:00:00Z', now)).toBe('vor 10 Tagen');
    expect(inst.age('2026-02-12T08:00:00Z', now)).toBe('vor 7 Monaten');
  });

  it('"Abbrechen" closes the dialog', async () => {
    const { closed } = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Abbrechen' }));
    expect(closed).toHaveBeenCalled();
  });
});
