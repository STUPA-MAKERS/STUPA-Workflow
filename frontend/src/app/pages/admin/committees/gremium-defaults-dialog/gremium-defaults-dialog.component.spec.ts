import { render, screen, waitFor } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { of, throwError } from 'rxjs';
import { ToastService } from '@stupa-makers/ui-kit';
import { AdminApiService } from '../../admin-api.service';
import type { GremiumDefaults } from '../../admin.models';
import { GremiumDefaultsDialogComponent } from './gremium-defaults-dialog.component';

const DEFAULTS: GremiumDefaults = {
  quorumPercent: 40,
  repeatQuorumPercent: 25,
  guestsMayVote: false,
  allowVoteDelegation: false,
  delegationLeadMinutes: 120,
  delegationMaxPerDelegate: 2,
};

function makeApi(over: Partial<Record<string, jest.Mock>> = {}) {
  return {
    getGremiumDefaults: jest.fn(() => of({ ...DEFAULTS })),
    putGremiumDefaults: jest.fn((b: GremiumDefaults) => of(b)),
    ...over,
  };
}

async function setup(api = makeApi(), open = true) {
  const closed = jest.fn();
  const view = await render(GremiumDefaultsDialogComponent, {
    providers: [{ provide: AdminApiService, useValue: api }],
    componentInputs: { open },
    on: { closed },
  });
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  const toasts = () =>
    view.fixture.debugElement.injector
      .get(ToastService)
      .toasts()
      .map((t) => t.message);
  return { ...view, api, closed, toasts };
}

const saveButton = () => screen.getByText('Speichern').closest('button') as HTMLButtonElement;

describe('GremiumDefaultsDialogComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('reads nothing while it is closed', async () => {
    const { api } = await setup(makeApi(), false);
    expect(api.getGremiumDefaults).not.toHaveBeenCalled();
  });

  /** §F/administration/admin/000906 */
  it('shows the stored defaults and saves the changed values', async () => {
    const { api, closed, toasts } = await setup();
    expect(screen.getByRole('dialog', { name: 'Vorgaben für neue Gremien' })).toBeInTheDocument();
    const quorum = screen.getByRole('spinbutton', { name: 'Quorum (%)' });
    await waitFor(() => expect(quorum).toHaveValue(40));
    const guests = screen.getByRole('switch', { name: 'Gäste dürfen abstimmen' });
    expect(guests).toBeDisabled();
    expect(screen.queryByRole('spinbutton', { name: 'Vorlauf für Delegationen (Minuten)' })).toBeNull();
    await userEvent.clear(quorum);
    const repeat = screen.getByRole('spinbutton', { name: 'Quorum der Wiederholungssitzung (%)' });
    await userEvent.clear(repeat);
    await userEvent.type(repeat, '150');
    await userEvent.click(guests);
    await userEvent.click(screen.getByRole('switch', { name: 'Stimm-Delegation erlauben' }));
    const lead = screen.getByRole('spinbutton', { name: 'Vorlauf für Delegationen (Minuten)' });
    await userEvent.clear(lead);
    await userEvent.type(lead, '90');
    const most = screen.getByRole('spinbutton', { name: 'Höchstzahl Delegationen je Person' });
    expect(most).toHaveValue(2);
    await userEvent.clear(most);
    await userEvent.type(most, '3');
    await userEvent.click(saveButton());
    expect(api.putGremiumDefaults).toHaveBeenCalledWith({
      quorumPercent: null,
      repeatQuorumPercent: 100,
      guestsMayVote: true,
      allowVoteDelegation: true,
      delegationLeadMinutes: 90,
      delegationMaxPerDelegate: 3,
    });
    expect(toasts()).toContain('Vorgaben gespeichert.');
    expect(closed).toHaveBeenCalled();
  });

  it('reads an empty or invalid lead time as 0 and caps it at 30 days', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const cmp = fixture.componentInstance as any;
    cmp.patchLead('abc');
    expect(cmp.form().delegationLeadMinutes).toBe(0);
    cmp.patchLead(999999);
    expect(cmp.form().delegationLeadMinutes).toBe(43200);
    cmp.patchMax('');
    expect(cmp.form().delegationMaxPerDelegate).toBe(2);
    cmp.patchMax(0);
    expect(cmp.form().delegationMaxPerDelegate).toBe(1);
    cmp.patchMax(99);
    expect(cmp.form().delegationMaxPerDelegate).toBe(20);
    cmp.patchPercent('quorumPercent', 'abc');
    expect(cmp.form().quorumPercent).toBeNull();
  });

  it('names a failed read, reads again on the retry and cannot save before', async () => {
    const api = makeApi({
      getGremiumDefaults: jest
        .fn()
        .mockReturnValueOnce(throwError(() => ({ status: 500 })))
        .mockReturnValue(of({ ...DEFAULTS })),
    });
    const { fixture, toasts } = await setup(api);
    expect(toasts()).toContain('Die Vorgaben konnten nicht geladen werden.');
    expect(saveButton()).toBeDisabled();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const cmp = fixture.componentInstance as any;
    cmp.save();
    cmp.patch({ guestsMayVote: true });
    expect(cmp.form()).toBeNull();
    expect(api.putGremiumDefaults).not.toHaveBeenCalled();
    cmp.load();
    fixture.detectChanges();
    await waitFor(() => expect(screen.getByRole('spinbutton', { name: 'Quorum (%)' })).toHaveValue(40));
  });

  it('names a failed save, stays open and closes on cancel', async () => {
    const api = makeApi({ putGremiumDefaults: jest.fn(() => throwError(() => ({ status: 500 }))) });
    const { closed, toasts } = await setup(api);
    await userEvent.click(saveButton());
    expect(toasts()).toContain('Die Vorgaben konnten nicht gespeichert werden.');
    expect(closed).not.toHaveBeenCalled();
    await userEvent.click(screen.getByText('Abbrechen').closest('button') as HTMLButtonElement);
    expect(closed).toHaveBeenCalled();
  });
});
