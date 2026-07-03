import { render, screen } from '@testing-library/angular';
import type { SelectOption } from '@stupa-makers/ui-kit';
import type { TransitionDef } from '../admin.models';
import { TransitionDetailComponent } from './transition-detail.component';

const ROLES: SelectOption[] = [{ value: 'finance', label: 'Finanzen (finance)' }];
const GREMIEN: SelectOption[] = [{ value: 'g1', label: 'StuPa' }];
const WEBHOOKS: SelectOption[] = [{ value: 'w1', label: 'Buchhaltung' }];

async function setup(transition: TransitionDef) {
  const view = await render(TransitionDetailComponent, {
    inputs: {
      transition,
      roleOptions: ROLES,
      gremiumOptions: GREMIEN,
      webhookOptions: WEBHOOKS,
    },
  });
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const c = view.fixture.componentInstance as any;
  return { ...view, c };
}

describe('TransitionDetailComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('renders every action kind with its param control and recipient rows', async () => {
    const { c } = await setup({
      from: 'a',
      to: 'b',
      actions: [
        { type: 'webhook', webhookId: 'w1' },
        { type: 'addToNextSession', gremiumId: 'g1' },
        { type: 'assignBudget', budgetId: 'b1' },
        {
          type: 'notify',
          recipients: [
            { kind: 'applicant' },
            { kind: 'gremium', ref: 'g1' },
            { kind: 'role', ref: 'finance' },
            { kind: 'email', ref: 'x@y.de' },
          ],
        },
      ],
    });
    // Label appears in the add-select option AND as the card title.
    expect(screen.getAllByText('Webhook auslösen').length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText('Zur nächsten Sitzung').length).toBeGreaterThanOrEqual(2);
    // Params and recipients are read through the pure helpers.
    expect(c.actionParam({ type: 'assignBudget', budgetId: 'b1' }, 'budgetId')).toBe('b1');
    expect(c.actionParam({ type: 'assignBudget' }, 'budgetId')).toBe('');
    expect(c.recipientsOf({ type: 'notify' })).toEqual([]);
    expect(c.recipientNeedsRef('gremium')).toBe(true);
    expect(c.recipientNeedsRef('applicant')).toBe(false);
    expect(c.actionOptions().length).toBeGreaterThan(0);
    expect(c.recipientKindOptions().length).toBeGreaterThan(0);
    expect(c.actionLabel('notify')).toBeTruthy();
    // The email recipient renders a free-text ref input.
    expect(document.querySelector('input[placeholder="name@beispiel.de"]')).not.toBeNull();
  });

  it('emits add/remove/param/recipient events instead of mutating the graph', async () => {
    const { c } = await setup({
      from: 'a',
      to: 'b',
      actions: [{ type: 'notify', recipients: [{ kind: 'applicant' }] }],
    });
    const events: unknown[] = [];
    c.actionAdd.subscribe((e: unknown) => events.push(['add', e]));
    c.actionRemove.subscribe((e: unknown) => events.push(['remove', e]));
    c.actionParamChange.subscribe((e: unknown) => events.push(['param', e]));
    c.recipientAdd.subscribe((e: unknown) => events.push(['rcpt+', e]));
    c.recipientRemove.subscribe((e: unknown) => events.push(['rcpt-', e]));
    c.guardChange.subscribe((e: unknown) => events.push(['guard', e]));
    c.actionAdd.emit('webhook');
    c.actionRemove.emit(0);
    c.actionParamChange.emit({ ai: 0, key: 'webhookId', value: 'w1' });
    c.recipientAdd.emit(0);
    c.recipientRemove.emit({ ai: 0, ri: 0 });
    c.guardChange.emit(null);
    expect(events).toEqual([
      ['add', 'webhook'],
      ['remove', 0],
      ['param', { ai: 0, key: 'webhookId', value: 'w1' }],
      ['rcpt+', 0],
      ['rcpt-', { ai: 0, ri: 0 }],
      ['guard', null],
    ]);
  });
});
