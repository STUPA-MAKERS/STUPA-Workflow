import { of } from 'rxjs';
import { provideRouter } from '@angular/router';
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
    providers: [provideRouter([]), { provide: AdminApiService, useValue: api }],
  });
  return { ...view, listAuditLog };
}

describe('AuditLogComponent (#45)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('lists audit entries with cursor paging and human-readable rendering', async () => {
    const { fixture, listAuditLog } = await setup({
      items: [entry(1)],
      nextCursor: null,
      hasMore: false,
    });
    // Cursor request: no offset/total, no before on first load.
    expect(listAuditLog).toHaveBeenCalledWith(
      expect.objectContaining({ limit: 50, before: undefined }),
    );
    // Human-readable message filled from actor + target.
    expect(
      screen.getByText(/Root Admin hat Rollen\/Rechte geändert \(principal:p-1\)\./),
    ).toBeInTheDocument();
    // Localized action label appears as badge in the expanded details.
    screen.getByRole('button', { expanded: false }).click();
    fixture.detectChanges();
    expect(screen.getAllByText('Rollen/Rechte').length).toBeGreaterThan(0);
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

  it('prefers the resolved target label in the sentence', async () => {
    await setup({
      items: [
        entry(1, {
          action: 'status_change',
          targetType: 'application',
          targetId: 'a-1',
          targetLabel: 'Beamer kaufen',
        }),
      ],
      nextCursor: null,
      hasMore: false,
    });
    expect(screen.getByText(/Beamer kaufen/)).toBeInTheDocument();
    expect(screen.queryByText(/application:a-1/)).not.toBeInTheDocument();
  });

  it('groups entries under a day heading and expands details on click', async () => {
    const { fixture } = await setup({
      items: [entry(1, { data: { rows: 7 } })],
      nextCursor: null,
      hasMore: false,
    });
    // 2026-06-07 liegt in der Vergangenheit → volle Datums-Überschrift.
    expect(screen.getByRole('heading', { level: 2 }).textContent).toMatch(/2026/);
    // Details erst nach Klick auf die Zeile sichtbar.
    expect(screen.queryByText(/rows: 7/)).not.toBeInTheDocument();
    screen.getByRole('button', { expanded: false }).click();
    fixture.detectChanges();
    expect(screen.getByText(/rows: 7/)).toBeInTheDocument();
  });
});
