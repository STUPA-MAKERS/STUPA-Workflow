import { render, screen, waitFor, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { of, throwError } from 'rxjs';
import { AdminApiService } from '../../admin-api.service';
import type { CdVariantOption, Gremium } from '../../admin.models';
import { GremiumDialogComponent, parseRecipients } from './gremium-dialog.component';

const CD: CdVariantOption[] = [
  { id: 'cd-1', key: 'stupa', name: 'StuPa-Protokoll' },
  { id: 'cd-2', key: 'asta', name: 'AStA' },
];
const STUPA: Gremium = {
  id: 'g-1',
  name: 'Studierendenparlament',
  slug: 'studierendenparlament',
  cdVariantId: 'cd-1',
  defaultLang: 'de',
  allowVoteDelegation: true,
  delegationLeadMinutes: 60,
  delegationAllowExternal: false,
  quorumPercent: 50,
};

function makeApi(over: Partial<Record<string, jest.Mock>> = {}) {
  return {
    getGremiumMailRecipients: jest.fn(() =>
      of({ recipients: ['protokolle@stupa.example', 'verteiler@lists.example'] }),
    ),
    setGremiumMailRecipients: jest.fn((_id: string, recipients: string[]) => of({ recipients })),
    createGremium: jest.fn((b: Partial<Gremium>) => of({ id: 'g-new', ...b })),
    updateGremium: jest.fn((id: string, b: Partial<Gremium>) => of({ ...STUPA, id, ...b })),
    ...over,
  };
}

async function setup(gremium: Gremium | null, api = makeApi()) {
  const view = await render(GremiumDialogComponent, {
    providers: [{ provide: AdminApiService, useValue: api }],
    componentInputs: { open: true, gremium, cdVariants: CD },
  });
  // NgModel writes its value after a microtask.
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  const saved = jest.fn();
  const closed = jest.fn();
  view.fixture.componentInstance.saved.subscribe(saved);
  view.fixture.componentInstance.closed.subscribe(closed);
  return { ...view, api, saved, closed };
}

const dialog = () => screen.getByRole('dialog');
const save = () =>
  within(dialog())
    .getByText(/^(Speichern|Anlegen)$/)
    .closest('button') as HTMLButtonElement;

describe('GremiumDialogComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('loads every setting of the gremium, the recipients included', async () => {
    const { api } = await setup(STUPA);
    expect(screen.getByRole('heading', { name: 'Gremium bearbeiten' })).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: /Name/ })).toHaveValue('Studierendenparlament');
    // The slug of a stored gremium never changes, so the dialog shows the stored one.
    expect(screen.getByText('studierendenparlament')).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'CD-Variante' })).toHaveValue('cd-1');
    expect(screen.getByRole('combobox', { name: 'Standardsprache' })).toHaveValue('de');
    expect(screen.getByRole('spinbutton', { name: 'Quorum (%)' })).toHaveValue(50);
    expect(screen.getByRole('switch', { name: 'Stimm-Delegation erlauben' })).toHaveAttribute(
      'aria-checked',
      'true',
    );
    expect(
      screen.getByRole('spinbutton', { name: 'Vorlauf für Delegationen (Minuten)' }),
    ).toHaveValue(60);
    expect(screen.getByRole('switch', { name: 'Delegation an Externe erlauben' })).toHaveAttribute(
      'aria-checked',
      'false',
    );
    expect(screen.getByRole('textbox', { name: 'Zusätzliche Protokoll-Empfänger' })).toHaveValue(
      'protokolle@stupa.example\nverteiler@lists.example',
    );
    expect(api.getGremiumMailRecipients).toHaveBeenCalledWith('g-1');
  });

  it('has no switch to change a ballot after casting (O11)', async () => {
    await setup(STUPA);
    expect(screen.queryByText(/Stimme nach Abgabe/)).toBeNull();
    expect(screen.getAllByRole('switch')).toHaveLength(2);
  });

  it('saves every setting and then the recipients', async () => {
    const { api, saved } = await setup(STUPA);
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'CD-Variante' }), 'cd-2');
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Standardsprache' }), 'en');
    const quorum = screen.getByRole('spinbutton', { name: 'Quorum (%)' });
    await userEvent.clear(quorum);
    await userEvent.type(quorum, '150');
    const lead = screen.getByRole('spinbutton', { name: 'Vorlauf für Delegationen (Minuten)' });
    await userEvent.clear(lead);
    await userEvent.type(lead, '30');
    await userEvent.click(screen.getByRole('switch', { name: 'Delegation an Externe erlauben' }));
    const mail = screen.getByRole('textbox', { name: 'Zusätzliche Protokoll-Empfänger' });
    await userEvent.clear(mail);
    await userEvent.type(mail, 'a@x.de, b@x.de;{enter}c@x.de');
    await userEvent.click(save());
    expect(api.updateGremium).toHaveBeenCalledWith('g-1', {
      name: 'Studierendenparlament',
      cdVariantId: 'cd-2',
      defaultLang: 'en',
      allowVoteDelegation: true,
      delegationLeadMinutes: 30,
      delegationAllowExternal: true,
      // The quorum is a percent: 150 becomes 100.
      quorumPercent: 100,
    });
    expect(api.setGremiumMailRecipients).toHaveBeenCalledWith('g-1', [
      'a@x.de',
      'b@x.de',
      'c@x.de',
    ]);
    expect(saved).toHaveBeenCalledWith(
      expect.objectContaining({ created: false, recipients: ['a@x.de', 'b@x.de', 'c@x.de'] }),
    );
  });

  it('creates a gremium with a slug from the name; the delegation fields follow the switch', async () => {
    const { api, saved } = await setup(null);
    expect(screen.getByRole('heading', { name: 'Gremium anlegen' })).toBeInTheDocument();
    expect(save()).toBeDisabled();
    expect(screen.queryByRole('spinbutton', { name: /Vorlauf/ })).toBeNull();
    await userEvent.type(screen.getByRole('textbox', { name: /Name/ }), 'Finanz Ausschuss');
    expect(screen.getByText('finanz-ausschuss')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('switch', { name: 'Stimm-Delegation erlauben' }));
    await waitFor(() => expect(screen.getByRole('spinbutton', { name: /Vorlauf/ })).toHaveValue(0));
    await userEvent.type(screen.getByRole('spinbutton', { name: 'Quorum (%)' }), '40');
    await userEvent.click(save());
    expect(api.createGremium).toHaveBeenCalledWith({
      name: 'Finanz Ausschuss',
      slug: 'finanz-ausschuss',
      cdVariantId: null,
      defaultLang: 'de',
      allowVoteDelegation: true,
      delegationLeadMinutes: 0,
      delegationAllowExternal: false,
      quorumPercent: 40,
    });
    expect(api.setGremiumMailRecipients).toHaveBeenCalledWith('g-new', []);
    expect(saved).toHaveBeenCalledWith(expect.objectContaining({ created: true }));
  });

  it('names a taken slug', async () => {
    const api = makeApi({ createGremium: jest.fn(() => throwError(() => ({ status: 409 }))) });
    await setup(null, api);
    await userEvent.type(screen.getByRole('textbox', { name: /Name/ }), 'AStA');
    await userEvent.click(save());
    expect(within(dialog()).getByRole('alert')).toHaveTextContent(
      'Ein Gremium mit diesem Kürzel gibt es schon.',
    );
  });

  it('changes the new gremium on a second save after the recipients failed', async () => {
    const api = makeApi({
      setGremiumMailRecipients: jest
        .fn()
        .mockReturnValueOnce(throwError(() => ({ status: 422 })))
        .mockReturnValueOnce(throwError(() => ({ status: 500 })))
        .mockReturnValue(of({ recipients: ['ok@x.de'] })),
    });
    const { saved } = await setup(null, api);
    await userEvent.type(screen.getByRole('textbox', { name: /Name/ }), 'Neu');
    await userEvent.click(save());
    expect(within(dialog()).getByRole('alert')).toHaveTextContent(
      /eine Empfänger-Adresse ist ungültig/,
    );
    await userEvent.click(save());
    expect(within(dialog()).getByRole('alert')).toHaveTextContent(/die Protokoll-Empfänger nicht/);
    await userEvent.click(save());
    expect(api.createGremium).toHaveBeenCalledTimes(1);
    expect(api.updateGremium).toHaveBeenCalledTimes(2);
    expect(saved).toHaveBeenCalledWith(
      expect.objectContaining({ created: true, recipients: ['ok@x.de'] }),
    );
  });

  it('names a failed save and a failed recipient read', async () => {
    const api = makeApi({
      updateGremium: jest.fn(() => throwError(() => ({ status: 500 }))),
      getGremiumMailRecipients: jest.fn(() => throwError(() => ({ status: 500 }))),
    });
    await setup(STUPA, api);
    expect(within(dialog()).getByRole('alert')).toHaveTextContent(
      'Die Protokoll-Empfänger konnten nicht geladen werden.',
    );
    await userEvent.click(save());
    expect(within(dialog()).getByRole('alert')).toHaveTextContent(
      'Gremium konnte nicht gespeichert werden.',
    );
  });

  it('keeps the stored recipients when their read failed', async () => {
    const api = makeApi({
      getGremiumMailRecipients: jest.fn(() => throwError(() => ({ status: 503 }))),
    });
    const { saved } = await setup(STUPA, api);
    expect(within(dialog()).getByRole('alert')).toHaveTextContent('Speichern ändert sie nicht.');
    // The empty field would delete the stored list, so it stays locked.
    expect(within(dialog()).getByRole('textbox', { name: /Protokoll-Empfänger/ })).toBeDisabled();
    await userEvent.clear(screen.getByRole('spinbutton', { name: 'Quorum (%)' }));
    await userEvent.type(screen.getByRole('spinbutton', { name: 'Quorum (%)' }), '60');
    await userEvent.click(save());
    expect(api.updateGremium).toHaveBeenCalledWith(
      'g-1',
      expect.objectContaining({ quorumPercent: 60 }),
    );
    expect(api.setGremiumMailRecipients).not.toHaveBeenCalled();
    expect(saved).toHaveBeenCalledWith(
      expect.objectContaining({ created: false, recipients: null }),
    );
  });

  it('closes on cancel', async () => {
    const { closed } = await setup(STUPA);
    await userEvent.click(within(dialog()).getByText('Abbrechen'));
    expect(closed).toHaveBeenCalled();
  });

  it('reads a cleared quorum as "no quorum" and a cleared lead time as 0', async () => {
    const { api } = await setup(STUPA);
    await userEvent.clear(screen.getByRole('spinbutton', { name: 'Quorum (%)' }));
    await userEvent.clear(screen.getByRole('spinbutton', { name: /Vorlauf/ }));
    await userEvent.click(save());
    expect(api.updateGremium).toHaveBeenCalledWith(
      'g-1',
      expect.objectContaining({ quorumPercent: null, delegationLeadMinutes: 0 }),
    );
  });

  it('splits the recipients at line breaks, commas and semicolons', () => {
    expect(parseRecipients(' a@x.de ,\n\nb@x.de;c@x.de ')).toEqual(['a@x.de', 'b@x.de', 'c@x.de']);
    expect(parseRecipients('')).toEqual([]);
  });

  it('fills the defaults of a sparse gremium and guards the save', async () => {
    const sparse: Gremium = {
      id: 'g-9',
      name: 'Sparse',
      slug: 'sparse',
      cdVariantId: null,
      defaultLang: 'de',
      allowVoteDelegation: false,
    };
    const api = makeApi();
    const { fixture } = await setup(sparse, api);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.form()).toMatchObject({
      cdVariantId: '',
      delegationLeadMinutes: 0,
      delegationAllowExternal: false,
      quorumPercent: null,
    });
    c.patchQuorum('abc');
    expect(c.form().quorumPercent).toBeNull();
    c.patchQuorum(-3);
    expect(c.form().quorumPercent).toBe(0);
    c.patchQuorum(undefined);
    expect(c.form().quorumPercent).toBeNull();
    c.patchLead('x');
    expect(c.form().delegationLeadMinutes).toBe(0);
    c.patchLead(-5);
    expect(c.form().delegationLeadMinutes).toBe(0);
    c.patchLead(99999);
    expect(c.form().delegationLeadMinutes).toBe(43200);
    c.patch('name', '   ');
    c.submit();
    expect(api.updateGremium).not.toHaveBeenCalled();
  });

  it('falls back to the lower-case name when the name gives no slug', async () => {
    const api = makeApi();
    await setup(null, api);
    await userEvent.type(screen.getByRole('textbox', { name: /Name/ }), '§§');
    expect(screen.getByText('—')).toBeInTheDocument();
    await userEvent.click(save());
    expect(api.createGremium).toHaveBeenCalledWith(expect.objectContaining({ slug: '§§' }));
  });
});
