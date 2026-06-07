import { of } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { NotificationRule } from '../admin.models';
import { AdminApiService } from '../admin-api.service';
import { NotificationRulesComponent } from './notification-rules.component';

async function setup(seed: NotificationRule[] = []) {
  const saveNotificationRule = jest.fn((r: NotificationRule) => of({ ...r, id: r.id || 'nr-new' }));
  const api = {
    listNotificationRules: jest.fn(() => of(seed)),
    saveNotificationRule,
    // Vom Options-Provider (#77) für die Empfänger-Dropdowns benötigt.
    listGremien: jest.fn(() => of([{ id: 'g-stupa', name: 'StuPa', slug: 'stupa', cdVariant: 'stupa', defaultLang: 'de' }])),
    listRoles: jest.fn(() => of([])),
  };
  const view = await render(NotificationRulesComponent, {
    providers: [{ provide: AdminApiService, useValue: api }],
  });
  return { ...view, saveNotificationRule };
}

describe('NotificationRulesComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('adds a rule and saves once the template key is set', async () => {
    const { saveNotificationRule } = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Regel hinzufügen' }));

    const save = screen.getByRole('button', { name: 'Speichern' });
    expect(save).toBeDisabled(); // templateKey empty

    await userEvent.type(screen.getByRole('textbox', { name: 'Vorlagen-Schlüssel' }), 'status_applicant');
    expect(save).toBeEnabled();
    await userEvent.click(save);
    expect(saveNotificationRule).toHaveBeenCalledTimes(1);
  });

  it('requires a ref for role/group recipients', async () => {
    await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Regel hinzufügen' }));
    await userEvent.type(screen.getByRole('textbox', { name: 'Vorlagen-Schlüssel' }), 'tpl');
    // comboboxes: [0] = event, [1] = recipient kind. Default applicant → valid.
    await userEvent.selectOptions(screen.getAllByRole('combobox')[1], 'role');
    expect(screen.getByText(/requires a ref/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Speichern' })).toBeDisabled();
  });

  it('exercises recipient mutators and labels', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.add();
    c.addRcpt(0); // adds a role recipient (ref empty)
    expect(c.rules()[0].recipients).toHaveLength(2);
    c.rules()[0].recipients[1].kind = 'applicant';
    c.onKind(0, 1); // applicant → ref stripped
    expect(c.rules()[0].recipients[1].ref).toBeUndefined();
    c.removeRcpt(0, 1);
    expect(c.rules()[0].recipients).toHaveLength(1);
    // Empfänger-Typen kommen als lokalisierte Dropdown-Optionen (#77).
    expect(c.kindOptions.find((o: { value: string }) => o.value === 'role').label).toBe('Rolle');
    c.remove(0);
    expect(c.rules()).toHaveLength(0);
  });
});
