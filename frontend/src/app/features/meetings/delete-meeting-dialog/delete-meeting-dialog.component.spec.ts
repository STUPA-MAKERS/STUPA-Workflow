import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { Meeting } from '@core/api/models';
import { ToastService } from '@stupa-makers/ui-kit';
import { runAxe } from '../../../../testing/a11y';
import { DeleteMeetingDialogComponent } from './delete-meeting-dialog.component';

const PLANNED = { id: 'm-1', title: '35. Sitzung', status: 'planned', protocolId: null } as unknown as Meeting;

async function setup(meeting: Meeting | null = PLANNED) {
  const closed = jest.fn();
  const deleted = jest.fn();
  const view = await render(DeleteMeetingDialogComponent, {
    inputs: { meeting },
    on: { closed, deleted },
    providers: [provideHttpClient(), provideHttpClientTesting()],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  const toasts = () =>
    view.fixture.debugElement.injector
      .get(ToastService)
      .toasts()
      .map((t) => t.message);
  return { ...view, http, cmp: view.fixture.componentInstance, closed, deleted, toasts };
}

describe('DeleteMeetingDialogComponent', () => {
  it('names what goes with a planned meeting and offers an outlined danger button', async () => {
    await setup();
    expect(screen.getByRole('dialog', { name: 'Sitzung löschen' })).toBeInTheDocument();
    expect(
      screen.getByText(
        '„35. Sitzung“ wird mit Tagesordnung, Anwesenheit und Vertretungen gelöscht. Das kann nicht rückgängig gemacht werden.',
      ),
    ).toBeInTheDocument();
    const confirm = screen.getByRole('button', { name: 'Endgültig löschen' });
    expect(confirm).toHaveClass('btn--danger');
    expect(confirm).not.toHaveClass('btn--fill');
  });

  it('names the protocol once the meeting has one', async () => {
    await setup({ ...PLANNED, status: 'closed', protocolId: 'p-1' } as Meeting);
    expect(screen.getByText(/wird mit Protokoll, Tagesordnung, Anwesenheit und Vertretungen/)).toBeInTheDocument();
  });

  it('deletes the meeting and reports it', async () => {
    const { http, deleted, toasts } = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Endgültig löschen' }));
    const req = http.expectOne('/api/meetings/m-1');
    expect(req.request.method).toBe('DELETE');
    req.flush(null, { status: 204, statusText: 'No Content' });
    expect(deleted).toHaveBeenCalledWith('m-1');
    expect(toasts()).toContain('Sitzung gelöscht.');
  });

  it('names the open vote, another refusal and a bare error', async () => {
    const { http, cmp, deleted, toasts } = await setup();
    cmp.confirm();
    cmp.confirm(); // one request at a time
    http.expectOne('/api/meetings/m-1').flush({ code: 'open_vote' }, { status: 409, statusText: 'x' });
    expect(toasts()).toContain(
      'Eine Abstimmung der Sitzung ist noch offen. Bitte die Abstimmung zuerst schließen oder abbrechen.',
    );
    cmp.confirm();
    http
      .expectOne('/api/meetings/m-1')
      .flush({ detail: 'final protocol' }, { status: 403, statusText: 'x' });
    expect(toasts()).toContain('Aktion fehlgeschlagen.: final protocol');
    cmp.confirm();
    http.expectOne('/api/meetings/m-1').flush(null, { status: 500, statusText: 'x' });
    expect(toasts()).toContain('Aktion fehlgeschlagen.');
    expect(deleted).not.toHaveBeenCalled();
    expect(cmp.deleting()).toBe(false);
  });

  it('has no axe violations', async () => {
    await setup();
    expect(await runAxe(document.body)).toHaveNoViolations();
  });

  it('closes on cancel', async () => {
    const { closed } = await setup();
    const [, footerCancel] = screen.getAllByRole('button', { name: 'Abbrechen' });
    await userEvent.click(footerCancel);
    expect(closed).toHaveBeenCalled();
  });

  it('stays closed and sends nothing without a meeting', async () => {
    const { http, cmp } = await setup(null);
    expect(screen.queryByRole('dialog')).toBeNull();
    cmp.confirm();
    http.verify();
  });
});
