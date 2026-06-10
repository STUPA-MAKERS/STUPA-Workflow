import { of } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import type { AuditEntry, AuditPage } from '../admin.models';
import { AdminApiService } from '../admin-api.service';
import { AuditLogComponent } from './audit-log.component';

function entry(id: number, over: Partial<AuditEntry> = {}): AuditEntry {
  return {
    id,
    at: '2026-06-07T09:00:00+00:00',
    actor: 'kc|root',
    actorName: 'Root Admin',
    action: 'role_change',
    targetType: 'principal',
    targetId: 'p-1',
    data: {},
    hash: 'h',
    prevHash: null,
    ...over,
  };
}

async function setup(page: AuditPage) {
  const listAuditLog = jest.fn(() => of(page));
  const listAuditActors = jest.fn(() => of([]));
  const api = { listAuditLog, listAuditActors };
  const view = await render(AuditLogComponent, {
    providers: [{ provide: AdminApiService, useValue: api }],
  });
  return { ...view, listAuditLog };
}

describe('AuditLogComponent (#45)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('lists audit entries with cursor paging and human-readable rendering', async () => {
    const { listAuditLog } = await setup({ items: [entry(1)], nextCursor: null, hasMore: false });
    // Cursor request: no offset/total, no before on first load.
    expect(listAuditLog).toHaveBeenCalledWith(
      expect.objectContaining({ limit: 50, before: undefined }),
    );
    // Localized action label (not the raw key) — badge + filter option.
    expect(screen.getAllByText('Rollen/Rechte').length).toBeGreaterThan(0);
    // Human-readable message filled from actor + target.
    expect(
      screen.getByText(/Root Admin hat Rollen\/Rechte geändert \(principal:p-1\)\./),
    ).toBeInTheDocument();
  });

  it('renders a fallback message for unknown action types', async () => {
    await setup({
      items: [entry(1, { action: 'mystery_event', actorName: null })],
      nextCursor: null,
      hasMore: false,
    });
    // Fallback uses raw action + target; actor falls back to its sub.
    expect(screen.getByText(/mystery_event \(principal:p-1\)/)).toBeInTheDocument();
  });

  it('shows the empty state when there are no entries', async () => {
    await setup({ items: [], nextCursor: null, hasMore: false });
    expect(screen.getByText('Keine Audit-Einträge.')).toBeInTheDocument();
  });

  it('offers "load more" while more entries remain', async () => {
    await setup({ items: [entry(1)], nextCursor: 1, hasMore: true });
    expect(screen.getByRole('button', { name: 'Mehr laden' })).toBeInTheDocument();
  });
});
