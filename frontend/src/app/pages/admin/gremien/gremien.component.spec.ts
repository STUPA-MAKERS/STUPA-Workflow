import { Router, provideRouter } from '@angular/router';
import { render, screen, waitFor, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { AuthService } from '@core/auth/auth.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { of, throwError } from 'rxjs';
import { AdminApiService } from '../admin-api.service';
import type { Gremium } from '../admin.models';
import { AdminGremienComponent } from './gremien.component';

const GREMIEN: Gremium[] = [
  {
    id: 'g-1',
    name: 'Studierendenparlament',
    slug: 'stupa',
    cdVariantId: 'cd-1',
    defaultLang: 'de',
    allowVoteDelegation: true,
    delegationLeadMinutes: 60,
    delegationAllowExternal: false,
    quorumPercent: 50,
    memberCount: 23,
    roleCount: 4,
    protocolsPublic: true,
  },
  {
    id: 'g-2',
    name: 'AStA',
    slug: 'asta',
    cdVariantId: null,
    defaultLang: 'en',
    allowVoteDelegation: false,
    quorumPercent: null,
    memberCount: 1,
    roleCount: 1,
  },
  {
    id: 'g-3',
    name: 'Ohne Zahlen',
    slug: 'oz',
    cdVariantId: 'cd-x',
    defaultLang: 'de',
    allowVoteDelegation: true,
    delegationLeadMinutes: 0,
    delegationAllowExternal: true,
  },
];

const clone = <T>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

function makeApi(over: Partial<Record<string, jest.Mock>> = {}) {
  return {
    listGremien: jest.fn(() => of(clone(GREMIEN))),
    listCdVariantOptions: jest.fn(() =>
      of([{ id: 'cd-1', key: 'stupa', name: 'StuPa-Protokoll' }]),
    ),
    getGremiumMailRecipients: jest.fn((id: string) =>
      of({
        recipients: id === 'g-1' ? ['protokolle@stupa.example', 'verteiler@lists.example'] : [],
      }),
    ),
    setGremiumMailRecipients: jest.fn((_id: string, recipients: string[]) => of({ recipients })),
    createGremium: jest.fn((b: Partial<Gremium>) => of({ id: 'g-new', ...b })),
    updateGremium: jest.fn((id: string, b: Partial<Gremium>) => of({ ...GREMIEN[0], id, ...b })),
    deleteGremium: jest.fn(() => of(void 0)),
    listGremiumRoles: jest.fn((gid: string) =>
      of([
        {
          id: `${gid}-v`,
          gremiumId: gid,
          key: 'vorstand',
          name: { de: 'Vorstand' },
          forced: true,
          permissions: ['session.manage'],
        },
      ]),
    ),
    listRoleMappings: jest.fn(() => of([])),
    listMembershipMappings: jest.fn(() => of([])),
    createGremiumRole: jest.fn((gid: string, b: object) =>
      of({ id: 'gr-new', gremiumId: gid, forced: false, ...b }),
    ),
    ...over,
  };
}

/** NgModel writes its value after a microtask. */
async function setup(opts: { api?: ReturnType<typeof makeApi>; perms?: string[] } = {}) {
  const api = opts.api ?? makeApi();
  const perms = opts.perms ?? ['admin.gremien', 'admin.gremium_roles', 'admin.group_mappings'];
  const toast = { success: jest.fn(), error: jest.fn() };
  const view = await render(AdminGremienComponent, {
    providers: [
      provideRouter([]),
      { provide: AdminApiService, useValue: api },
      { provide: ToastService, useValue: toast },
      { provide: AuthService, useValue: { can: (p: string) => perms.includes(p) } },
    ],
  });
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  return { ...view, api, toast };
}

const item = (name: string) =>
  screen.getByRole('button', { name: new RegExp(`^${name}`) }).closest('li') as HTMLElement;

/** Choose an item of the ⋮ menu of one gremium row. */
async function pick(name: string, label: string): Promise<void> {
  await userEvent.click(screen.getByRole('button', { name: `Weitere Aktionen: ${name}` }));
  await userEvent.click(await screen.findByRole('menuitem', { name: label }));
}

describe('AdminGremienComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  /** The row has no inline link or icons: the ⋮ menu holds edit, members and delete. */
  it('lists the gremien with slug and counts; the first row starts open', async () => {
    const { api } = await setup();
    const first = item('Studierendenparlament');
    expect(within(first).getByText('stupa')).toBeInTheDocument();
    expect(within(first).getByText('23 Mitglieder · 4 Rollen')).toBeInTheDocument();
    expect(within(item('AStA')).getByText('1 Mitglied · 1 Rolle')).toBeInTheDocument();
    expect(within(item('Ohne Zahlen')).queryByText(/Rolle/)).toBeNull();
    expect(within(first).queryByRole('link')).toBeNull();
    expect(within(first).getByRole('button', { name: 'Weitere Aktionen: Studierendenparlament' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^Studierendenparlament/ })).toHaveAttribute(
      'aria-expanded',
      'true',
    );
    expect(screen.getByRole('button', { name: /^AStA/ })).toHaveAttribute('aria-expanded', 'false');
    expect(api.listGremiumRoles).toHaveBeenCalledWith('g-1', { quiet: true });
    expect(api.listGremiumRoles).not.toHaveBeenCalledWith('g-2', expect.anything());
  });

  it('opens the members page from the ⋮ menu of a row', async () => {
    const { fixture } = await setup();
    const nav = jest.spyOn(fixture.debugElement.injector.get(Router), 'navigate').mockResolvedValue(true);
    await pick('AStA', 'Mitglieder');
    expect(nav).toHaveBeenCalledWith(['/admin/gremien', 'g-2', 'members']);
  });

  it('tags a gremium that publishes its protocols and names the setting', async () => {
    await setup();
    expect(
      within(item('Studierendenparlament')).getByText('Öffentlich', { selector: 'app-status-text' }),
    ).toBeInTheDocument();
    expect(within(item('AStA')).queryByText('Öffentlich', { selector: 'app-status-text' })).toBeNull();
    const first = item('Studierendenparlament');
    const dt = within(first).getByText('Öffentlich', { selector: 'dt' });
    expect(dt.nextElementSibling).toHaveTextContent('Ja');
  });

  it('shows every setting of an open row; the recipients wrap in full', async () => {
    await setup();
    const first = item('Studierendenparlament');
    const value = (label: string) =>
      within(first).getByText(label).nextElementSibling?.textContent?.trim();
    expect(value('CD-Variante')).toBe('StuPa-Protokoll');
    expect(value('Standardsprache')).toBe('Deutsch');
    expect(value('Quorum')).toBe('50 %');
    expect(value('Stimm-Delegation erlauben')).toBe('Ja');
    expect(value('Vorlauf für Delegationen')).toBe('60 Minuten');
    expect(value('Delegation an Externe erlauben')).toBe('Nein');
    expect(value('Zusätzliche Protokoll-Empfänger')).toBe(
      'protokolle@stupa.example, verteiler@lists.example',
    );
    expect(within(first).queryByText(/Stimme nach Abgabe/)).toBeNull();
    expect(
      within(first).getByRole('heading', { name: 'Gremienrollen und Berechtigungen' }),
    ).toBeInTheDocument();
  });

  /** Opening again reads the recipients only once. */
  it('opens and closes a row with its name and with the chevron', async () => {
    const { api } = await setup();
    await userEvent.click(screen.getByRole('button', { name: /^AStA/ }));
    const asta = item('AStA');
    const value = (label: string) =>
      within(asta).getByText(label).nextElementSibling?.textContent?.trim();
    expect(value('CD-Variante')).toBe('Standard des PDF-Renderers');
    expect(value('Standardsprache')).toBe('Englisch');
    expect(value('Quorum')).toBe('Kein Quorum');
    expect(within(asta).queryByText('Vorlauf für Delegationen')).toBeNull();
    expect(value('Zusätzliche Protokoll-Empfänger')).toBe('Keine');
    await userEvent.click(screen.getByRole('button', { name: 'Zuklappen: AStA' }));
    expect(screen.getByRole('button', { name: /^AStA/ })).toHaveAttribute('aria-expanded', 'false');
    await userEvent.click(screen.getByRole('button', { name: 'Aufklappen: AStA' }));
    expect(api.getGremiumMailRecipients.mock.calls.filter(([id]) => id === 'g-2')).toHaveLength(1);
  });

  it('names "until the start" for a lead time of 0 and a failed recipient read', async () => {
    const api = makeApi({
      getGremiumMailRecipients: jest.fn(() => throwError(() => ({ status: 500 }))),
    });
    await setup({ api });
    await userEvent.click(screen.getByRole('button', { name: /^Ohne Zahlen/ }));
    const oz = item('Ohne Zahlen');
    const value = (label: string) =>
      within(oz).getByText(label).nextElementSibling?.textContent?.trim();
    expect(value('Vorlauf für Delegationen')).toBe('Bis Sitzungsbeginn');
    expect(value('Delegation an Externe erlauben')).toBe('Ja');
    expect(value('CD-Variante')).toBe('Standard des PDF-Renderers');
    expect(value('Zusätzliche Protokoll-Empfänger')).toBe(
      'Die Protokoll-Empfänger konnten nicht geladen werden.',
    );
  });

  it('edits a gremium in the dialog and reloads the list', async () => {
    const { api, toast } = await setup();
    await pick('Studierendenparlament', 'Bearbeiten');
    const dialog = screen.getByRole('dialog', { name: 'Gremium bearbeiten' });
    await waitFor(() =>
      expect(within(dialog).getByRole('textbox', { name: /Name/ })).toHaveValue(
        'Studierendenparlament',
      ),
    );
    await userEvent.click(within(dialog).getByText('Speichern'));
    expect(api.updateGremium).toHaveBeenCalled();
    expect(toast.success).toHaveBeenCalledWith('Gremium gespeichert.');
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(api.listGremien).toHaveBeenCalledTimes(2);
  });

  it('creates a gremium and opens its row', async () => {
    const api = makeApi();
    const { toast } = await setup({ api });
    await userEvent.click(screen.getByRole('button', { name: /Gremium anlegen/ }));
    const dialog = screen.getByRole('dialog', { name: 'Gremium anlegen' });
    await userEvent.type(within(dialog).getByRole('textbox', { name: /Name/ }), 'Neu');
    api.listGremien.mockReturnValue(
      of([...clone(GREMIEN), { ...clone(GREMIEN[1]), id: 'g-new', name: 'Neu', slug: 'neu' }]),
    );
    await userEvent.click(within(dialog).getByText('Anlegen'));
    expect(toast.success).toHaveBeenCalledWith('Gremium angelegt.');
    expect(screen.getByRole('button', { name: /^Neu/ })).toHaveAttribute('aria-expanded', 'true');
  });

  it('shows a new gremium after its recipients failed and the dialog was cancelled', async () => {
    const api = makeApi({
      setGremiumMailRecipients: jest.fn(() => throwError(() => ({ status: 422 }))),
    });
    const { toast } = await setup({ api });
    await userEvent.click(screen.getByRole('button', { name: /Gremium anlegen/ }));
    const dialog = screen.getByRole('dialog', { name: 'Gremium anlegen' });
    await userEvent.type(within(dialog).getByRole('textbox', { name: /Name/ }), 'Neu');
    api.listGremien.mockReturnValue(
      of([...clone(GREMIEN), { ...clone(GREMIEN[1]), id: 'g-new', name: 'Neu', slug: 'neu' }]),
    );
    await userEvent.click(within(dialog).getByText('Anlegen'));
    expect(within(dialog).getByRole('alert')).toHaveTextContent(
      /eine Empfänger-Adresse ist ungültig/,
    );
    await userEvent.click(within(dialog).getByText('Abbrechen'));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(toast.success).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: /^Neu/ })).toHaveAttribute('aria-expanded', 'true');
    expect(api.getGremiumMailRecipients).toHaveBeenCalledWith('g-new');
  });

  it('shows the edited values after the recipients failed and the dialog was cancelled', async () => {
    const api = makeApi({
      setGremiumMailRecipients: jest.fn(() => throwError(() => ({ status: 422 }))),
    });
    await setup({ api });
    await pick('AStA', 'Bearbeiten');
    const dialog = screen.getByRole('dialog', { name: 'Gremium bearbeiten' });
    const name = within(dialog).getByRole('textbox', { name: /Name/ });
    await waitFor(() => expect(name).toHaveValue('AStA'));
    await userEvent.clear(name);
    await userEvent.type(name, 'AStA neu');
    api.listGremien.mockReturnValue(
      of(clone(GREMIEN).map((g) => (g.id === 'g-2' ? { ...g, name: 'AStA neu' } : g))),
    );
    await userEvent.click(within(dialog).getByText('Speichern'));
    expect(api.updateGremium).toHaveBeenCalledWith(
      'g-2',
      expect.objectContaining({ name: 'AStA neu' }),
    );
    await userEvent.click(within(dialog).getByText('Abbrechen'));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.getByRole('button', { name: /^AStA neu/ })).toBeInTheDocument();
    expect(api.listGremien).toHaveBeenCalledTimes(2);
  });

  it('keeps the shown recipients when the dialog did not save them', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    const before = c.recipients().get('g-1');
    expect(before).toEqual(['protokolle@stupa.example', 'verteiler@lists.example']);
    c.onSaved({ gremium: GREMIEN[0], created: false, recipients: null });
    expect(c.recipients().get('g-1')).toEqual(before);
  });

  it('closes the dialog on cancel', async () => {
    await setup();
    await userEvent.click(screen.getByRole('button', { name: /Gremium anlegen/ }));
    await userEvent.click(within(screen.getByRole('dialog')).getByText('Abbrechen'));
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('deletes a gremium after the confirmation', async () => {
    const api = makeApi();
    const { toast } = await setup({ api });
    await pick('AStA', 'Löschen');
    const dialog = screen.getByRole('dialog', { name: 'Gremium löschen?' });
    expect(dialog).toHaveTextContent('„AStA“');
    await userEvent.click(within(dialog).getByText('Löschen'));
    expect(api.deleteGremium).toHaveBeenCalledWith('g-2');
    expect(toast.success).toHaveBeenCalledWith('Gremium gelöscht.');
  });

  it.each([
    [
      { status: 409, error: { code: 'open_vote' } },
      'Eine Abstimmung des Gremiums ist noch offen. Schließe sie oder brich sie zuerst ab.',
    ],
    [
      { status: 403, error: { code: 'meeting_finalized' } },
      'Eine Sitzung des Gremiums hat ein finales Protokoll. Zum Löschen fehlt dir das Recht „meeting.delete_finalized“.',
    ],
  ])('names the reason of a refused delete (%o)', async (err, message) => {
    const api = makeApi({ deleteGremium: jest.fn(() => throwError(() => err)) });
    const { toast } = await setup({ api });
    await pick('AStA', 'Löschen');
    await userEvent.click(within(screen.getByRole('dialog')).getByText('Löschen'));
    expect(toast.error).toHaveBeenCalledWith(message);
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('keeps the generic message for another 403', async () => {
    const api = makeApi({
      deleteGremium: jest.fn(() =>
        throwError(() => ({ status: 403, error: { code: 'forbidden' } })),
      ),
    });
    const { toast } = await setup({ api });
    await pick('AStA', 'Löschen');
    await userEvent.click(within(screen.getByRole('dialog')).getByText('Löschen'));
    expect(toast.error).toHaveBeenCalledWith('Das Gremium konnte nicht gelöscht werden.');
  });

  it('names a failed delete and keeps the dialog', async () => {
    const api = makeApi({ deleteGremium: jest.fn(() => throwError(() => ({ status: 500 }))) });
    const { toast } = await setup({ api });
    await pick('AStA', 'Löschen');
    await userEvent.click(within(screen.getByRole('dialog')).getByText('Löschen'));
    expect(toast.error).toHaveBeenCalledWith('Das Gremium konnte nicht gelöscht werden.');
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    await userEvent.click(within(screen.getByRole('dialog')).getByText('Abbrechen'));
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('updates the role count of a row after a role change', async () => {
    const api = makeApi();
    await setup({ api });
    const first = item('Studierendenparlament');
    await userEvent.click(within(first).getByRole('button', { name: /Gremium-Rolle anlegen/ }));
    const dialog = screen.getByRole('dialog', { name: /Gremium-Rolle anlegen/ });
    await userEvent.type(within(dialog).getByRole('textbox', { name: /Schlüssel/ }), 'kasse');
    await userEvent.click(within(dialog).getByText('Speichern'));
    expect(api.createGremiumRole).toHaveBeenCalledWith(
      'g-1',
      expect.objectContaining({ key: 'kasse' }),
    );
    expect(within(first).getByText('23 Mitglieder · 2 Rollen')).toBeInTheDocument();
  });

  it('links to the group mappings only with that permission', async () => {
    await setup();
    expect(screen.getByRole('link', { name: 'Gruppen-Zuordnung' })).toHaveAttribute(
      'href',
      '/admin/group-mappings',
    );
  });

  it('links to the group mappings only with that permission (2)', async () => {
    await setup({ perms: ['admin.gremien'] });
    expect(screen.queryByRole('link', { name: 'Gruppen-Zuordnung' })).toBeNull();
  });

  it('names a failed load and an empty list', async () => {
    await setup({
      api: makeApi({ listGremien: jest.fn(() => throwError(() => ({ status: 500 }))) }),
    });
    expect(screen.getByRole('alert')).toHaveTextContent('Gremien konnten nicht geladen werden.');
  });

  it('names a failed load and an empty list (2)', async () => {
    await setup({
      api: makeApi({
        listGremien: jest.fn(() => of([])),
        listCdVariantOptions: jest.fn(() => throwError(() => ({ status: 403 }))),
      }),
    });
    expect(screen.getByText('Noch keine Gremien angelegt.')).toBeInTheDocument();
  });

  it('shows an ellipsis while the recipients load and guards the delete', async () => {
    const api = makeApi({ getGremiumMailRecipients: jest.fn(() => of({ recipients: [] })) });
    const { fixture } = await setup({ api });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    const fresh = { ...GREMIEN[1], id: 'g-fresh' };
    const last = c.settings(fresh).at(-1);
    expect(last.value).toBe('…');
    c.doDelete();
    c.confirmDelete.set(GREMIEN[1]);
    c.deleting.set(true);
    c.doDelete();
    expect(api.deleteGremium).not.toHaveBeenCalled();
  });
});
