import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { AgendaItem, Meeting } from '@core/api/models';
import { ToastService } from '@stupa-makers/ui-kit';
import { runAxe } from '../../../../testing/a11y';
import { VoteOpenDialogComponent } from './vote-open-dialog.component';

const MEETING = { id: 'm-1', title: '34. Sitzung', status: 'live', votes: [] } as unknown as Meeting;
const APP_TOP: AgendaItem = { id: 't-3', applicationId: 'a-1', title: 'Zuschuss Party', position: 2 };
const FREE_TOP: AgendaItem = { id: 't-8', applicationId: null, title: 'Verschiedenes', position: 7 };

async function setup(item: AgendaItem | null = APP_TOP, topNumber = 3) {
  const closed = jest.fn();
  const opened = jest.fn();
  const view = await render(VoteOpenDialogComponent, {
    inputs: { meeting: MEETING, item, topNumber },
    on: { closed, opened },
    providers: [provideHttpClient(), provideHttpClientTesting()],
  });
  const http = view.fixture.debugElement.injector.get(HttpTestingController);
  const toasts = () =>
    view.fixture.debugElement.injector
      .get(ToastService)
      .toasts()
      .map((t) => t.message);
  return { ...view, http, cmp: view.fixture.componentInstance, closed, opened, toasts };
}

describe('VoteOpenDialogComponent', () => {
  it('names the item and prefills the question of an application item', async () => {
    await setup();
    const dialog = screen.getByRole('dialog', { name: 'Abstimmung öffnen' });
    expect(dialog).toHaveAccessibleDescription('TOP 3 · Zuschuss Party');
    expect(screen.getByLabelText('Beschlussfrage')).toHaveValue(
      'Soll der Antrag „Zuschuss Party“ wie beschrieben gefördert werden?',
    );
    expect(screen.getByRole('radio', { name: 'Einfach' })).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByRole('switch', { name: 'Geheime Abstimmung' })).toHaveAttribute('aria-checked', 'false');
    expect(screen.getByText('Stimmen werden ohne Namen gezählt')).toBeInTheDocument();
  });

  it('builds no tie break, no ballot change and no eligible count (O11, O18)', async () => {
    const { http, opened, toasts } = await setup();
    expect(screen.queryByText(/Stimmengleichheit/)).toBeNull();
    expect(screen.queryByText(/änderbar/)).toBeNull();
    await userEvent.click(screen.getByRole('radio', { name: 'Zwei Drittel' }));
    await userEvent.click(screen.getByRole('switch', { name: 'Geheime Abstimmung' }));
    const question = screen.getByLabelText('Beschlussfrage');
    await userEvent.clear(question);
    await userEvent.type(question, '  Fördern wir?  ');
    const submit = screen
      .getAllByRole('button', { name: 'Abstimmung öffnen' })
      .find((b) => b.closest('.dialog__footer'));
    await userEvent.click(submit as HTMLElement);
    const req = http.expectOne('/api/meetings/m-1/votes');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({
      agendaItemId: 't-3',
      question: 'Fördern wir?',
      options: ['yes', 'no', 'abstain'],
      secret: true,
      majorityRule: 'two_thirds',
    });
    for (const key of ['eligibleCount', 'allowChange', 'tieBreak', 'quorumPercent']) {
      expect(req.request.body).not.toHaveProperty(key);
    }
    req.flush({ ...MEETING, votes: [], createdAt: 'x' });
    expect(opened).toHaveBeenCalled();
    expect(toasts()).toContain('Abstimmung geöffnet.');
  });

  it('starts a free-text item with its title and sends an empty question as null', async () => {
    const { http, cmp } = await setup(FREE_TOP, 8);
    expect(cmp.question()).toBe('Verschiedenes');
    expect(cmp.subtitle()).toBe('TOP 8 · Verschiedenes');
    cmp.question.set('   ');
    cmp.submit();
    cmp.submit(); // one request at a time
    expect(http.expectOne('/api/meetings/m-1/votes').request.body.question).toBeNull();
  });

  it('copes with items without a title', async () => {
    const { cmp, fixture } = await setup({ ...APP_TOP, title: null });
    expect(cmp.question()).toBe('Soll der Antrag „“ wie beschrieben gefördert werden?');
    expect(cmp.subtitle()).toBe('TOP 3');
    fixture.componentRef.setInput('item', { ...FREE_TOP, title: null });
    fixture.detectChanges();
    expect(cmp.question()).toBe('');
  });

  it('has no axe violations', async () => {
    await setup();
    expect(await runAxe(document.body)).toHaveNoViolations();
  });

  it('accepts only the known majority rules', async () => {
    const { cmp } = await setup();
    cmp.setRule('absolute');
    expect(cmp.majorityRule()).toBe('absolute');
    cmp.setRule('tie');
    cmp.setRule(null);
    expect(cmp.majorityRule()).toBe('absolute');
  });

  it('shows the server reason when the open fails', async () => {
    const { http, cmp, opened, toasts } = await setup();
    cmp.submit();
    http.expectOne('/api/meetings/m-1/votes').flush({ detail: 'TOP hat schon eine Abstimmung' }, { status: 409, statusText: 'x' });
    expect(toasts()).toContain('Aktion fehlgeschlagen.: TOP hat schon eine Abstimmung');
    cmp.submit();
    http.expectOne('/api/meetings/m-1/votes').flush(null, { status: 500, statusText: 'x' });
    expect(toasts()).toContain('Aktion fehlgeschlagen.');
    expect(opened).not.toHaveBeenCalled();
    expect(cmp.submitting()).toBe(false);
  });

  it('stays closed without an item and closes on cancel', async () => {
    const empty = await setup(null);
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(empty.cmp.subtitle()).toBe('');
    empty.cmp.submit();
    empty.http.verify();
    empty.fixture.componentRef.setInput('item', APP_TOP);
    empty.fixture.detectChanges();
    const [, footerCancel] = screen.getAllByRole('button', { name: 'Abbrechen' });
    await userEvent.click(footerCancel);
    expect(empty.closed).toHaveBeenCalled();
  });
});
