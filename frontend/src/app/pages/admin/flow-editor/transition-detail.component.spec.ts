import { render, screen } from '@testing-library/angular';
import type { SelectOption } from '@stupa-makers/ui-kit';
import type { TransitionDef } from '../admin.models';
import type { BudgetTreeNode } from '../../budget/budget-tree.api';
import { TransitionDetailComponent } from './transition-detail.component';

const ROLES: SelectOption[] = [{ value: 'finance', label: 'Finanzen (finance)' }];
const GREMIEN: SelectOption[] = [{ value: 'g1', label: 'StuPa' }];
const WEBHOOKS: SelectOption[] = [{ value: 'w1', label: 'Buchhaltung' }];

const TREE: BudgetTreeNode[] = [
  {
    id: 'b1',
    parentId: null,
    gremiumId: null,
    key: 'VSM',
    pathKey: 'VSM',
    name: 'Studierendenschaft',
    currency: 'EUR',
    active: true,
    color: null,
    acceptedStateKeys: [],
    deniedStateKeys: [],
    hiddenInBudget: false,
    viewGremiumId: null,
    fiscalStartMonth: 1,
    fiscalStartDay: 1,
    byFiscalYear: [],
    children: [],
  },
];

async function setup(transition: TransitionDef, extra: Record<string, unknown> = {}) {
  const view = await render(TransitionDetailComponent, {
    inputs: {
      transition,
      roleOptions: ROLES,
      gremiumOptions: GREMIEN,
      webhookOptions: WEBHOOKS,
      ...extra,
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
    // The label appears in the add-select option and as the card title.
    expect(screen.getAllByText('Webhook auslösen').length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText('Zur nächsten Sitzung').length).toBeGreaterThanOrEqual(2);
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

  it('adds the chosen action kind only on "Hinzufügen" and clears the choice', async () => {
    const { c, fixture } = await setup({ from: 'a', to: 'b', actions: [] });
    const added: string[] = [];
    c.actionAdd.subscribe((e: string) => added.push(e));
    expect(screen.getByText('Noch keine Aktionen für diesen Übergang. Oben eine hinzufügen.')).toBeInTheDocument();
    const add = screen.getByRole('button', { name: 'Hinzufügen' });
    expect(add).toBeDisabled();
    c.addPending();
    expect(added).toEqual([]);
    c.pendingAction.set('webhook');
    fixture.detectChanges();
    expect(add).toBeEnabled();
    add.click();
    expect(added).toEqual(['webhook']);
    expect(c.pendingAction()).toBe('');
  });

  it('puts the value of a recipient under its kind and names the remove button of an action', async () => {
    const { container } = await setup({
      from: 'a',
      to: 'b',
      actions: [{ type: 'notify', recipients: [{ kind: 'applicant' }, { kind: 'gremium', ref: 'g1' }] }],
    });
    const rows = container.querySelectorAll('.td__recipient');
    expect(rows).toHaveLength(2);
    expect(rows[0].classList).not.toContain('td__recipient--ref');
    expect(rows[1].classList).toContain('td__recipient--ref');
    expect(screen.getByRole('button', { name: 'Entfernen: Benachrichtigen' })).toBeInTheDocument();
  });

  it('offers an optional gremium for addToNextSession and the cost-center pickers', async () => {
    await setup(
      {
        from: 'a',
        to: 'b',
        actions: [
          { type: 'addToNextSession' },
          { type: 'assignBudgetFromApplicantGremium', parentId: 'b1' },
          { type: 'assignBudgetFromMap', field: 'fs', map: { technik: 'b1', alt: 'gone' } },
        ],
      },
      { budgetTree: TREE },
    );
    expect(screen.getByText('Leer = Gremium der Abstimmung.')).toBeInTheDocument();
    // The pickers show the path key and the name, an unknown id shows no id.
    expect(screen.getAllByText('VSM · Studierendenschaft')).toHaveLength(2);
    expect(screen.getByText('Unbekannte Kostenstelle')).toBeInTheDocument();
    expect(screen.queryByText('gone')).toBeNull();
  });

  it('hides the cost-center actions when the target takes its gremium from the cost center', async () => {
    const { c } = await setup({ from: 'a', to: 'b', actions: [] }, { targetBudgetVote: true });
    const values = c.actionOptions().map((o: { value: string }) => o.value);
    expect(values).toContain('addToNextSession');
    expect(values).not.toContain('assignBudget');
    expect(values).not.toContain('assignBudgetFromMap');
  });

  it('edits the value → cost center rows through actionMapChange', async () => {
    const { c } = await setup({ from: 'a', to: 'b', actions: [] });
    const maps: unknown[] = [];
    c.actionMapChange.subscribe((e: { map: unknown }) => maps.push(e.map));
    const act = { type: 'assignBudgetFromMap', field: 'fs', map: { a: 'b1', b: 'b2' } };
    expect(c.mapRows(act)).toEqual([
      { value: 'a', budgetId: 'b1' },
      { value: 'b', budgetId: 'b2' },
    ]);
    expect(c.mapRows({ type: 'assignBudgetFromMap', map: ['x'] })).toEqual([]);
    expect(c.mapRows({ type: 'assignBudgetFromMap' })).toEqual([]);
    c.addMapRow(0, act);
    c.setMapValue(0, act, 0, 'c');
    c.setMapBudget(0, act, 1, 'b3');
    c.removeMapRow(0, act, 0);
    // A blank row exists: no second one.
    c.addMapRow(0, { type: 'assignBudgetFromMap', map: { '': '' } });
    expect(maps).toEqual([
      { a: 'b1', b: 'b2', '': '' },
      { c: 'b1', b: 'b2' },
      { a: 'b1', b: 'b3' },
      { b: 'b2' },
    ]);
    expect(c.hasBlankMapRow({ type: 'assignBudgetFromMap', map: { '': '' } })).toBe(true);
  });

  it('renders a map row per entry and an empty note without rows', async () => {
    const { container } = await setup(
      { from: 'a', to: 'b', actions: [{ type: 'assignBudgetFromMap', field: '', map: {} }] },
      { budgetTree: TREE },
    );
    expect(screen.getByText('Noch keine Zuordnung.')).toBeInTheDocument();
    expect(container.querySelectorAll('.td__mapRow')).toHaveLength(0);
  });
});
