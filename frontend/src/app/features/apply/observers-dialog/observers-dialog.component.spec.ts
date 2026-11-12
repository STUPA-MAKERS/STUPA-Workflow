import { HttpErrorResponse } from '@angular/common/http';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { of, throwError } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import type { ApplicationObserver } from '@core/api/models';
import { ToastService } from '@stupa-makers/ui-kit';
import { MAX_OBSERVERS, ObserversDialogComponent } from './observers-dialog.component';

const APP = 'a1';
const ADRIAN: ApplicationObserver = { id: 'o1', email: 'adrian@example.org', addedAt: '2026-11-10T09:00:00Z' };

function refusal(status: number, code: string): HttpErrorResponse {
  return new HttpErrorResponse({ status, error: { status, code } });
}

async function setup(api: Partial<Record<keyof ApiClient, jest.Mock>>, open = true) {
  const toast = { error: jest.fn(), success: jest.fn(), show: jest.fn() };
  const full: Partial<Record<keyof ApiClient, jest.Mock>> = {
    applicationObservers: jest.fn(() => of([ADRIAN])),
    addApplicationObserver: jest.fn(),
    removeApplicationObserver: jest.fn(() => of(undefined)),
    ...api,
  };
  const view = await render(ObserversDialogComponent, {
    inputs: { applicationId: APP, open },
    providers: [
      { provide: ApiClient, useValue: full },
      { provide: ToastService, useValue: toast },
    ],
  });
  return { ...view, cmp: view.fixture.componentInstance, api: full, toast };
}

describe('ObserversDialogComponent', () => {
  it('lists the observers when it opens and adds an address', async () => {
    const added: ApplicationObserver = { id: 'o2', email: 'mara@example.org', addedAt: '2026-11-11T09:00:00Z' };
    const { api, toast } = await setup({ addApplicationObserver: jest.fn(() => of(added)) });
    expect(await screen.findByText('adrian@example.org')).toBeInTheDocument();
    expect(api.applicationObservers).toHaveBeenCalledWith(APP);
    await userEvent.type(screen.getByLabelText('E-Mail-Adresse'), 'mara@example.org');
    await userEvent.click(screen.getByRole('button', { name: 'Hinzufügen' }));
    expect(api.addApplicationObserver).toHaveBeenCalledWith(APP, 'mara@example.org');
    expect(await screen.findByText('mara@example.org')).toBeInTheDocument();
    expect(toast.success).toHaveBeenCalledWith('Beobachter:in hinzugefügt');
  });

  it('removes an observer from its row menu', async () => {
    const { cmp, api, toast } = await setup({});
    await screen.findByText('adrian@example.org');
    cmp.remove(cmp.menu(ADRIAN)[0].items[0]);
    expect(api.removeApplicationObserver).toHaveBeenCalledWith(APP, 'o1');
    expect(cmp.observers()).toEqual([]);
    expect(toast.success).toHaveBeenCalledWith('Beobachter:in entfernt');
    api.removeApplicationObserver!.mockReturnValue(throwError(() => new Error('x')));
    cmp.remove({ id: 'o9', label: 'x' });
    expect(toast.error).toHaveBeenCalled();
  });

  it.each([
    [refusal(409, 'observer_exists'), 'Diese Adresse beobachtet den Antrag schon.'],
    [refusal(422, 'observer_is_applicant'), 'Das ist die Adresse der antragstellenden Person.'],
    [refusal(422, 'observer_limit'), 'Ein Antrag hat höchstens 5 Beobachter:innen.'],
    [refusal(422, ''), 'Gib eine gültige E-Mail-Adresse ein.'],
  ])('shows the refusal %# on the field', async (err, message) => {
    const { cmp, fixture } = await setup({ addApplicationObserver: jest.fn(() => throwError(() => err)) });
    await screen.findByText('adrian@example.org');
    cmp.onText('x@example.org');
    cmp.add();
    fixture.detectChanges();
    expect(await screen.findByText(message)).toBeInTheDocument();
    cmp.onText('y@example.org');
    expect(cmp.error()).toBeNull();
  });

  it('toasts any other failure, and ignores an empty field', async () => {
    const { cmp, api, toast } = await setup({
      addApplicationObserver: jest.fn(() => throwError(() => new HttpErrorResponse({ status: 500 }))),
    });
    await screen.findByText('adrian@example.org');
    cmp.add();
    expect(api.addApplicationObserver).not.toHaveBeenCalled();
    cmp.onText('x@example.org');
    cmp.add();
    expect(toast.error).toHaveBeenCalledWith('Das hat nicht geklappt. Versuch es noch einmal.');
  });

  it('hides the field at the limit and shows the empty state without observers', async () => {
    const five = Array.from({ length: MAX_OBSERVERS }, (_, i) => ({ ...ADRIAN, id: `o${i}`, email: `p${i}@example.org` }));
    const { cmp, fixture } = await setup({ applicationObservers: jest.fn(() => of(five)) });
    await screen.findByText('p0@example.org');
    expect(screen.queryByLabelText('E-Mail-Adresse')).not.toBeInTheDocument();
    cmp.observers.set([]);
    fixture.detectChanges();
    expect(screen.getByText('Noch niemand beobachtet diesen Antrag')).toBeInTheDocument();
  });

  it('toasts a failed load', async () => {
    const { toast } = await setup({ applicationObservers: jest.fn(() => throwError(() => new Error('x'))) });
    expect(toast.error).toHaveBeenCalledWith('Die Beobachter:innen konnten nicht geladen werden.');
  });

  it('loads nothing while closed', async () => {
    const closed = await setup({}, false);
    expect(closed.api.applicationObservers).not.toHaveBeenCalled();
  });
});
