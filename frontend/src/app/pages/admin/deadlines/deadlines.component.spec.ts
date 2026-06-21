import { of, throwError } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import userEvent from '@testing-library/user-event';
import type { DeadlinePolicy } from '../admin.models';
import { AdminApiService } from '../admin-api.service';
import { ToastService } from '@stupa-makers/ui-kit';
import { I18nService } from '@core/i18n/i18n.service';
import { AdminDeadlinesComponent } from './deadlines.component';

const POLICIES: DeadlinePolicy[] = [
  { id: 'dp-1', key: 'semester', label: { de: 'Semesterfrist', en: 'Semester' }, kind: 'absolute', absoluteAt: '2026-07-01T00:00:00Z' },
  { id: 'dp-2', key: 'edit_window', label: { de: 'Bearbeitung', en: 'Edit' }, kind: 'relative_changed', offsetDays: 7 },
];

function makeApi() {
  return {
    listDeadlinePolicies: jest.fn(() => of(POLICIES)),
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    createDeadlinePolicy: jest.fn((b: any) => of({ id: 'dp-new', ...b })),
    updateDeadlinePolicy: jest.fn((id: string, b: any) => of({ ...POLICIES[0], id, ...b })), // eslint-disable-line @typescript-eslint/no-explicit-any
    deleteDeadlinePolicy: jest.fn(() => of(void 0)),
  };
}

async function setup(api = makeApi()) {
  const toast = { success: jest.fn(), error: jest.fn() };
  const view = await render(AdminDeadlinesComponent, {
    providers: [
      { provide: AdminApiService, useValue: api },
      { provide: ToastService, useValue: toast },
    ],
  });
  return { ...view, api, toast };
}

describe('AdminDeadlinesComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('lists policies with key, kind and resolved value', async () => {
    await setup();
    expect(screen.getByText('Semesterfrist')).toBeInTheDocument();
    expect(screen.getByText('edit_window')).toBeInTheDocument();
    expect(screen.getByText('+ 7 Tage')).toBeInTheDocument();
  });

  it('creates a relative policy via the dialog', async () => {
    const { api, container } = await setup();
    await userEvent.click(screen.getByRole('button', { name: 'Frist hinzufügen' }));
    const q = (sel: string) => container.querySelector<HTMLElement>(sel)!;
    // key + relative kind + offset → save enabled.
    await userEvent.type(screen.getByLabelText('Schlüssel'), 'mahnung');
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Art' }), 'relative_submitted');
    await userEvent.type(q('input[name="offsetDays"]'), '14');
    await userEvent.click(screen.getByRole('button', { name: 'Speichern' }));
    expect(api.createDeadlinePolicy).toHaveBeenCalledWith(
      expect.objectContaining({ key: 'mahnung', kind: 'relative_submitted', offsetDays: 14, absoluteAt: null }),
    );
  });

  it('renders the absolute value as a localised date', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.valueOf(POLICIES[0])).toBe(new Date('2026-07-01T00:00:00Z').toLocaleDateString('de'));
  });

  it('valueOf shows an em-dash for missing absolute date / offset', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.valueOf({ kind: 'absolute', absoluteAt: null } as DeadlinePolicy)).toBe('—');
    expect(c.valueOf({ kind: 'relative_changed', offsetDays: null } as DeadlinePolicy)).toBe('—');
  });

  it('label resolves locale, then de, then key; null policy → empty', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.label(null)).toBe('');
    expect(c.label({ key: 'k', label: { de: 'DE' } } as DeadlinePolicy)).toBe('DE');
    const i18n = fixture.debugElement.injector.get(I18nService);
    i18n.setLocale('en');
    expect(c.label({ key: 'k', label: { en: 'EN', de: 'DE' } } as DeadlinePolicy)).toBe('EN');
    // missing both locale + de → falls back to the key
    expect(c.label({ key: 'fallback', label: {} } as DeadlinePolicy)).toBe('fallback');
  });

  it('openEdit pre-fills the draft from an existing absolute policy', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.openEdit(0);
    expect(c.editingId()).toBe('dp-1');
    const d = c.draft();
    expect(d.key).toBe('semester');
    expect(d.labelDe).toBe('Semesterfrist');
    expect(d.labelEn).toBe('Semester');
    expect(d.kind).toBe('absolute');
    expect(d.absoluteAt).toBe('2026-07-01');
  });

  it('openEdit on a relative policy carries the offset and empty label fallbacks', async () => {
    const relative: DeadlinePolicy[] = [
      { id: 'r-1', key: 'r', label: {}, kind: 'relative_submitted', offsetDays: 3 },
    ];
    const api = { ...makeApi(), listDeadlinePolicies: jest.fn(() => of(relative)) };
    const { fixture } = await setup(api);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.openEdit(0);
    const d = c.draft();
    expect(d.labelDe).toBe('');
    expect(d.labelEn).toBe('');
    expect(d.absoluteAt).toBe('');
    expect(d.offsetDays).toBe(3);
  });

  it('updates an existing policy in place on save', async () => {
    const { fixture, api, toast } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.openEdit(0);
    c.patch('labelDe', 'Neue Frist');
    c.save();
    expect(api.updateDeadlinePolicy).toHaveBeenCalledWith('dp-1', expect.objectContaining({
      kind: 'absolute',
      offsetDays: null,
    }));
    expect(c.policies().find((p: DeadlinePolicy) => p.id === 'dp-1')).toBeDefined();
    expect(toast.success).toHaveBeenCalled();
    expect(c.draft()).toBeNull();
  });

  it('canSave covers all gates', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    expect(c.canSave()).toBe(false); // no draft
    c.openAdd();
    expect(c.canSave()).toBe(false); // empty key
    c.patch('key', 'k');
    // absolute kind without a date
    expect(c.canSave()).toBe(false);
    c.patch('absoluteAt', '2026-01-01');
    expect(c.canSave()).toBe(true);
    // switch to relative: needs a non-negative offset
    c.patch('kind', 'relative_submitted');
    c.patch('offsetDays', null);
    expect(c.canSave()).toBe(false);
    c.patch('offsetDays', -1);
    expect(c.canSave()).toBe(false);
    c.patch('offsetDays', 0);
    expect(c.canSave()).toBe(true);
  });

  it('save is a no-op when it cannot save', async () => {
    const { fixture, api } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.openAdd(); // empty key → canSave false
    c.save();
    expect(api.createDeadlinePolicy).not.toHaveBeenCalled();
  });

  it('toasts on a save failure', async () => {
    const api = {
      ...makeApi(),
      createDeadlinePolicy: jest.fn(() => throwError(() => new Error('boom'))),
    };
    const { fixture, toast } = await setup(api);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.openAdd();
    c.patch('key', 'neu');
    c.patch('absoluteAt', '2026-01-01');
    c.save();
    expect(toast.error).toHaveBeenCalledWith('Speichern fehlgeschlagen.');
  });

  it('save uses key as label fallback when labels are blank', async () => {
    const { fixture, api } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.openAdd();
    c.patch('key', 'plain');
    c.patch('absoluteAt', '2026-01-01');
    c.save();
    expect(api.createDeadlinePolicy).toHaveBeenCalledWith(
      expect.objectContaining({ label: { de: 'plain', en: 'plain' } }),
    );
  });

  it('deletes a policy after confirmation', async () => {
    const { fixture, api, toast } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.askDelete(POLICIES[0]);
    expect(c.confirmDelete()).toEqual(POLICIES[0]);
    c.doDelete();
    expect(api.deleteDeadlinePolicy).toHaveBeenCalledWith('dp-1');
    expect(c.policies().some((p: DeadlinePolicy) => p.id === 'dp-1')).toBe(false);
    expect(c.confirmDelete()).toBeNull();
    expect(toast.success).toHaveBeenCalled();
  });

  it('doDelete is a no-op without a pending confirmation', async () => {
    const { fixture, api } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.doDelete();
    expect(api.deleteDeadlinePolicy).not.toHaveBeenCalled();
  });

  it('toasts on a delete failure', async () => {
    const api = {
      ...makeApi(),
      deleteDeadlinePolicy: jest.fn(() => throwError(() => new Error('boom'))),
    };
    const { fixture, toast } = await setup(api);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.askDelete(POLICIES[1]);
    c.doDelete();
    expect(toast.error).toHaveBeenCalledWith('Speichern fehlgeschlagen.');
  });

  it('close clears the draft and editing id', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.openEdit(0);
    c.close();
    expect(c.draft()).toBeNull();
    expect(c.editingId()).toBeNull();
  });

  it('patch is a no-op when there is no draft', async () => {
    const { fixture } = await setup();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const c = fixture.componentInstance as any;
    c.patch('key', 'x');
    expect(c.draft()).toBeNull();
  });
});
