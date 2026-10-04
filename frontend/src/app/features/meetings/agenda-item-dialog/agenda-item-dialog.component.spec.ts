import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { render, screen, within } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { AssignableApplication, Meeting } from '@core/api/models';
import { ToastService } from '@stupa-makers/ui-kit';
import { runAxe } from '../../../../testing/a11y';
import { AgendaItemDialogComponent } from './agenda-item-dialog.component';

const MEETING = { id: 'm-1', title: '34. Sitzung', status: 'live', votes: [] } as unknown as Meeting;
const APPS: AssignableApplication[] = [
  { applicationId: 'a-1', title: 'Sommerkino auf der Campuswiese', stateLabel: { de: 'Auf Tagesordnung', en: 'On the agenda' } },
  { applicationId: 'a-2', title: 'Erste-Hilfe-Kurs', stateLabel: null },
  { applicationId: 'a-3', title: null },
];

async function setup(open = true) {
  const closed = jest.fn();
  const added = jest.fn();
  const view = await render(AgendaItemDialogComponent, {
    inputs: { open, meeting: MEETING, nextNumber: 9 },
    on: { closed, added },
    providers: [provideHttpClient(), provideHttpClientTesting()],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  const toasts = () =>
    view.fixture.debugElement.injector
      .get(ToastService)
      .toasts()
      .map((t) => t.message);
  return { ...view, http, cmp: view.fixture.componentInstance, closed, added, toasts };
}

function flushApps(http: HttpTestingController, fixture: { detectChanges(): void }, rows = APPS) {
  http.expectOne('/api/meetings/m-1/agenda/assignable').flush(rows);
  fixture.detectChanges();
}

function submitButton(): HTMLElement {
  return screen
    .getAllByRole('button', { name: 'TOP hinzufügen' })
    .find((b) => b.closest('.dialog__footer')) as HTMLElement;
}

describe('AgendaItemDialogComponent', () => {
  it('lists the assignable applications of the Gremium with their state', async () => {
    const { http, fixture } = await setup();
    const dialog = screen.getByRole('dialog', { name: 'TOP hinzufügen' });
    expect(dialog).toHaveAccessibleDescription('34. Sitzung');
    expect(screen.getByRole('status')).toHaveTextContent('Wird geladen');
    flushApps(http, fixture);
    expect(screen.getByText('Zuweisbare Anträge · 3')).toBeInTheDocument();
    const group = screen.getByRole('radiogroup', { name: /Zuweisbare Anträge/ });
    expect(within(group).getAllByRole('radio')).toHaveLength(3);
    expect(within(group).getByText('Auf Tagesordnung')).toBeInTheDocument();
    expect(screen.getByText('Kommt als TOP 9 ans Ende der Tagesordnung.')).toBeInTheDocument();
    expect(submitButton()).toBeDisabled();
  });

  it('assigns the picked application, non-public at once', async () => {
    const { http, fixture, added } = await setup();
    flushApps(http, fixture);
    await userEvent.click(screen.getByRole('radio', { name: /Sommerkino/ }));
    await userEvent.click(screen.getByRole('switch', { name: 'Nicht öffentlich (NÖ)' }));
    await userEvent.click(submitButton());
    const req = http.expectOne('/api/meetings/m-1/agenda');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ applicationId: 'a-1', nonPublic: true });
    req.flush([{ id: 't-9', applicationId: 'a-1', title: 'Sommerkino', position: 8, nonPublic: true }]);
    expect(added).toHaveBeenCalledWith([expect.objectContaining({ id: 't-9' })]);
  });

  it('filters the list by the search text and says when nothing matches', async () => {
    const { http, fixture, cmp } = await setup();
    flushApps(http, fixture);
    await userEvent.type(screen.getByRole('searchbox', { name: 'Antrag suchen' }), 'kurs');
    const group = screen.getByRole('radiogroup', { name: /Zuweisbare Anträge/ });
    expect(within(group).getAllByRole('radio')).toHaveLength(1);
    expect(screen.getByText('Zuweisbare Anträge · 1')).toBeInTheDocument();
    cmp.query.set('zzz');
    fixture.detectChanges();
    expect(screen.getByText('Kein Antrag passt zur Suche.')).toBeInTheDocument();
  });

  it('does not send a pick that the search hides', async () => {
    const { http, fixture, cmp } = await setup();
    flushApps(http, fixture);
    await userEvent.click(screen.getByRole('radio', { name: /Sommerkino/ }));
    expect(submitButton()).toBeEnabled();
    await userEvent.type(screen.getByRole('searchbox', { name: 'Antrag suchen' }), 'kurs');
    expect(screen.getByRole('radio', { name: /Erste-Hilfe/ })).not.toBeChecked();
    expect(submitButton()).toBeDisabled();
    cmp.submit();
    http.expectNone('/api/meetings/m-1/agenda');
    await userEvent.clear(screen.getByRole('searchbox', { name: 'Antrag suchen' }));
    expect(screen.getByRole('radio', { name: /Sommerkino/ })).toBeChecked();
    expect(submitButton()).toBeEnabled();
  });

  it('says when no application can be assigned, also after a failed load', async () => {
    const { http, fixture } = await setup();
    http.expectOne('/api/meetings/m-1/agenda/assignable').flush(null, { status: 403, statusText: 'x' });
    fixture.detectChanges();
    expect(screen.getByText('Keine zuweisbaren Anträge.')).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    const { http, fixture } = await setup();
    flushApps(http, fixture, APPS.slice(0, 2));
    expect(await runAxe(document.body)).toHaveNoViolations();
  });

  it('adds a free-text item', async () => {
    const { http, fixture, cmp, added } = await setup();
    flushApps(http, fixture);
    await userEvent.click(screen.getByRole('radio', { name: 'Freitext-TOP' }));
    expect(submitButton()).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/Titel/), '  Verschiedenes ');
    await userEvent.click(submitButton());
    cmp.submit(); // one request at a time
    const req = http.expectOne('/api/meetings/m-1/agenda');
    expect(req.request.body).toEqual({ title: 'Verschiedenes', nonPublic: false });
    req.flush([]);
    expect(added).toHaveBeenCalledWith([]);
  });

  it('accepts only the two kinds', async () => {
    const { http, fixture, cmp } = await setup();
    flushApps(http, fixture);
    cmp.setKind('freetext');
    cmp.setKind('other');
    cmp.setKind(null);
    expect(cmp.kind()).toBe('freetext');
    cmp.setKind('application');
    expect(cmp.kind()).toBe('application');
  });

  it('shows the server reason when the add fails', async () => {
    const { http, fixture, cmp, added, toasts } = await setup();
    flushApps(http, fixture);
    cmp.pick.set('a-2');
    cmp.submit();
    http.expectOne('/api/meetings/m-1/agenda').flush({ detail: 'meeting_closed' }, { status: 409, statusText: 'x' });
    expect(toasts()).toContain('Aktion fehlgeschlagen.: meeting_closed');
    cmp.submit();
    http.expectOne('/api/meetings/m-1/agenda').flush(null, { status: 500, statusText: 'x' });
    expect(toasts()).toContain('Aktion fehlgeschlagen.');
    expect(added).not.toHaveBeenCalled();
  });

  it('starts empty on every opening and closes on cancel', async () => {
    const { http, fixture, cmp, closed } = await setup(false);
    http.expectNone('/api/meetings/m-1/agenda/assignable');
    fixture.componentRef.setInput('open', true);
    fixture.detectChanges();
    flushApps(http, fixture);
    cmp.pick.set('a-1');
    cmp.nonPublic.set(true);
    fixture.componentRef.setInput('open', false);
    fixture.detectChanges();
    fixture.componentRef.setInput('open', true);
    fixture.detectChanges();
    flushApps(http, fixture);
    expect(cmp.pick()).toBeNull();
    expect(cmp.nonPublic()).toBe(false);
    const [, footerCancel] = screen.getAllByRole('button', { name: 'Abbrechen' });
    await userEvent.click(footerCancel);
    expect(closed).toHaveBeenCalled();
  });
});
