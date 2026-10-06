import { provideRouter } from '@angular/router';
import { render, screen, waitFor } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { of, throwError } from 'rxjs';
import { AdminApiService } from '../admin-api.service';
import type { GremiumRole } from '../admin.models';
import { GremiumRoleDialogComponent } from './gremium-role-dialog.component';

const OWN: GremiumRole = {
  id: 'gr-p',
  gremiumId: 'g-1',
  key: 'protokoll',
  name: { de: 'Protokoll', en: 'Minutes' },
  forced: false,
  permissions: ['vote.cast', 'protocol.write'],
};
const FORCED: GremiumRole = {
  ...OWN,
  id: 'gr-m',
  key: 'member',
  name: { de: 'Mitglied' },
  forced: true,
  permissions: ['vote.cast'],
};

function makeApi(over: Partial<Record<string, jest.Mock>> = {}) {
  return {
    createGremiumRole: jest.fn((gid: string, b: Partial<GremiumRole>) =>
      of({ id: 'gr-new', gremiumId: gid, ...b }),
    ),
    updateGremiumRole: jest.fn((id: string, b: Partial<GremiumRole>) => of({ ...OWN, id, ...b })),
    ...over,
  };
}

async function setup(
  role: GremiumRole | null,
  api = makeApi(),
  inputs: Record<string, unknown> = {},
) {
  const view = await render(GremiumRoleDialogComponent, {
    providers: [provideRouter([]), { provide: AdminApiService, useValue: api }],
    componentInputs: {
      open: true,
      role,
      gremiumId: 'g-1',
      gremiumName: 'Studierendenparlament',
      groups: ['stupa-protokoll'],
      showGroups: true,
      ...inputs,
    },
  });
  // NgModel writes its value after a microtask.
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  const saved = jest.fn();
  const deleteRequested = jest.fn();
  const closed = jest.fn();
  view.fixture.componentInstance.saved.subscribe(saved);
  view.fixture.componentInstance.deleteRequested.subscribe(deleteRequested);
  view.fixture.componentInstance.closed.subscribe(closed);
  return { ...view, api, saved, deleteRequested, closed };
}

describe('GremiumRoleDialogComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('edits a role: the key is fixed, every right of the catalogue shows, the groups link out', async () => {
    const { api, saved } = await setup(OWN);
    expect(screen.getByRole('heading', { name: 'Gremium-Rolle bearbeiten' })).toBeInTheDocument();
    // NgModel applies `disabled` after a microtask.
    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Schlüssel' })).toBeDisabled());
    expect(screen.getByText('Berechtigungen im Studierendenparlament')).toBeInTheDocument();
    for (const name of [
      'Sitzungen verwalten',
      'Abstimmungen führen',
      'Abstimmen',
      'Protokoll führen',
      'Protokoll freigeben',
    ]) {
      expect(screen.getByRole('checkbox', { name })).toBeInTheDocument();
    }
    expect(screen.getByRole('checkbox', { name: 'Protokoll führen' })).toBeChecked();
    expect(screen.getByText('stupa-protokoll')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'In der Gruppen-Zuordnung ändern' })).toHaveAttribute(
      'href',
      '/admin/group-mappings',
    );

    await userEvent.click(screen.getByRole('checkbox', { name: 'Protokoll freigeben' }));
    await userEvent.click(screen.getByRole('button', { name: 'Speichern' }));
    expect(api.updateGremiumRole).toHaveBeenCalledWith('gr-p', {
      name: { de: 'Protokoll', en: 'Minutes' },
      permissions: ['vote.cast', 'protocol.write', 'protocol.finalize'],
    });
    expect(saved).toHaveBeenCalled();
  });

  it('offers "Rolle löschen" for an own role and asks the parent', async () => {
    const { deleteRequested } = await setup(OWN);
    await userEvent.click(screen.getByRole('button', { name: 'Rolle löschen' }));
    expect(deleteRequested).toHaveBeenCalledWith(OWN);
  });

  it('has no delete for a forced role and names it as such', async () => {
    await setup(FORCED, makeApi(), { groups: ['stupa-mitglieder'] });
    expect(screen.queryByRole('button', { name: 'Rolle löschen' })).toBeNull();
    expect(
      screen.getByText(/Pflichtrolle: Sie ist in jedem Gremium vorhanden/),
    ).toBeInTheDocument();
    expect(screen.getByText('Mitgliedschaft über')).toBeInTheDocument();
  });

  it('creates a role: the key must match the pattern (A10)', async () => {
    const { api, saved } = await setup(null);
    const key = screen.getByRole('textbox', { name: /Schlüssel/ });
    const save = screen.getByRole('button', { name: 'Speichern' });
    expect(save).toBeDisabled();
    await userEvent.type(key, 'Kassen Prüfung');
    expect(screen.getByRole('alert')).toHaveTextContent(/Kleinbuchstaben/);
    expect(save).toBeDisabled();
    await userEvent.clear(key);
    await userEvent.type(key, 'kasse');
    await userEvent.type(screen.getByRole('textbox', { name: 'Bezeichnung (DE)' }), 'Kasse');
    // A new role can vote by default.
    expect(screen.getByRole('checkbox', { name: 'Abstimmen' })).toBeChecked();
    await userEvent.click(save);
    expect(api.createGremiumRole).toHaveBeenCalledWith('g-1', {
      key: 'kasse',
      name: { de: 'Kasse', en: 'Kasse' },
      permissions: ['vote.cast'],
    });
    expect(saved).toHaveBeenCalled();
  });

  it('shows a 409 and a 422 of the server under the key', async () => {
    const api = makeApi({
      createGremiumRole: jest
        .fn()
        .mockReturnValueOnce(throwError(() => ({ status: 409 })))
        .mockReturnValueOnce(throwError(() => ({ status: 422 }))),
    });
    await setup(null, api);
    await userEvent.type(screen.getByRole('textbox', { name: /Schlüssel/ }), 'vorstand');
    await userEvent.click(screen.getByRole('button', { name: 'Speichern' }));
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Diesen Schlüssel gibt es in diesem Gremium schon.',
    );
    await userEvent.click(screen.getByRole('button', { name: 'Speichern' }));
    expect(screen.getByRole('alert')).toHaveTextContent(/Kleinbuchstaben/);
    // A new key clears the answer of the server.
    await userEvent.type(screen.getByRole('textbox', { name: /Schlüssel/ }), 'x');
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('names another failure above the footer', async () => {
    const api = makeApi({ updateGremiumRole: jest.fn(() => throwError(() => ({ status: 500 }))) });
    const { saved } = await setup(OWN, api);
    await userEvent.click(screen.getByRole('button', { name: 'Speichern' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Speichern fehlgeschlagen.');
    expect(saved).not.toHaveBeenCalled();
  });

  it('hides the groups without the mappings permission and closes on cancel', async () => {
    const { closed } = await setup(OWN, makeApi(), { showGroups: false });
    expect(screen.queryByText('OIDC-Gruppen')).toBeNull();
    // The text button of the footer; the close icon of the dialog has the same name.
    await userEvent.click(screen.getByText('Abbrechen'));
    expect(closed).toHaveBeenCalled();
  });

  it('shows "no group" for a role without a mapping', async () => {
    await setup(OWN, makeApi(), { groups: [] });
    expect(screen.getByText('Keine Gruppe zugeordnet.')).toBeInTheDocument();
  });

  it('guards the save of an invalid key and the delete of a forced role', async () => {
    const api = makeApi();
    const { fixture, deleteRequested } = await setup(FORCED, api);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.askDelete();
    expect(deleteRequested).not.toHaveBeenCalled();
    c.togglePerm('vote.cast', false);
    expect(c.draft().permissions).toEqual([]);
    c.saving.set(true);
    c.save();
    expect(api.updateGremiumRole).not.toHaveBeenCalled();
  });
});
