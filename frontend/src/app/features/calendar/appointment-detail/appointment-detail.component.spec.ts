import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { Appointment } from '@core/api/calendar.service';
import type { TodoLinkedCard } from '@core/api/todos.service';
import { appointment } from '../../../../testing/calendar-fixtures';
import { runAxe } from '../../../../testing/a11y';
import { errorToasts } from '../../../../testing/load-error';
import { CALENDAR_NOW } from '../calendar-grid.util';
import { AppointmentDetailComponent } from './appointment-detail.component';

const URL = '/api/calendar/appointments/a-1';

const LINKED = '/api/todos/linked';

async function setup(
  a: Appointment | null = appointment(),
  now = new Date(2026, 10, 11, 9, 0),
  cards: readonly TodoLinkedCard[] = [],
) {
  const on = { closed: jest.fn(), edit: jest.fn(), answered: jest.fn(), removed: jest.fn() };
  const view = await render(AppointmentDetailComponent, {
    inputs: { open: true, appointment: a },
    on,
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      provideRouter([]),
      { provide: CALENDAR_NOW, useValue: () => now },
    ],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  http.match((r) => r.url === LINKED).forEach((r) => r.flush(cards));
  view.fixture.detectChanges();
  return { ...view, on, http };
}

jest.setTimeout(15_000);

describe('AppointmentDetailComponent', () => {
  it('shows when, where, from whom, the invited and the answers', async () => {
    const view = await setup();
    const dialog = screen.getByRole('dialog', { name: 'Jour fixe' });
    expect(within(dialog).getByText('Mi, 11.11.2026 · 14:00 – 15:30')).toBeInTheDocument();
    expect(within(dialog).getByText('AStA-Büro')).toBeInTheDocument();
    expect(within(dialog).getByText('Dana Meier')).toBeInTheDocument();
    expect(within(dialog).getByText('Offene Buchungen')).toBeInTheDocument();
    expect(within(dialog).getByText('Haushaltsausschuss')).toBeInTheDocument();
    const [row] = within(dialog).getAllByRole('listitem');
    expect(row).toHaveTextContent('Jonas Weber');
    expect(row).toHaveTextContent('Zusage');
    expect(await runAxe(view.container)).toHaveNoViolations();
  });

  it('leaves out what a Termin does not have', async () => {
    await setup(
      appointment({ place: null, description: null, creator: null, gremien: [], persons: [], answers: [], invited: false, canEdit: false }),
    );
    const dialog = screen.getByRole('dialog', { name: 'Jour fixe' });
    expect(within(dialog).queryByText('Ort')).toBeNull();
    expect(within(dialog).queryByText('Von')).toBeNull();
    expect(within(dialog).queryByText('Eingeladen')).toBeNull();
    expect(within(dialog).queryByText('Antworten')).toBeNull();
    expect(within(dialog).queryByRole('radiogroup')).toBeNull();
    expect(within(dialog).queryByRole('button', { name: 'Bearbeiten' })).toBeNull();
    expect(within(dialog).queryByRole('button', { name: 'Löschen' })).toBeNull();
  });

  /** § 000735: the detail of a Termin shows the cards that link it. */
  it('shows the cards that link the Termin', async () => {
    const card: TodoLinkedCard = {
      id: 'k-1',
      boardId: 'b-1',
      boardName: 'Studierendenparlament',
      title: 'Raum buchen',
      columnName: 'In Arbeit',
      isDone: false,
      dueDate: null,
      assignees: [],
      event: null,
      balance: null,
    };
    const view = await setup(appointment(), undefined, [card]);
    const dialog = screen.getByRole('dialog', { name: 'Jour fixe' });
    expect(within(dialog).getByRole('link', { name: 'Raum buchen' })).toBeInTheDocument();
    expect(await runAxe(view.container)).toHaveNoViolations();
  });

  it('shows no dialog without a Termin', async () => {
    await setup(null);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  /** § 000719: an invited person answers and changes the answer. */
  it('saves the answer of an invited person', async () => {
    const view = await setup();
    await userEvent.click(screen.getByRole('radio', { name: 'Vorbehalt' }));
    const req = view.http.expectOne(`${URL}/answer`);
    expect(req.request.body).toEqual({ answer: 'tentative' });
    const saved = appointment({ myAnswer: 'tentative' });
    req.flush(saved);
    expect(view.on.answered).toHaveBeenCalledWith(saved);
    view.fixture.componentRef.setInput('appointment', saved);
    view.fixture.detectChanges();
    expect(screen.getByRole('radio', { name: 'Vorbehalt' })).toBeChecked();
    view.fixture.componentInstance.setAnswer('tentative');
    view.fixture.componentInstance.setAnswer('other');
    view.fixture.componentInstance.setAnswer(null);
    view.http.verify();
  });

  it('reports a refused answer and takes no second answer while one is out', async () => {
    const view = await setup();
    view.fixture.componentInstance.setAnswer('accept');
    view.fixture.componentInstance.setAnswer('decline');
    view.http.expectOne(`${URL}/answer`).flush({ code: 'calendar_appointment_over' }, { status: 409, statusText: 'Conflict' });
    expect(errorToasts()).toEqual(['Die Antwort konnte nicht gespeichert werden.']);
    expect(view.on.answered).not.toHaveBeenCalled();
    expect(view.fixture.componentInstance.answering()).toBe(false);
  });

  /** § 000719: the answer stays open until the Termin ends. */
  it('offers no answer after the end of the Termin, and none to a person who is not invited', async () => {
    await setup(appointment(), new Date(2026, 10, 11, 16, 0));
    expect(screen.queryByRole('radiogroup')).toBeNull();
  });

  it('asks for the edit dialog', async () => {
    const view = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Bearbeiten' }));
    expect(view.on.edit).toHaveBeenCalledWith(appointment());
    await userEvent.click(screen.getByRole('button', { name: 'Schließen' }));
    expect(view.on.closed).toHaveBeenCalled();
  });

  it('deletes the Termin after a confirmation', async () => {
    const view = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Löschen' }));
    const confirm = await screen.findByRole('dialog', { name: 'Termin löschen?' });
    expect(confirm).toHaveTextContent('„Jour fixe“ wird endgültig gelöscht.');
    await userEvent.click(within(confirm).getByRole('button', { name: 'Abbrechen' }));
    expect(view.fixture.componentInstance.confirming()).toBe(false);
    view.http.expectNone(URL);

    await userEvent.click(await screen.findByRole('button', { name: 'Löschen' }));
    await userEvent.click(within(await screen.findByRole('dialog', { name: 'Termin löschen?' })).getByRole('button', { name: 'Löschen' }));
    view.fixture.componentInstance.remove();
    const req = view.http.expectOne(URL);
    expect(req.request.method).toBe('DELETE');
    req.flush(null);
    expect(view.on.removed).toHaveBeenCalledWith(appointment());
    expect(view.fixture.componentInstance.confirming()).toBe(false);
  });

  it('reports a failed delete and keeps the confirmation open', async () => {
    const view = await setup();
    view.fixture.componentInstance.confirming.set(true);
    view.fixture.componentInstance.remove();
    view.http.expectOne(URL).flush(null, { status: 500, statusText: 'Error' });
    expect(errorToasts()).toEqual(['Der Termin konnte nicht gelöscht werden.']);
    expect(view.fixture.componentInstance.confirming()).toBe(true);
    expect(view.on.removed).not.toHaveBeenCalled();
    view.fixture.componentRef.setInput('appointment', null);
    view.fixture.componentInstance.remove();
    view.http.verify();
  });
});
