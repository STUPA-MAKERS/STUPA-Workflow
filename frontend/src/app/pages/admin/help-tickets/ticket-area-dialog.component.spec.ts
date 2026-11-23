import { render, screen } from '@testing-library/angular';
import { Subject, of, throwError, type Observable } from 'rxjs';
import { TicketsApiService, type TicketArea } from '@core/api/tickets.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { toastWith } from '../../../../testing/load-error';
import { TicketAreaDialogComponent, idsAfter } from './ticket-area-dialog.component';

const PLAT: TicketArea = {
  id: 'a-plat',
  name: 'Plattform',
  gremiumId: null,
  platform: true,
  notifyNew: true,
  categories: [],
  mine: true,
};
const ASTA: TicketArea = {
  id: 'a-asta',
  name: 'AStA-Büro',
  gremiumId: 'g1',
  platform: false,
  notifyNew: false,
  categories: [
    { id: 'c1', name: 'Raumanfrage' },
    { id: 'c2', name: 'Schlüssel' },
  ],
  mine: true,
};

const refusal = (code: string) => throwError(() => ({ status: 409, error: { code } }));

/** The methods of the dialog that a test calls in place of the fields of the kit form. */
interface Inner {
  value(): Record<string, unknown>;
  onValue(v: Record<string, unknown>): void;
  errors(): Record<string, string>;
  save(): void;
  doDelete(): void;
  onAction(key: string): void;
  confirmDelete(): boolean;
}

async function setup(area: TicketArea | null = null) {
  localStorage.setItem('ap.locale', 'de');
  const api = {
    createArea: jest.fn((b: object): Observable<TicketArea> => of({ ...ASTA, id: 'a-new', ...b } as TicketArea)),
    updateArea: jest.fn((_id: string, b: object): Observable<TicketArea> => of({ ...ASTA, ...b } as TicketArea)),
    deleteArea: jest.fn((): Observable<void> => of(undefined)),
  };
  const toast = { success: jest.fn(), error: jest.fn() };
  const saved = jest.fn();
  const deleted = jest.fn();
  const closed = jest.fn();
  const view = await render(TicketAreaDialogComponent, {
    inputs: { open: true, area, gremien: [{ id: 'g1', name: 'AStA' }] },
    on: { saved, deleted, closed },
    providers: [
      { provide: TicketsApiService, useValue: api },
      { provide: ToastService, useFactory: () => toastWith(toast) },
    ],
  });
  await view.fixture.whenStable();
  view.fixture.detectChanges();
  const cmp = view.fixture.componentInstance as unknown as Inner;
  /** Set the value as the form reports it, then let the form take it. */
  const fill = async (value: Record<string, unknown>) => {
    cmp.onValue(value);
    view.fixture.detectChanges();
    await view.fixture.whenStable();
  };
  return { ...view, cmp, fill, api, toast, saved, deleted, closed };
}

describe('idsAfter', () => {
  it('gives a new row at the end no id', () => {
    expect(idsAfter(['a'], ['c1'], ['a', ''])).toEqual(['c1', null]);
  });

  it('drops the id of the removed row, also of the last one', () => {
    expect(idsAfter(['a', 'b', 'c'], ['c1', 'c2', 'c3'], ['a', 'c'])).toEqual(['c1', 'c3']);
    expect(idsAfter(['a', 'b'], ['c1', 'c2'], ['a'])).toEqual(['c1']);
  });

  it('keeps the ids on a changed name', () => {
    expect(idsAfter(['a', 'b'], ['c1', null], ['a', 'x'])).toEqual(['c1', null]);
  });
});

describe('TicketAreaDialogComponent', () => {
  afterEach(() => localStorage.clear());

  it('creates a Bereich with its Gremium and its Kategorien', async () => {
    const { cmp, fill, api, saved } = await setup();
    expect(screen.getByRole('heading', { name: 'Bereich anlegen' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Bereich löschen' })).toBeNull();
    expect(cmp.value()).toEqual({ name: '', gremiumId: '', notifyNew: true, categories: [] });
    await fill({ name: '  Fachschaft ', gremiumId: 'g1', notifyNew: true, categories: [{ name: ' Beratung' }] });
    cmp.save();
    expect(api.createArea).toHaveBeenCalledWith({
      name: 'Fachschaft',
      gremiumId: 'g1',
      notifyNew: true,
      categories: [{ name: 'Beratung' }],
    });
    expect(saved).toHaveBeenCalled();
  });

  it('saves nothing without a name', async () => {
    const { cmp, api } = await setup();
    cmp.save();
    expect(api.createArea).not.toHaveBeenCalled();
  });

  it('keeps the id of a renamed Kategorie and drops a removed one', async () => {
    const { cmp, fill, api } = await setup(ASTA);
    expect(screen.getByRole('heading', { name: 'Bereich bearbeiten' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Bereich löschen' })).toBeInTheDocument();
    const start = cmp.value();
    await fill({ ...start, categories: [{ name: 'Schlüssel' }] });
    await fill({ ...start, gremiumId: '', categories: [{ name: 'Schlüsselausgabe' }] });
    await fill({ ...start, gremiumId: '', categories: [{ name: 'Schlüsselausgabe' }, { name: 'Neu' }] });
    cmp.save();
    expect(api.updateArea).toHaveBeenCalledWith('a-asta', {
      name: 'AStA-Büro',
      gremiumId: null,
      notifyNew: false,
      categories: [{ id: 'c2', name: 'Schlüsselausgabe' }, { name: 'Neu' }],
    });
  });

  it('saves only the switch of Plattform', async () => {
    const { cmp, fill, api } = await setup(PLAT);
    expect(screen.getByText(/Plattform ist fest eingebaut/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Bereich löschen' })).toBeNull();
    await fill({ notifyNew: false });
    cmp.save();
    expect(api.updateArea).toHaveBeenCalledWith('a-plat', { notifyNew: false });
  });

  it('shows a taken name under the field, and any other refusal as a toast', async () => {
    const { cmp, api, toast, saved } = await setup(ASTA);
    api.updateArea.mockReturnValueOnce(refusal('ticket_area_name_taken'));
    cmp.save();
    expect(cmp.errors()).toEqual({ name: 'Ein Bereich mit diesem Namen existiert schon.' });
    api.updateArea.mockReturnValueOnce(refusal('ticket_categories_invalid'));
    cmp.save();
    expect(toast.error).toHaveBeenCalledWith('Jede Kategorie braucht einen eigenen Namen.');
    api.updateArea.mockReturnValueOnce(throwError(() => ({ status: 500, error: null })));
    cmp.save();
    expect(toast.error).toHaveBeenLastCalledWith('Der Bereich konnte nicht gespeichert werden.');
    expect(saved).not.toHaveBeenCalled();
  });

  it('saves only once while a save runs', async () => {
    const { cmp, api } = await setup(ASTA);
    api.updateArea.mockReturnValueOnce(new Subject<TicketArea>());
    cmp.save();
    cmp.save();
    cmp.doDelete();
    expect(api.updateArea).toHaveBeenCalledTimes(1);
    expect(api.deleteArea).not.toHaveBeenCalled();
  });

  it('deletes a Bereich after the question', async () => {
    const { cmp, api, deleted } = await setup(ASTA);
    cmp.onAction('delete');
    expect(cmp.confirmDelete()).toBe(true);
    cmp.doDelete();
    expect(api.deleteArea).toHaveBeenCalledWith('a-asta');
    expect(deleted).toHaveBeenCalledWith(ASTA);
  });

  it('says why a Bereich with tickets stays', async () => {
    const { cmp, api, toast, deleted } = await setup(ASTA);
    api.deleteArea.mockReturnValueOnce(refusal('ticket_area_has_tickets'));
    cmp.doDelete();
    expect(toast.error).toHaveBeenCalledWith(
      'Der Bereich enthält Tickets. Verschiebe sie zuerst in einen anderen Bereich.',
    );
    api.deleteArea.mockReturnValueOnce(throwError(() => ({ status: 500 })));
    cmp.doDelete();
    expect(toast.error).toHaveBeenLastCalledWith('Der Bereich konnte nicht gelöscht werden.');
    expect(deleted).not.toHaveBeenCalled();
  });

  it('closes on Abbrechen, saves on Speichern and deletes nothing in a new Bereich', async () => {
    const { cmp, fill, api, closed } = await setup();
    cmp.doDelete();
    expect(api.deleteArea).not.toHaveBeenCalled();
    await fill({ name: 'Büro', gremiumId: '', notifyNew: false, categories: [] });
    cmp.onAction('save');
    expect(api.createArea).toHaveBeenCalledWith({ name: 'Büro', gremiumId: null, notifyNew: false, categories: [] });
    cmp.onAction('cancel');
    expect(closed).toHaveBeenCalled();
  });
});
