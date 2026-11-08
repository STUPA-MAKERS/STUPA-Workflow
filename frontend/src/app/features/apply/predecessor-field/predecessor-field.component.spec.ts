import { fireEvent, render, screen } from '@testing-library/angular';
import { of, throwError } from 'rxjs';
import { ApiClient } from '@core/api/api-client.service';
import type { ApplicationListItem } from '@core/api/models';
import { predecessorErrorKey } from '../../../pages/applications/applications-detail.component';
import { PREDECESSOR_HITS, PredecessorFieldComponent } from './predecessor-field.component';

function item(id: string, title: string | null, state = true): ApplicationListItem {
  return {
    id,
    typeId: 't-1',
    title,
    state: state
      ? { id: 's-1', key: 'approved', label: 'Bewilligt', color: null, editAllowed: false, kind: 'normal' }
      : null,
    gremiumId: null,
    amount: null,
    currency: null,
    createdAt: '2025-05-12T10:00:00Z',
    updatedAt: '2025-05-12T10:00:00Z',
    archivedAt: null,
  };
}

const HITS = [item('a-1', 'Sommerfest 2025'), item('a-2', null, false), item('self', 'Dieser Antrag')];

async function setup(opts: { picked?: string | null; fail?: boolean } = {}) {
  const listApplications = jest.fn(() =>
    opts.fail ? throwError(() => new Error('x')) : of({ items: HITS, nextCursor: null }),
  );
  const choose = jest.fn();
  const cleared = jest.fn();
  const view = await render(PredecessorFieldComponent, {
    inputs: { typeId: 't-1', excludeId: 'self', picked: opts.picked ?? null },
    on: { choose, cleared },
    providers: [{ provide: ApiClient, useValue: { listApplications } }],
  });
  const type = (text: string) => {
    fireEvent.input(screen.getByRole('combobox', { name: 'Vorgänger' }), { target: { value: text } });
    view.fixture.componentInstance.search.flush();
    view.fixture.detectChanges();
  };
  return { ...view, listApplications, choose, cleared, type };
}

describe('PredecessorFieldComponent', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('searches Anträge of the type, archived ones too, without the Antrag itself', async () => {
    const { type, listApplications } = await setup();
    type('Sommer');
    expect(listApplications).toHaveBeenLastCalledWith({
      type: 't-1',
      q: 'Sommer',
      archived: 'all',
      limit: PREDECESSOR_HITS,
    });
    const options = screen.getAllByRole('option');
    expect(options).toHaveLength(2);
    expect(options[0]).toHaveTextContent('Sommerfest 2025');
    expect(options[0]).toHaveTextContent('Bewilligt');
    expect(options[1]).toHaveTextContent('Ohne Titel');
    expect(screen.queryByText('Dieser Antrag')).toBeNull();
  });

  it('emits the pick and closes the list', async () => {
    const { type, choose, fixture } = await setup();
    type('Sommer');
    fireEvent.click(screen.getAllByRole('option')[0]);
    fixture.detectChanges();
    expect(choose).toHaveBeenCalledWith(HITS[0]);
    expect(screen.queryByRole('option')).toBeNull();
    expect(fixture.componentInstance.query()).toBe('');
  });

  it('a failed search shows no hits', async () => {
    const { type } = await setup({ fail: true });
    type('Sommer');
    expect(screen.queryByRole('option')).toBeNull();
  });

  it('shows the picked Vorgänger with an × that clears it', async () => {
    const { cleared } = await setup({ picked: 'Sommerfest 2025' });
    expect(screen.getByText('Sommerfest 2025')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Vorgänger entfernen' }));
    expect(cleared).toHaveBeenCalled();
  });

  it('a new type drops the hits of the old one', async () => {
    const { type, fixture } = await setup();
    type('Sommer');
    expect(screen.getAllByRole('option')).toHaveLength(2);
    fixture.componentRef.setInput('typeId', 't-2');
    fixture.detectChanges();
    expect(screen.queryByRole('option')).toBeNull();
  });
});

describe('predecessorErrorKey', () => {
  it('names the reason of a refused link', () => {
    expect(predecessorErrorKey(422, 'predecessor_cycle')).toBe('applications.predecessor.errorCycle');
    expect(predecessorErrorKey(422, 'predecessor_type_mismatch')).toBe('applications.predecessor.errorType');
    expect(predecessorErrorKey(403, null)).toBe('applications.predecessor.errorForbidden');
    expect(predecessorErrorKey(500, undefined)).toBe('applications.predecessor.error');
  });
});
