import { of } from 'rxjs';
import { render, screen } from '@testing-library/angular';
import type { Page } from '@core/api/models';
import type { AuditEntry } from '../admin.models';
import { AdminApiService } from '../admin-api.service';
import { AuditLogComponent } from './audit-log.component';

type AuditPage = Page<AuditEntry>;

function entry(id: number): AuditEntry {
  return {
    id,
    at: '2026-06-07T09:00:00+00:00',
    actor: 'kc|root',
    action: 'role_change',
    targetType: 'principal',
    targetId: 'p-1',
    data: {},
    hash: 'h',
    prevHash: null,
  };
}

async function setup(page: AuditPage) {
  const listAuditLog = jest.fn(() => of(page));
  const api = { listAuditLog };
  const view = await render(AuditLogComponent, {
    providers: [{ provide: AdminApiService, useValue: api }],
  });
  return { ...view, listAuditLog };
}

describe('AuditLogComponent (#45)', () => {
  beforeEach(() => localStorage.setItem('ap.locale', 'de'));

  it('lists audit entries', async () => {
    const { listAuditLog } = await setup({ items: [entry(1)], total: 1, limit: 50, offset: 0 });
    expect(listAuditLog).toHaveBeenCalledWith({ limit: 50, offset: 0 });
    expect(screen.getByText('role_change')).toBeInTheDocument();
    expect(screen.getByText('principal:p-1')).toBeInTheDocument();
  });

  it('shows the empty state when there are no entries', async () => {
    await setup({ items: [], total: 0, limit: 50, offset: 0 });
    expect(screen.getByText('Keine Audit-Einträge.')).toBeInTheDocument();
  });

  it('offers "load more" while more entries remain', async () => {
    await setup({ items: [entry(1)], total: 5, limit: 50, offset: 0 });
    expect(screen.getByRole('button', { name: 'Mehr laden' })).toBeInTheDocument();
  });
});
