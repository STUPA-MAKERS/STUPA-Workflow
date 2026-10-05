import { Subject, of, throwError } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { ToastService } from '@stupa-makers/ui-kit';
import { AdminApiService } from '../../admin-api.service';
import {
  MERGE_AREAS,
  type AdminPrincipal,
  type MergePreview,
  type MergeResult,
} from '../../admin.models';
import { UserMergeComponent } from './user-merge.component';

const OLD: AdminPrincipal = {
  id: 'p-old',
  sub: 'e03ad7d7',
  email: 'erika@alt.example',
  displayName: 'Erika (Keycloak)',
  lastLogin: '2025-11-14T08:30:00+00:00',
  assignments: [],
  oidcGroups: [],
};
const NEW: AdminPrincipal = {
  id: 'p-new',
  sub: 'authentik|erika',
  email: 'erika@neu.example',
  displayName: 'Erika Neu',
  lastLogin: null,
  assignments: [],
  oidcGroups: [],
};
const OFF: AdminPrincipal = { ...NEW, id: 'p-off', displayName: '', email: 'off@x', active: false };
const MERGED: AdminPrincipal = { ...NEW, id: 'p-merged', displayName: 'Schon weg', mergedIntoId: 'p-new' };

function side(p: AdminPrincipal) {
  return {
    id: p.id,
    displayName: p.displayName ?? null,
    email: p.email ?? null,
    lastLogin: p.lastLogin ?? null,
  };
}

function areas(over: Partial<Record<string, [number, number, number]>> = {}) {
  return MERGE_AREAS.map((area) => {
    const [rewritten, combined, removed] = over[area] ?? [0, 0, 0];
    return { area, rewritten, combined, removed };
  });
}

function preview(over: Partial<MergePreview> = {}): MergePreview {
  return {
    source: side(OLD),
    target: side(NEW),
    areas: areas({ votes: [3, 0, 0], notifications: [0, 2, 0], sessions: [0, 0, 1] }),
    conflicts: [],
    canMerge: true,
    ...over,
  };
}

function result(): MergeResult {
  return {
    source: side(OLD),
    target: side(NEW),
    areas: areas({ votes: [3, 0, 0] }),
    mergedAt: '2026-10-05T10:00:00+00:00',
  };
}

function makeApi(over: Partial<Record<string, jest.Mock>> = {}) {
  return {
    listPrincipals: jest.fn(() => of([OLD, NEW, OFF, MERGED])),
    previewPrincipalMerge: jest.fn(() => of(preview())),
    mergePrincipal: jest.fn(() => of(result())),
    ...over,
  };
}

async function setup(api = makeApi(), source: AdminPrincipal | null = OLD) {
  const toast = { success: jest.fn(), error: jest.fn() };
  const closed = jest.fn();
  const merged = jest.fn();
  const view = await render(UserMergeComponent, {
    inputs: { source },
    on: { closed, merged },
    providers: [
      { provide: AdminApiService, useValue: api },
      { provide: ToastService, useValue: toast },
    ],
  });
  return { ...view, api, toast, closed, merged };
}

async function pickNew() {
  await userEvent.click(screen.getByRole('button', { name: /Erika Neu/ }));
}

describe('UserMergeComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('renders nothing while no account is chosen', async () => {
    const { api } = await setup(makeApi(), null);
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(api.listPrincipals).not.toHaveBeenCalled();
  });

  it('lists the accounts to pick, without the old one and without merged ones', async () => {
    await setup();
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText('Altes Konto: Erika (Keycloak)')).toBeInTheDocument();
    const list = screen.getByRole('list', { name: 'Konten zur Auswahl' });
    expect(list.querySelectorAll('li')).toHaveLength(2);
    expect(screen.queryByText('Schon weg')).toBeNull();
    // An inactive account without a name shows its e-mail and the tag.
    expect(screen.getAllByText('off@x').length).toBeGreaterThan(0);
    expect(screen.getByText('deaktiviert')).toBeInTheDocument();
    expect(screen.getAllByText(/nie/)).toHaveLength(2);
  });

  it('shows "no results" for an empty or failed search', async () => {
    await setup(makeApi({ listPrincipals: jest.fn(() => of([OLD])) }));
    expect(screen.getByText('Keine Benutzer gefunden.')).toBeInTheDocument();
  });

  it('a failed search shows an empty list', async () => {
    await setup(makeApi({ listPrincipals: jest.fn(() => throwError(() => new Error('x'))) }));
    expect(screen.getByText('Keine Benutzer gefunden.')).toBeInTheDocument();
  });

  it('shows the preview: both accounts, the areas with rows, the warning', async () => {
    const { api } = await setup();
    await pickNew();
    expect(api.previewPrincipalMerge).toHaveBeenCalledWith('p-old', 'p-new');
    expect(screen.getByText('Altes Konto')).toBeInTheDocument();
    expect(screen.getByText('Bleibt bestehen')).toBeInTheDocument();
    expect(screen.getByText('Stimmen (offen und geheim)')).toBeInTheDocument();
    expect(screen.getByText('3 übertragen')).toBeInTheDocument();
    expect(screen.getByText('2 zusammengefasst')).toBeInTheDocument();
    expect(screen.getByText('1 entfernt')).toBeInTheDocument();
    // An area without rows does not show.
    expect(screen.queryByText('Kommentare')).toBeNull();
    expect(screen.getByText(/Das alte Konto wird gesperrt/)).toBeInTheDocument();
    expect(screen.getByText(/zeigen danach Erika Neu/)).toBeInTheDocument();
  });

  it('needs the "I understand" box before the danger button works', async () => {
    const { api, merged, toast } = await setup();
    await pickNew();
    const go = screen.getByRole('button', { name: 'Konten zusammenführen' });
    expect(go).toBeDisabled();
    await userEvent.click(screen.getByLabelText(/Ich habe die Vorschau geprüft/));
    expect(go).toBeEnabled();
    await userEvent.click(go);
    expect(api.mergePrincipal).toHaveBeenCalledWith('p-old', 'p-new');
    expect(merged).toHaveBeenCalledWith(result());
    expect(toast.success).toHaveBeenCalledWith('Konten zusammengeführt.');
    expect(
      screen.getByText('Erika (Keycloak) ist jetzt mit Erika Neu zusammengeführt. Das alte Konto ist gesperrt.'),
    ).toBeInTheDocument();
    expect(screen.getByText('3 übertragen')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Fertig' }));
  });

  it('a result without rows shows only the note', async () => {
    const api = makeApi({
      previewPrincipalMerge: jest.fn(() => of(preview({ areas: areas() }))),
      mergePrincipal: jest.fn(() => of({ ...result(), areas: areas() })),
    });
    const { container } = await setup(api);
    await pickNew();
    expect(screen.getByText('Das alte Konto hat keine Daten.')).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText(/Ich habe die Vorschau geprüft/));
    await userEvent.click(screen.getByRole('button', { name: 'Konten zusammenführen' }));
    expect(container.ownerDocument.querySelector('.um__areas')).toBeNull();
  });

  it('lists the conflicts with an explanation and keeps the merge blocked', async () => {
    const api = makeApi({
      previewPrincipalMerge: jest.fn(() =>
        of(
          preview({
            canMerge: false,
            conflicts: [
              { kind: 'ballot_same_vote', label: 'Haushalt 2026' },
              { kind: 'erasure_open', label: null },
            ],
          }),
        ),
      ),
    });
    await setup(api);
    await pickNew();
    expect(screen.getByText('Konflikte')).toBeInTheDocument();
    expect(screen.getByText('Beide Konten haben in derselben Abstimmung abgestimmt')).toBeInTheDocument();
    expect(screen.getByText('Haushalt 2026')).toBeInTheDocument();
    expect(screen.getByText(/Führe den Löschantrag unter Datenschutz aus/)).toBeInTheDocument();
    // No confirmation box; the danger button says why it is off.
    expect(screen.queryByLabelText(/Ich habe die Vorschau geprüft/)).toBeNull();
    const go = screen.getByRole('button', { name: 'Konten zusammenführen' });
    expect(go).toBeDisabled();
    expect(go).toHaveAttribute('title', 'Löse zuerst die Konflikte.');
  });

  it('a 409 merge_conflict shows the conflicts of the server', async () => {
    const api = makeApi({
      mergePrincipal: jest.fn(() =>
        throwError(() => ({
          status: 409,
          error: {
            code: 'merge_conflict',
            errors: [
              { field: 'attendance_differs', msg: 'Sitzung 3' },
              { field: 'erasure_open', msg: '' },
            ],
          },
        })),
      ),
    });
    const { toast } = await setup(api);
    await pickNew();
    await userEvent.click(screen.getByLabelText(/Ich habe die Vorschau geprüft/));
    await userEvent.click(screen.getByRole('button', { name: 'Konten zusammenführen' }));
    expect(toast.error).toHaveBeenCalledWith('Die Daten haben sich geändert. Prüfe die Konflikte.');
    expect(screen.getByText('Sitzung 3')).toBeInTheDocument();
    expect(screen.getByText('Die Konten haben in derselben Sitzung eine andere Anwesenheit')).toBeInTheDocument();
    expect(screen.getByText('Für eines der Konten ist ein Löschantrag offen')).toBeInTheDocument();
  });

  it('a 409 merge_conflict without an errors list loads the preview again', async () => {
    const api = makeApi({
      mergePrincipal: jest.fn(() => throwError(() => ({ status: 409, error: { code: 'merge_conflict' } }))),
    });
    await setup(api);
    await pickNew();
    await userEvent.click(screen.getByLabelText(/Ich habe die Vorschau geprüft/));
    await userEvent.click(screen.getByRole('button', { name: 'Konten zusammenführen' }));
    expect(api.previewPrincipalMerge).toHaveBeenCalledTimes(2);
  });

  it('a 409 merge_conflict without a list loads the preview again', async () => {
    const api = makeApi({
      mergePrincipal: jest.fn(() =>
        throwError(() => ({ status: 409, error: { code: 'merge_conflict', errors: null } })),
      ),
    });
    await setup(api);
    await pickNew();
    await userEvent.click(screen.getByLabelText(/Ich habe die Vorschau geprüft/));
    await userEvent.click(screen.getByRole('button', { name: 'Konten zusammenführen' }));
    expect(api.previewPrincipalMerge).toHaveBeenCalledTimes(2);
  });

  it('any other error gives a toast and keeps the preview', async () => {
    const api = makeApi({ mergePrincipal: jest.fn(() => throwError(() => ({ status: 500 }))) });
    const { toast } = await setup(api);
    await pickNew();
    await userEvent.click(screen.getByLabelText(/Ich habe die Vorschau geprüft/));
    await userEvent.click(screen.getByRole('button', { name: 'Konten zusammenführen' }));
    expect(toast.error).toHaveBeenCalledWith('Zusammenführen fehlgeschlagen.');
    expect(screen.getByText('3 übertragen')).toBeInTheDocument();
  });

  it('a failed preview offers a retry, and "Zurück" returns to the list', async () => {
    let calls = 0;
    const api = makeApi({
      previewPrincipalMerge: jest.fn(() => (++calls === 1 ? throwError(() => new Error('x')) : of(preview()))),
    });
    await setup(api);
    await pickNew();
    expect(screen.getByText('Die Vorschau konnte nicht geladen werden.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Erneut versuchen' }));
    expect(screen.getByText('3 übertragen')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Zurück' }));
    expect(screen.getByRole('list', { name: 'Konten zur Auswahl' })).toBeInTheDocument();
  });

  it('shows a placeholder while the preview loads', async () => {
    const pending = new Subject<MergePreview>();
    await setup(makeApi({ previewPrincipalMerge: jest.fn(() => pending) }));
    await pickNew();
    expect(screen.getByText('Vorschau wird geladen …')).toBeInTheDocument();
    pending.next(preview());
    pending.complete();
  });

  it('"Abbrechen" closes the dialog', async () => {
    const { closed } = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Abbrechen' }));
    expect(closed).toHaveBeenCalled();
  });

  it('the guards do nothing without an account or a preview', async () => {
    const { fixture } = await setup(makeApi(), null);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const inst = fixture.componentInstance as any;
    inst.pick(NEW);
    inst.retryPreview();
    inst.confirm();
    expect(inst.step()).toBe('pick');
    expect(inst.name(null)).toBe('Konto ohne Namen');
    expect(inst.previewAreas()).toEqual([]);
    expect(inst.resultAreas()).toEqual([]);
    expect(inst.conflicts()).toEqual([]);
  });

  it('a new account starts again at the first step', async () => {
    const { fixture, rerender } = await setup();
    await pickNew();
    await rerender({ inputs: { source: { ...OLD, id: 'p-other' } } });
    fixture.detectChanges();
    expect(screen.getByRole('list', { name: 'Konten zur Auswahl' })).toBeInTheDocument();
  });
});
