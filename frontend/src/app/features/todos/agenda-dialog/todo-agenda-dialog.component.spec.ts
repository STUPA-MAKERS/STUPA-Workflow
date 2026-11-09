import { render } from '@testing-library/angular';
import { of, throwError } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import type { Meeting } from '@core/api/models';
import { ToastService } from '@stupa-makers/ui-kit';
import { TodoAgendaDialogComponent } from './todo-agenda-dialog.component';

const MEETINGS = [
  { id: 'm-1', title: '34. Sitzung', date: '2026-11-12', startTime: '18:00:00' },
  { id: 'm-2', title: 'Sondersitzung', date: '2026-11-19', startTime: null },
  { id: 'm-3', title: 'Ohne Termin', date: null, startTime: null },
] as unknown as Meeting[];

async function setup(code?: string, meetings: readonly Meeting[] = MEETINGS, open = true) {
  const api = {
    addAgendaTodo: jest.fn(() => (code ? throwError(() => ({ error: { code } })) : of([]))),
  };
  const toast = { success: jest.fn(), error: jest.fn() };
  const view = await render(TodoAgendaDialogComponent, {
    inputs: { open, cardId: 'k-1', meetings },
    providers: [
      { provide: ApiClient, useValue: api },
      { provide: ToastService, useValue: toast },
    ],
  });
  return { ...view, api, toast, cmp: view.fixture.componentInstance };
}

describe('TodoAgendaDialogComponent (spec 000553)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('offers the planned meetings and picks the next one', async () => {
    const { cmp } = await setup();
    expect(cmp.rows().map((r) => [r.id, r.title])).toEqual([
      ['m-1', '34. Sitzung'],
      ['m-2', 'Sondersitzung'],
      ['m-3', 'Ohne Termin'],
    ]);
    expect(cmp.rows()[2].sub).toBe('');
    expect(cmp.rows()[0].sub).toContain('18:00');
    expect(cmp.pick()).toBe('m-1');
  });

  it('puts the card on the next meeting and closes', async () => {
    const { cmp, api, toast } = await setup();
    const added = jest.fn();
    cmp.added.subscribe(added);
    cmp.submit('m-1');
    expect(api.addAgendaTodo).toHaveBeenCalledWith('m-1', 'k-1');
    expect(toast.success).toHaveBeenCalledWith('Auf die Tagesordnung gesetzt');
    expect(added).toHaveBeenCalledWith('m-1');
    expect(cmp.open()).toBe(false);
  });

  it('says so when the card is on that agenda already', async () => {
    const { cmp, toast } = await setup('todo_already_on_agenda');
    cmp.submit('m-1');
    expect(toast.error).toHaveBeenCalledWith('Die Karte steht schon auf dieser Tagesordnung.');
    expect(cmp.open()).toBe(true);
  });

  it('says that it failed on any other error', async () => {
    const { cmp, toast } = await setup('boom');
    cmp.submit('m-1');
    expect(toast.error).toHaveBeenCalledWith('Die Karte konnte nicht auf die Tagesordnung.');
  });

  it('picks nothing without meetings', async () => {
    expect((await setup(undefined, [])).cmp.pick()).toBeNull();
  });

  it('picks nothing while closed', async () => {
    expect((await setup(undefined, MEETINGS, false)).cmp.pick()).toBeNull();
  });
});
