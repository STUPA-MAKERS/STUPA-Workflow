import { provideRouter } from '@angular/router';
import { render, screen } from '@testing-library/angular';
import type { ApplicationDecision } from '@core/api/models';
import { runAxe } from '../../../testing/a11y';
import { DecisionSectionComponent } from './decision-section.component';

const DECISION: ApplicationDecision = {
  requestedAmount: '1250.00',
  approvedAmount: '900.00',
  amountDeviates: true,
  conditions: ['Belege bis 31.12.2026', 'STUPA als Förderer nennen'],
  decidedAt: '2026-09-29T19:41:00Z',
  voteId: 'v-1',
  gremiumName: 'Studierendenparlament',
  meetingTitle: '34. Sitzung',
  agendaPosition: 6,
};

async function setup(decision: ApplicationDecision = DECISION, applicant = false) {
  localStorage.setItem('ap.locale', 'de');
  return render(DecisionSectionComponent, {
    inputs: { decision, applicant, currency: 'EUR' },
    providers: [provideRouter([])],
  });
}

const norm = (el: Element) => (el.textContent ?? '').replace(/\u00a0/g, ' ');

describe('DecisionSectionComponent', () => {
  it('shows the deviation, the conditions and the source for the team', async () => {
    const { container } = await setup();
    expect(screen.getByRole('heading', { name: 'Beschluss' })).toBeInTheDocument();
    expect(screen.getByText('Mit Abweichungen')).toBeInTheDocument();
    expect(norm(container.querySelector('s') as Element)).toBe('1.250,00 €');
    expect(norm(container.querySelector('.dsec__approved') as Element)).toBe('900,00 €');
    expect(norm(container.querySelector('.dsec__diff') as Element)).toBe('−350,00 €');
    expect(screen.getAllByRole('listitem')).toHaveLength(2);
    expect(screen.getByText(/Studierendenparlament, 34. Sitzung, TOP 6/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Zur Abstimmung' })).toHaveAttribute('href', '/voting/v-1');
    expect(screen.queryByText(/Gefördert wird nur/)).toBeNull();
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('shows the Gremium only and a note for the applicant', async () => {
    const { container } = await setup({ ...DECISION, voteId: null, meetingTitle: null, agendaPosition: null }, true);
    expect(screen.queryByRole('link')).toBeNull();
    expect(screen.getByText(/· Studierendenparlament$/)).toBeInTheDocument();
    expect(norm(screen.getByText(/Gefördert wird nur/))).toContain('bis zu 900,00 €');
    expect(await runAxe(container)).toHaveNoViolations();
  });

  it('hides meeting data in the applicant view even when it is sent', async () => {
    await setup(DECISION, true);
    expect(screen.queryByText(/34. Sitzung/)).toBeNull();
  });

  it('shows only the approved amount for a decision as requested', async () => {
    const { container } = await setup({
      ...DECISION,
      approvedAmount: null,
      amountDeviates: false,
      conditions: [],
      voteId: null,
      gremiumName: null,
      meetingTitle: null,
      agendaPosition: null,
    });
    expect(screen.queryByText('Mit Abweichungen')).toBeNull();
    expect(container.querySelector('s')).toBeNull();
    expect(norm(container.querySelector('.dsec__approved') as Element)).toBe('1.250,00 €');
    expect(screen.queryByRole('list')).toBeNull();
  });

  it('notes the conditions for an applicant without an amount deviation', async () => {
    await setup({ ...DECISION, approvedAmount: null, amountDeviates: false, requestedAmount: null }, true);
    expect(screen.getByText('Bitte beachte die Auflagen des Beschlusses.')).toBeInTheDocument();
  });

  it('has no note for an applicant without a deviation', async () => {
    await setup({ ...DECISION, approvedAmount: null, amountDeviates: false, conditions: [] }, true);
    expect(screen.queryByText(/Gefördert wird nur|Bitte beachte/)).toBeNull();
  });
});
