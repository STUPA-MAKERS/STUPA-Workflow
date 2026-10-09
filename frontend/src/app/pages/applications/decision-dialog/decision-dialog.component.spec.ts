import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import { USE_MOCK_API } from '@core/api/api.config';
import type { Transition } from '@core/api/models';
import { ToastService } from '@stupa-makers/ui-kit';
import { runAxe } from '../../../../testing/a11y';
import { DecisionDialogComponent } from './decision-dialog.component';

const APPROVE: Transition = {
  id: 'tr-approve',
  fromStateId: 's1',
  toStateId: 's2',
  label: 'Bewilligen',
  color: null,
  addsToAgenda: false,
  agendaGremiumId: null,
  allowsDecision: true,
};

async function setup(transition: Transition | null = APPROVE, open = true) {
  localStorage.setItem('ap.locale', 'de');
  const done = jest.fn();
  const view = await render(DecisionDialogComponent, {
    providers: [provideHttpClient(), provideHttpClientTesting(), { provide: USE_MOCK_API, useValue: false }],
    componentInputs: {
      applicationId: 'app-1',
      applicationTitle: 'Erstsemester-Hütte',
      requested: '1250.00',
      currency: 'EUR',
      transition,
      open,
    },
    on: { done },
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  const toast = view.fixture.debugElement.injector.get(ToastService);
  const confirm = () =>
    screen.getAllByRole('button', { name: 'Bewilligen' }).find((b) => b.closest('.dialog__footer')) as HTMLElement;
  return { ...view, http, toast, done, confirm };
}

describe('DecisionDialogComponent', () => {
  it('fires as requested while the switch is off', async () => {
    const { http, done, toast, confirm, container } = await setup();
    expect(screen.getByRole('dialog', { name: 'Bewilligen' })).toHaveAccessibleDescription('Erstsemester-Hütte');
    expect(screen.queryByLabelText('Förderbetrag')).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
    await userEvent.click(confirm());
    const req = http.expectOne('/api/applications/app-1/transition');
    expect(req.request.body).toEqual({ transitionId: 'tr-approve' });
    req.flush({ newStateId: 's2', statusEventId: 'e', dispatchedActions: [] });
    expect(done).toHaveBeenCalled();
    expect(toast.toasts().map((t) => t.message)).toContain('Status geändert.');
  });

  it('sends the approved amount and the conditions', async () => {
    const { http, confirm } = await setup();
    await userEvent.click(screen.getByRole('switch', { name: /Mit Abweichungen genehmigen/ }));
    const amount = screen.getByLabelText('Förderbetrag');
    await userEvent.clear(amount);
    await userEvent.type(amount, '900');
    await userEvent.click(screen.getByRole('button', { name: 'Auflage hinzufügen' }));
    await userEvent.type(screen.getByLabelText('Auflage 1'), 'Belege bis Jahresende');
    await userEvent.click(confirm());
    const req = http.expectOne('/api/applications/app-1/transition');
    expect(req.request.body).toEqual({
      transitionId: 'tr-approve',
      decision: { approvedAmount: '900', conditions: ['Belege bis Jahresende'] },
    });
    req.flush({ newStateId: 's2', statusEventId: 'e', dispatchedActions: [] });
  });

  it('blocks an amount above the requested one', async () => {
    const { http, confirm, fixture } = await setup();
    await userEvent.click(screen.getByRole('switch', { name: /Mit Abweichungen genehmigen/ }));
    const amount = screen.getByLabelText('Förderbetrag');
    await userEvent.clear(amount);
    await userEvent.type(amount, '2000');
    fixture.detectChanges();
    expect(screen.getByRole('alert')).toHaveTextContent('nicht übersteigen');
    expect(confirm()).toBeDisabled();
    (fixture.componentInstance as unknown as { submit(): void }).submit();
    http.expectNone('/api/applications/app-1/transition');
  });

  it('shows the refusal of the server in the dialog', async () => {
    const { http, confirm, done } = await setup();
    await userEvent.click(confirm());
    http
      .expectOne('/api/applications/app-1/transition')
      .flush({ code: 'decision_not_allowed' }, { status: 422, statusText: 'Unprocessable' });
    expect(await screen.findByText('Bei diesem Übergang ist keine Abweichung möglich.')).toBeInTheDocument();
    expect(done).not.toHaveBeenCalled();
  });

  it('closes on a conflict and reports other errors as a toast', async () => {
    const { http, confirm, done, toast } = await setup();
    await userEvent.click(confirm());
    http.expectOne('/api/applications/app-1/transition').flush(null, { status: 409, statusText: 'Conflict' });
    expect(done).toHaveBeenCalled();
    expect(toast.toasts().map((t) => t.message)).toContain(
      'Statuswechsel nicht möglich (Status hat sich geändert oder Bedingung nicht erfüllt).',
    );
  });

  it('reports a forbidden fire and a server error', async () => {
    const { http, confirm, toast } = await setup();
    await userEvent.click(confirm());
    http.expectOne('/api/applications/app-1/transition').flush(null, { status: 403, statusText: 'Forbidden' });
    await userEvent.click(confirm());
    http.expectOne('/api/applications/app-1/transition').flush(null, { status: 500, statusText: 'Error' });
    expect(toast.toasts().length).toBe(2);
  });

  it('does nothing without a transition and closes on cancel', async () => {
    const { http, fixture } = await setup(null);
    (fixture.componentInstance as unknown as { submit(): void }).submit();
    http.expectNone('/api/applications/app-1/transition');
    fixture.componentRef.setInput('transition', APPROVE);
    fixture.detectChanges();
    await userEvent.click(screen.getAllByRole('button', { name: 'Abbrechen' })[0]);
    expect(fixture.componentInstance.open()).toBe(false);
  });
});
